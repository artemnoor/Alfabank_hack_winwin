from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
T08 = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(T08))

import run_pilot  # noqa: E402
from jev_spike import DEFAULT_MODEL, make_request, request_hash  # noqa: E402


class ExpandedPilotDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.news, cls.cases, cls.taxonomy, cls.annotations = run_pilot._load_study()

    def test_frozen_inputs_have_50_unique_cases_and_matching_prelabels(self) -> None:
        self.assertEqual(len(self.cases), 50)
        self.assertEqual(len({case["id"] for case in self.cases}), 50)
        self.assertEqual(
            [case["id"] for case in self.cases],
            [row["case_id"] for row in self.annotations],
        )
        manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in (
            ("news.json", manifest["news_sha256"]),
            ("annotations.json", manifest["annotations_sha256"]),
        ):
            self.assertEqual(
                hashlib.sha256((HERE / name).read_bytes()).hexdigest(), expected
            )

    def test_every_label_uses_known_codes_and_quotes_existing_text(self) -> None:
        topic_codes = {row["code"] for row in self.taxonomy["topics"]}
        event_codes = {row["code"] for row in self.taxonomy["events"]}
        by_id = {case["id"]: case for case in self.cases}
        for label in self.annotations:
            self.assertIn(label["topic"], topic_codes)
            self.assertTrue(set(label["events"]).issubset(event_codes))
            for quote in label["evidence_spans"].values():
                self.assertIn(quote, by_id[label["case_id"]]["text"])
            self.assertEqual(label["label_status"], "preliminary_unapproved")

    def test_request_payload_excludes_all_annotation_fields_and_disables_fallbacks(
        self,
    ) -> None:
        case = self.cases[0]
        request = make_request(case, self.taxonomy, model=DEFAULT_MODEL)
        self.assertEqual(
            request["state"], {"title": case["title"], "text": case["text"]}
        )
        self.assertEqual(request["provider"], {"allow_fallbacks": False})
        self.assertFalse(any("expected" in str(key).lower() for key in request))
        self.assertEqual(len(request["questions"]), 18)
        self.assertEqual(set(run_pilot._load_study()[1][0]), {"id", "title", "text"})

    def test_request_allowlist_is_unique_and_matches_frozen_manifest(self) -> None:
        manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
        actual = {
            case["id"]: request_hash(
                make_request(case, self.taxonomy, model=DEFAULT_MODEL)
            )
            for case in self.cases
        }
        self.assertEqual(len(set(actual.values())), 50)
        self.assertEqual(actual, manifest["approved_request_sha256_by_case"])

    def test_cost_threshold_is_documented_as_soft_not_a_hard_cap(self) -> None:
        manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["cost_guard_is_hard_cap"])
        self.assertIn("may be exceeded by one request", manifest["price_reference"])

    def test_study_ledger_starts_empty_and_never_seeds_historical_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = run_pilot.StudyLedger(Path(directory) / "study.json")
            state = ledger.load()
            self.assertEqual(state["study_id"], run_pilot.STUDY_ID)
            self.assertEqual(state["attempts"], [])

    def test_incomplete_reserved_attempt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = run_pilot.StudyLedger(Path(directory) / "study.json")
            ledger.save(
                {
                    "schema_version": 1,
                    "study_id": run_pilot.STUDY_ID,
                    "attempts": [
                        {
                            "case_id": self.cases[0]["id"],
                            "request_sha256": "a" * 64,
                            "status": "reserved",
                            "timestamp_utc": "2026-10-15T00:00:00+00:00",
                            "error_code": None,
                            "result_sha256": None,
                        }
                    ],
                }
            )
            with self.assertRaisesRegex(
                run_pilot.SpikeError, "study_ledger_has_incomplete_attempt"
            ):
                ledger.load()

    def test_saved_result_is_revalidated_and_tampering_is_detected(self) -> None:
        case = self.cases[0]
        request = make_request(case, self.taxonomy, model=DEFAULT_MODEL)
        topic_id = self.taxonomy["topic_choice_id"]
        topic_codes = request["questions"][topic_id]["criteria"]
        selected = next(iter(topic_codes))
        answers = {
            topic_id: {
                "type": "choice",
                "choice": selected,
                "confidence": 1.0,
                "probabilities": {
                    code: float(code == selected) for code in topic_codes
                },
            }
        }
        for question_id in request["questions"]:
            if question_id != topic_id:
                answers[question_id] = {"type": "noul", "noul": 0.0}
        response = {
            "model": "jev-1.13.0",
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost_rub": 0.001},
        }
        result = run_pilot.interpret_response(
            case, response, request, self.taxonomy
        ).result
        result["request_sha256"] = request_hash(request)
        self.assertTrue(run_pilot._saved_result_is_valid(result, case, self.taxonomy))
        tampered = dict(result)
        tampered["unlisted_event_score"] = 0.95
        self.assertFalse(
            run_pilot._saved_result_is_valid(tampered, case, self.taxonomy)
        )

    def test_call_budget_rejects_over_cap_before_network_or_ledger_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = run_pilot.StudyLedger(Path(directory) / "study.json")
            with self.assertRaisesRegex(
                run_pilot.SpikeError, "call_count_out_of_range"
            ):
                run_pilot.run(51, ledger)
            self.assertFalse(ledger.path.exists())


if __name__ == "__main__":
    unittest.main()
