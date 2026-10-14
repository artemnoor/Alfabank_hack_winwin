from __future__ import annotations

import hashlib
import json
import unittest
from difflib import SequenceMatcher
from pathlib import Path

from build_t08_validation_assets import (
    ERROR_ANALYSIS,
    ERROR_MANIFEST,
    GOLD_REVIEW_PACKET,
    V041_MANIFEST,
    V041_TAXONOMY,
    VALIDATION_MANIFEST,
    VALIDATION_NEWS,
    build,
)

ROOT = Path(__file__).resolve().parent


class T08ValidationAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build()

    def test_taxonomy_proposal_is_separate_and_keeps_public_registry(self) -> None:
        proposed = json.loads(V041_TAXONOMY.read_text(encoding="utf-8"))
        manifest = json.loads(V041_MANIFEST.read_text(encoding="utf-8"))
        v03 = json.loads((ROOT / "taxonomy.json").read_text(encoding="utf-8"))
        v04 = json.loads(
            (ROOT / "experiments/taxonomy-v0.4-proposal/taxonomy.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(proposed["version"], "0.4.1-spike")
        self.assertEqual(proposed["status"], "unvalidated-experimental-proposal")
        self.assertEqual(manifest["approval"], "awaiting_user_review")
        self.assertEqual(manifest["live_requests"], 0)
        self.assertEqual(
            [row["code"] for row in proposed["topics"]],
            [row["code"] for row in v03["topics"]],
        )
        self.assertEqual(
            [row["code"] for row in proposed["events"]],
            [row["code"] for row in v03["events"]],
        )
        for field in (
            "topic_choice_id",
            "unlisted_event_question",
            "uncertainty_question",
        ):
            self.assertEqual(proposed[field], v04[field])
        self.assertEqual(
            hashlib.sha256(V041_TAXONOMY.read_bytes()).hexdigest(),
            manifest["proposal_sha256"],
        )

    def test_proposal_resolves_only_the_reviewed_taxonomy_boundaries(self) -> None:
        proposed = json.loads(V041_TAXONOMY.read_text(encoding="utf-8"))
        events = {row["code"]: row for row in proposed["events"]}
        rules = "\n".join(proposed["annotation_rules"])
        self.assertIn(
            "trade_restriction", events["regulation_tax_change"]["exclude"].lower()
        )
        self.assertIn("пожар", events["environment_disaster_impact"]["exclude"].lower())
        self.assertIn(
            "выпуска", events["production_operational_disruption"]["exclude"].lower()
        )
        self.assertIn("штраф", events["sanctions"]["exclude"].lower())
        self.assertIn("расследован", events["legal_enforcement"]["include"].lower())
        self.assertIn(
            "закрыт", events["corporate_transaction_restructuring"]["include"].lower()
        )
        self.assertIn(
            "нехват", events["shortage_capacity_constraint"]["include"].lower()
        )
        self.assertIn("trade_restriction", rules)
        self.assertIn("legal_enforcement", rules)

    def test_visible_validation_candidate_has_new_unlabeled_inputs_only(self) -> None:
        manifest = json.loads(VALIDATION_MANIFEST.read_text(encoding="utf-8"))
        document = json.loads(VALIDATION_NEWS.read_text(encoding="utf-8"))
        cases = document["cases"]
        self.assertEqual(len(cases), 60)
        self.assertEqual(manifest["dataset_id"], "t08-visible-validation-candidates")
        self.assertEqual(manifest["version"], "1.1.0")
        self.assertEqual(manifest["case_count"], 60)
        self.assertEqual(manifest["status"], "awaiting_human_annotation")
        self.assertFalse(manifest["eligible_for_model_scoring"])
        self.assertEqual(manifest["benchmark_role"], "visible_validation_candidate")
        self.assertFalse(manifest["eligible_as_blind_test"])
        self.assertFalse(manifest["is_genuinely_blind"])
        self.assertFalse(manifest["blind_to_inputs"])
        self.assertTrue(manifest["blind_to_model_outputs"])
        self.assertEqual(manifest["gold_label_status"], "not_created")
        self.assertEqual(
            hashlib.sha256(VALIDATION_NEWS.read_bytes()).hexdigest(),
            manifest["input_sha256"],
        )
        ids = [case["id"] for case in cases]
        texts = [case["text"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(case_id.startswith("validation-v1-") for case_id in ids))
        self.assertEqual(len(texts), len(set(texts)))
        for case in cases:
            self.assertEqual(set(case), {"id", "title", "text"})
            self.assertTrue(case["title"].strip())
            self.assertTrue(case["text"].strip())

    def test_visible_validation_candidate_is_excluded_from_current_scoring(
        self,
    ) -> None:
        manifest = json.loads(VALIDATION_MANIFEST.read_text(encoding="utf-8"))
        error_report = json.loads(ERROR_ANALYSIS.read_text(encoding="utf-8"))
        error_manifest = json.loads(ERROR_MANIFEST.read_text(encoding="utf-8"))
        quality_report = (ROOT / "QUALITY_ANALYSIS.json").read_text(encoding="utf-8")
        validation_cases = json.loads(VALIDATION_NEWS.read_text(encoding="utf-8"))[
            "cases"
        ]
        self.assertEqual(manifest["excluded_from_current_reports"], True)
        self.assertEqual(error_report["saved_answer_count"], 45)
        self.assertEqual(len(error_report["false_positives"]), 6)
        self.assertEqual(len(error_report["false_negatives"]), 7)
        self.assertEqual(
            hashlib.sha256(ERROR_ANALYSIS.read_bytes()).hexdigest(),
            error_manifest["analysis_sha256"],
        )
        self.assertTrue(
            all(case["id"] not in quality_report for case in validation_cases)
        )

    def test_validation_candidate_texts_are_new_against_existing_spike_corpora(
        self,
    ) -> None:
        validation = json.loads(VALIDATION_NEWS.read_text(encoding="utf-8"))["cases"]
        old_texts = {
            " ".join(case["text"].casefold().split())
            for case in json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))[
                "cases"
            ]
            if case.get("text", "").strip()
        }
        deep_root = ROOT / "experiments" / "deep-v1"
        deep_manifest = json.loads(
            (deep_root / "manifest.json").read_text(encoding="utf-8")
        )
        for split in deep_manifest["splits"].values():
            document = json.loads(
                (deep_root / split["path"]).read_text(encoding="utf-8")
            )
            old_texts.update(
                " ".join(case["text"].casefold().split())
                for case in document["cases"]
                if case.get("text", "").strip()
            )
        new_texts = {" ".join(case["text"].casefold().split()) for case in validation}
        self.assertFalse(new_texts & old_texts)

    def test_validation_candidate_has_no_high_text_similarity_to_existing_corpora(
        self,
    ) -> None:
        validation = json.loads(VALIDATION_NEWS.read_text(encoding="utf-8"))["cases"]
        existing = [
            " ".join(case["text"].casefold().split())
            for case in json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))[
                "cases"
            ]
            if case.get("text", "").strip()
        ]
        deep_root = ROOT / "experiments" / "deep-v1"
        deep_manifest = json.loads(
            (deep_root / "manifest.json").read_text(encoding="utf-8")
        )
        for split in deep_manifest["splits"].values():
            document = json.loads(
                (deep_root / split["path"]).read_text(encoding="utf-8")
            )
            existing.extend(
                " ".join(case["text"].casefold().split())
                for case in document["cases"]
                if case.get("text", "").strip()
            )
        maximum = max(
            SequenceMatcher(
                None, " ".join(case["text"].casefold().split()), old_text
            ).ratio()
            for case in validation
            for old_text in existing
        )
        self.assertLess(maximum, 0.72)
        candidate_texts = [
            " ".join(case["text"].casefold().split()) for case in validation
        ]
        internal_maximum = max(
            SequenceMatcher(
                None, candidate_texts[index], candidate_texts[other]
            ).ratio()
            for index in range(len(candidate_texts))
            for other in range(index + 1, len(candidate_texts))
        )
        self.assertLess(internal_maximum, 0.72)

    def test_human_packet_blinds_all_baseline_cases_to_model_and_draft_labels(
        self,
    ) -> None:
        packet = GOLD_REVIEW_PACKET.read_text(encoding="utf-8")
        manifest = json.loads(ERROR_MANIFEST.read_text(encoding="utf-8"))
        corpus_cases = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))[
            "cases"
        ]
        nonempty = [case for case in corpus_cases if case.get("text", "").strip()]
        aliases = [
            line for line in packet.splitlines() if line.startswith("### Случай ")
        ]
        self.assertEqual(len(aliases), len(nonempty))
        self.assertIn("не только кейсы, на которых Jev расходился", packet)
        self.assertIn("корпус уже виден владельцу", packet)
        for case in nonempty:
            self.assertIn(case["title"], packet)
            self.assertIn(case["text"], packet)
            self.assertNotIn(case["id"], packet)
        self.assertNotIn("expected_events", packet)
        self.assertNotIn("candidate_codes", packet)
        self.assertNotIn("topic_confidence", packet)
        self.assertNotIn("0.87", packet)
        self.assertEqual(manifest["packet_case_count"], 49)
        self.assertFalse(manifest["packet_contains_source_ids"])
        self.assertFalse(manifest["packet_contains_draft_labels_or_model_outputs"])
        self.assertFalse(manifest["owner_blind"])
        self.assertEqual(
            hashlib.sha256(GOLD_REVIEW_PACKET.read_bytes()).hexdigest(),
            manifest["model_blind_review_packet_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
