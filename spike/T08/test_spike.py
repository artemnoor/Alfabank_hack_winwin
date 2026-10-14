from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError

from jev_spike import (
    API_ENDPOINT,
    CORPUS_PATH,
    DEFAULT_MODEL,
    SUPPORTED_MODEL_ALIASES,
    TAXONOMY_PATH,
    TRUSTED_CORPUS_SHA256,
    TRUSTED_TAXONOMY_SHA256,
    JevClient,
    LiveRequestError,
    NoContentError,
    SpikeError,
    approved_request_hashes,
    evaluate,
    https_transport,
    interpret_response,
    load_pinned_json,
    load_verified_inputs,
    make_request,
    no_content_result,
    request_hash,
    taxonomy_hash,
    validate_corpus,
    validate_response,
    validate_taxonomy,
)

TAXONOMY, CORPUS, CASES = load_verified_inputs()


def _valid_response(
    request: dict[str, Any],
    *,
    topic: str | None = None,
    event_scores: dict[str, float] | None = None,
    unlisted_score: float = 0.0,
    uncertainty_score: float = 0.0,
) -> dict[str, Any]:
    topic_id = TAXONOMY["topic_choice_id"]
    topic_codes = list(request["questions"][topic_id]["criteria"])
    selected = topic or topic_codes[0]
    probabilities = {code: (1.0 if code == selected else 0.0) for code in topic_codes}
    answers: dict[str, Any] = {
        topic_id: {
            "type": "choice",
            "choice": selected,
            "confidence": 1.0,
            "probabilities": probabilities,
        }
    }
    scores = event_scores or {}
    for question_id in request["questions"]:
        if question_id == topic_id:
            continue
        if question_id == TAXONOMY["unlisted_event_code"]:
            value = unlisted_score
        elif question_id == TAXONOMY["uncertainty_signal_code"]:
            value = uncertainty_score
        else:
            value = scores.get(question_id.removeprefix("event_"), 0.0)
        answers[question_id] = {"type": "noul", "noul": value}
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


class TaxonomyAndCorpusTests(unittest.TestCase):
    def test_taxonomy_is_versioned_unique_and_experimental(self) -> None:
        validate_taxonomy(TAXONOMY)
        self.assertEqual(TAXONOMY["status"], "experimental-proposal")
        self.assertEqual(len(TAXONOMY["events"]), 15)
        self.assertEqual(TAXONOMY["other_code"], "other_uncertain")

    def test_corpus_has_49_synthetic_news_plus_empty_case(self) -> None:
        cases = validate_corpus(CORPUS, TAXONOMY)
        non_empty = [
            case for case in cases if case["title"].strip() or case["text"].strip()
        ]
        self.assertEqual(len(cases), 50)
        self.assertEqual(len(non_empty), 49)
        self.assertEqual(sum(case["case_type"] == "multi_event" for case in cases), 9)
        self.assertEqual(sum(case["case_type"] == "empty_input" for case in cases), 1)

    def test_live_request_allowlist_covers_only_pinned_baseline(self) -> None:
        hashes = approved_request_hashes(CASES, TAXONOMY, model=DEFAULT_MODEL)
        self.assertEqual(len(hashes), 49)

    def test_each_event_has_two_manual_positive_examples(self) -> None:
        cases = validate_corpus(CORPUS, TAXONOMY)
        for event in TAXONOMY["events"]:
            positives = [
                case for case in cases if event["code"] in case["expected_events"]
            ]
            self.assertGreaterEqual(len(positives), 2, event["code"])

    def test_taxonomy_hash_tracks_definition_changes(self) -> None:
        invalid = copy.deepcopy(TAXONOMY)
        before = taxonomy_hash(invalid)
        invalid["events"][0]["definition"] += " Уточнение для пилотного сравнения."
        validate_taxonomy(invalid)
        self.assertNotEqual(before, taxonomy_hash(invalid))

    def test_corpus_cannot_reference_category_outside_registry(self) -> None:
        invalid = copy.deepcopy(CORPUS)
        invalid["cases"][0]["expected_events"] = ["invented_category"]
        with self.assertRaisesRegex(SpikeError, "Unknown gold event"):
            validate_corpus(invalid, TAXONOMY)

    def test_empty_case_is_stopped_before_provider_request(self) -> None:
        case = next(case for case in CASES if case["expected_status"] == "no_content")
        with self.assertRaises(NoContentError):
            make_request(case, TAXONOMY)
        self.assertEqual(
            no_content_result(case, TAXONOMY)["classification_status"], "no_content"
        )

    def test_unapproved_live_corpus_is_rejected(self) -> None:
        invalid = copy.deepcopy(CORPUS)
        invalid["status"] = "live-news"
        with self.assertRaisesRegex(SpikeError, "hand-labeled synthetic"):
            validate_corpus(invalid, TAXONOMY)

    def test_live_corpus_bytes_are_pinned_even_if_status_stays_synthetic(self) -> None:
        altered = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        altered["cases"][0]["text"] += " Подменённый текст."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps(altered, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(SpikeError, "Unapproved changes"):
                load_pinned_json(path, TRUSTED_CORPUS_SHA256)

    def test_live_taxonomy_bytes_are_pinned(self) -> None:
        altered = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
        altered["topics"][0]["definition"] += " Изменено."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "taxonomy.json"
            path.write_text(json.dumps(altered, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(SpikeError, "Unapproved changes"):
                load_pinned_json(path, TRUSTED_TAXONOMY_SHA256)

    def test_out_of_taxonomy_case_uses_explicit_other(self) -> None:
        case = next(case for case in CASES if case["case_type"] == "out_of_taxonomy")
        request = make_request(case, TAXONOMY)
        response = _valid_response(request, topic="other_uncertain")
        result = interpret_response(case, response, request, TAXONOMY).result
        self.assertEqual(result["classification_status"], "other")
        self.assertEqual(result["predicted_events"], [])

    def test_missing_topic_evidence_uses_uncertain_review_path(self) -> None:
        case = next(case for case in CASES if case["id"] == "e50-uncertain-topic")
        request = make_request(case, TAXONOMY)
        response = _valid_response(
            request, topic="other_uncertain", uncertainty_score=0.91
        )
        result = interpret_response(case, response, request, TAXONOMY).result
        self.assertEqual(result["topic"], "other_uncertain")
        self.assertEqual(result["classification_status"], "uncertain")

    def test_unlisted_business_event_scope_excludes_macro_rate_news(self) -> None:
        macro = next(case for case in CASES if case["id"] == "e36-noevent-rates")
        unlisted = next(
            case for case in CASES if case["id"] == "e47-unlisted-contract-award"
        )
        self.assertFalse(macro["expected_unlisted_event"])
        self.assertTrue(unlisted["expected_unlisted_event"])

    def test_legal_enforcement_requires_a_distinct_legal_development(self) -> None:
        by_id = {case["id"]: set(case["expected_events"]) for case in CASES}
        self.assertEqual(by_id["e19-insolvency-court"], {"insolvency_default"})
        self.assertEqual(by_id["e12-sanctions-assets"], {"sanctions"})
        self.assertEqual(
            by_id["e34-multi-insolvency-legal"],
            {"insolvency_default", "legal_enforcement"},
        )
        self.assertIn("legal_enforcement", by_id["e25-legal-fine"])
        self.assertIn("legal_enforcement", by_id["e26-legal-investigation"])


class RequestAndResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = next(
            case for case in CASES if case["id"] == "e31-multi-sanction-trade"
        )
        self.request = make_request(self.case, TAXONOMY)

    def test_uses_one_choice_and_one_noul_per_independent_event(self) -> None:
        questions = self.request["questions"]
        self.assertEqual(questions[TAXONOMY["topic_choice_id"]]["type"], "choice")
        self.assertEqual(
            sum(question["type"] == "noul" for question in questions.values()), 17
        )
        self.assertLessEqual(len(questions), 20)
        self.assertNotIn("extract", json.dumps(self.request))

    def test_request_has_no_free_form_category_generation(self) -> None:
        request_json = json.dumps(self.request, ensure_ascii=False)
        self.assertIn("other_uncertain", request_json)
        self.assertIn(TAXONOMY["unlisted_event_question"], request_json)
        self.assertIn(TAXONOMY["uncertainty_question"], request_json)
        self.assertNotIn("Generate a new category", request_json)

    def test_only_approved_jev_alias_is_allowed(self) -> None:
        self.assertEqual(SUPPORTED_MODEL_ALIASES, {"jev-latest"})
        with self.assertRaisesRegex(SpikeError, "invalid model alias"):
            make_request(self.case, TAXONOMY, model="some-other-model")

    def test_unknown_choice_is_rejected(self) -> None:
        response = _valid_response(self.request)
        answer = response["answers"][TAXONOMY["topic_choice_id"]]
        answer["choice"] = "invented"
        with self.assertRaisesRegex(SpikeError, "unknown or invalid topic"):
            validate_response(response, self.request, TAXONOMY)

    def test_malformed_choice_probabilities_are_rejected(self) -> None:
        response = _valid_response(self.request)
        response["answers"][TAXONOMY["topic_choice_id"]]["probabilities"][
            "economy_finance"
        ] = 0.25
        with self.assertRaisesRegex(SpikeError, "do not sum to one"):
            validate_response(response, self.request, TAXONOMY)

    def test_unexpected_or_missing_question_answer_is_rejected(self) -> None:
        response = _valid_response(self.request)
        response["answers"].pop("event_sanctions")
        with self.assertRaisesRegex(SpikeError, "question set"):
            validate_response(response, self.request, TAXONOMY)

    def test_malformed_noul_score_is_rejected(self) -> None:
        response = _valid_response(self.request)
        response["answers"]["event_sanctions"]["noul"] = 1.2
        with self.assertRaisesRegex(SpikeError, "invalid Noul"):
            validate_response(response, self.request, TAXONOMY)

    def test_non_jev_resolved_model_version_is_rejected(self) -> None:
        response = _valid_response(self.request)
        response["model"] = "gpt-4o"
        with self.assertRaisesRegex(SpikeError, "resolved model version"):
            validate_response(response, self.request, TAXONOMY)

    def test_independent_event_questions_preserve_all_positive_labels(self) -> None:
        event_scores = {
            "sanctions": 0.94,
            "trade_restriction": 0.91,
        }
        response = _valid_response(
            self.request, topic="politics_government", event_scores=event_scores
        )
        result = interpret_response(self.case, response, self.request, TAXONOMY).result
        self.assertEqual(set(result["predicted_events"]), set(event_scores))
        self.assertEqual(result["topic"], "politics_government")

    def test_uncertain_and_unlisted_are_fail_closed(self) -> None:
        response = _valid_response(self.request, topic="other_uncertain")
        result = interpret_response(self.case, response, self.request, TAXONOMY).result
        self.assertEqual(result["classification_status"], "other")
        response = _valid_response(
            self.request, topic="industry_trade_supply", unlisted_score=0.91
        )
        result = interpret_response(self.case, response, self.request, TAXONOMY).result
        self.assertEqual(result["classification_status"], "uncertain")
        self.assertEqual(result["predicted_events"], [])
        response = _valid_response(
            self.request, topic="industry_trade_supply", uncertainty_score=0.5
        )
        result = interpret_response(self.case, response, self.request, TAXONOMY).result
        self.assertEqual(result["classification_status"], "uncertain")

    def test_prompt_injection_is_article_data_not_taxonomy_mutation(self) -> None:
        injected = next(case for case in CASES if case["id"] == "e45-injection-rumor")
        request = make_request(injected, TAXONOMY)
        self.assertIn("Игнорируй критерии", request["state"]["text"])
        self.assertEqual(
            set(request["questions"][TAXONOMY["topic_choice_id"]]["criteria"]),
            {row["code"] for row in TAXONOMY["topics"]},
        )
        self.assertEqual(
            set(request["questions"][TAXONOMY["topic_choice_id"]]["criteria"]),
            set(self.request["questions"][TAXONOMY["topic_choice_id"]]["criteria"]),
        )


class TransportSafetyTests(unittest.TestCase):
    def test_client_posts_to_fixed_official_endpoint_and_never_logs_key(self) -> None:
        seen: dict[str, Any] = {}

        def fake_transport(
            url: str, payload: bytes, headers: dict[str, str], timeout: int
        ) -> bytes:
            seen.update(
                {"url": url, "payload": payload, "headers": headers, "timeout": timeout}
            )
            case = CASES[0]
            request = make_request(case, TAXONOMY)
            return json.dumps(_valid_response(request)).encode("utf-8")

        case = CASES[0]
        request = make_request(case, TAXONOMY)
        client = JevClient(
            "unit-test-fixture",
            allowed_request_hashes={request_hash(request)},
            transport=fake_transport,
        )
        response = client.classify(request)
        self.assertEqual(seen["url"], API_ENDPOINT)
        self.assertEqual(seen["timeout"], 30)
        self.assertEqual(seen["headers"]["Authorization"], "Bearer unit-test-fixture")
        self.assertNotIn(b"unit-test-fixture", seen["payload"])
        self.assertIn(case["text"].encode("utf-8"), seen["payload"])
        self.assertNotIn("unit-test-fixture", json.dumps(response))
        self.assertNotIn(case["text"], json.dumps(response))

    def test_provider_exception_text_is_suppressed(self) -> None:
        def broken_transport(*_: Any) -> bytes:
            raise RuntimeError("secret-and-article-body-must-not-leak")

        request = make_request(CASES[0], TAXONOMY)
        client = JevClient(
            "key",
            allowed_request_hashes={request_hash(request)},
            transport=broken_transport,
        )
        with self.assertRaises(LiveRequestError) as captured:
            client.classify(request)
        self.assertEqual(str(captured.exception), "transport_error")
        self.assertNotIn("secret-and-article-body", str(captured.exception))

    def test_redirects_are_refused(self) -> None:
        from jev_spike import _NoRedirect

        handler = _NoRedirect()
        with self.assertRaises(LiveRequestError) as captured:
            handler.redirect_request(
                None, None, 302, "Found", {}, "https://attacker.example/collect"
            )
        self.assertEqual(str(captured.exception), "redirect_refused")

    def test_http_error_body_is_suppressed(self) -> None:
        class FailingOpener:
            def open(self, *_: Any, **__: Any) -> bytes:
                raise HTTPError(
                    API_ENDPOINT,
                    451,
                    "Unavailable",
                    hdrs=None,
                    fp=io.BytesIO(b"provider echoed canary-secret"),
                )

        with (
            patch("urllib.request.build_opener", return_value=FailingOpener()),
            self.assertRaises(LiveRequestError) as captured,
        ):
            https_transport(API_ENDPOINT, b"safe synthetic request", {}, 30)
        self.assertEqual(str(captured.exception), "http_status_451")
        self.assertNotIn("canary-secret", str(captured.exception))

    def test_timeout_is_fixed_and_bounded(self) -> None:
        self.assertEqual(make_request(CASES[0], TAXONOMY)["model"], "jev-latest")
        seen: list[int] = []

        def fake_transport(
            _url: str, _payload: bytes, _headers: dict[str, str], timeout: int
        ) -> bytes:
            seen.append(timeout)
            request = make_request(CASES[0], TAXONOMY)
            return json.dumps(_valid_response(request)).encode("utf-8")

        request = make_request(CASES[0], TAXONOMY)
        JevClient(
            "key",
            allowed_request_hashes={request_hash(request)},
            transport=fake_transport,
        ).classify(request)
        self.assertEqual(seen, [30])

    def test_request_not_in_verified_allowlist_never_reaches_transport(self) -> None:
        sent: list[bytes] = []

        def fake_transport(
            _url: str, payload: bytes, _headers: dict[str, str], _timeout: int
        ) -> bytes:
            sent.append(payload)
            return b"{}"

        approved = make_request(CASES[0], TAXONOMY)
        unapproved = make_request(CASES[1], TAXONOMY)
        client = JevClient(
            "key",
            allowed_request_hashes={request_hash(approved)},
            transport=fake_transport,
        )
        with self.assertRaisesRegex(SpikeError, "request_not_authorized"):
            client.classify(unapproved)
        self.assertEqual(sent, [])

    def test_each_approved_request_can_be_sent_only_once(self) -> None:
        request = make_request(CASES[0], TAXONOMY)
        client = JevClient(
            "key",
            allowed_request_hashes={request_hash(request)},
            transport=lambda *_: b"{}",
        )
        raw_response = client.classify(request)
        with self.assertRaisesRegex(SpikeError, "invalid response shape"):
            validate_response(raw_response, request, TAXONOMY)
        with self.assertRaisesRegex(SpikeError, "request_already_used"):
            client.classify(request)


class EvaluationTests(unittest.TestCase):
    def test_quality_metrics_and_threshold_sweep_match_perfect_fixture(self) -> None:
        results: list[dict[str, Any]] = []
        for case in CASES:
            if case["expected_status"] == "no_content":
                results.append(no_content_result(case, TAXONOMY))
                continue
            request = make_request(case, TAXONOMY)
            event_scores = {
                event["code"]: 0.99
                if event["code"] in case["expected_events"]
                else 0.01
                for event in TAXONOMY["events"]
            }
            response = _valid_response(
                request, topic=case["expected_topic"], event_scores=event_scores
            )
            response["answers"][TAXONOMY["unlisted_event_code"]]["noul"] = (
                0.99 if case["expected_unlisted_event"] else 0.01
            )
            response["answers"][TAXONOMY["uncertainty_signal_code"]]["noul"] = (
                0.99 if case["expected_uncertainty_signal"] else 0.01
            )
            results.append(interpret_response(case, response, request, TAXONOMY).result)
        metrics = evaluate(CASES, results, TAXONOMY)
        self.assertTrue(metrics["evaluation_complete"])
        self.assertEqual(metrics["evaluation_coverage"], 1.0)
        self.assertEqual(metrics["topic_accuracy"], 1.0)
        self.assertEqual(metrics["event_micro_f1"], 1.0)
        self.assertEqual(metrics["event_macro_f1"], 1.0)
        self.assertEqual(metrics["event_threshold"], 0.8)
        self.assertEqual(len(metrics["threshold_sweep"]), 9)
        self.assertEqual(metrics["expected_unlisted_event_count"], 1)
        self.assertTrue(metrics["unlisted_event_exact"])
        self.assertEqual(metrics["expected_uncertainty_signal_count"], 6)
        self.assertEqual(metrics["uncertainty_signal_precision"], 1.0)
        self.assertEqual(metrics["uncertainty_signal_recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
