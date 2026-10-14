from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from typing import Any, Self
from unittest.mock import patch
from urllib.error import HTTPError, URLError

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


def _block_network(*_: Any, **__: Any) -> None:
    raise AssertionError("offline test attempted a network operation")


_NETWORK_PATCHERS = [
    patch("socket.create_connection", side_effect=_block_network),
    patch("socket.getaddrinfo", side_effect=_block_network),
    patch("socket.socket.connect", side_effect=_block_network),
    patch("socket.socket.connect_ex", side_effect=_block_network),
    patch("socket.socket.sendto", side_effect=_block_network),
]


def setUpModule() -> None:
    for network_patcher in _NETWORK_PATCHERS:
        network_patcher.start()


def tearDownModule() -> None:
    for network_patcher in reversed(_NETWORK_PATCHERS):
        network_patcher.stop()


def _valid_response(
    request: dict[str, Any],
    *,
    topic: str | None = None,
    topic_confidence: float = 1.0,
    topic_probabilities: dict[str, float] | None = None,
    event_scores: dict[str, float] | None = None,
    unlisted_score: float = 0.0,
    uncertainty_score: float = 0.0,
) -> dict[str, Any]:
    topic_id = TAXONOMY["topic_choice_id"]
    topic_codes = list(request["questions"][topic_id]["criteria"])
    selected = topic or topic_codes[0]
    probabilities = topic_probabilities or {
        code: (1.0 if code == selected else 0.0) for code in topic_codes
    }
    answers: dict[str, Any] = {
        topic_id: {
            "type": "choice",
            "choice": selected,
            "confidence": topic_confidence,
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
        "usage": {"input_tokens": 1, "output_tokens": 1, "cost_rub": 0.002},
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

    def test_pinned_loader_rejects_malformed_json_even_with_matching_hash(self) -> None:
        malformed = b'{"cases": ['
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed.json"
            path.write_bytes(malformed)
            with self.assertRaisesRegex(SpikeError, "Cannot parse spike data"):
                load_pinned_json(path, hashlib.sha256(malformed).hexdigest())

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
        self.assertEqual(API_ENDPOINT, "https://polza.ai/api/v1/systemone")
        self.assertEqual(set(self.request), {"state", "model", "questions", "provider"})
        self.assertEqual(set(self.request["state"]), {"title", "text"})
        self.assertEqual(self.request["model"], "typesafe/jev")
        self.assertEqual(self.request["provider"], {"allow_fallbacks": False})
        self.assertEqual(
            set(self.request["questions"][TAXONOMY["topic_choice_id"]]),
            {"type", "instructions", "criteria"},
        )
        self.assertTrue(
            all(
                question["type"] == "noul"
                and set(question["criteria"]) == {"true", "false"}
                for question_id, question in self.request["questions"].items()
                if question_id != TAXONOMY["topic_choice_id"]
            )
        )
        self.assertIn("other_uncertain", request_json)
        self.assertIn(TAXONOMY["unlisted_event_question"], request_json)
        self.assertIn(TAXONOMY["uncertainty_question"], request_json)
        self.assertNotIn("Generate a new category", request_json)

    def test_choice_option_count_respects_official_255_limit(self) -> None:
        oversized = copy.deepcopy(TAXONOMY)
        while len(oversized["topics"]) <= 255:
            index = len(oversized["topics"])
            oversized["topics"].append(
                {
                    "code": f"synthetic_topic_{index}",
                    "label": f"Test topic {index}",
                    "definition": "Test-only option",
                }
            )
        with self.assertRaisesRegex(SpikeError, "255-option limit"):
            make_request(CASES[0], oversized)

    def test_only_approved_jev_alias_is_allowed(self) -> None:
        self.assertEqual(SUPPORTED_MODEL_ALIASES, {"typesafe/jev"})
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

    def test_choice_must_be_one_of_the_maximum_probability_options(self) -> None:
        response = _valid_response(self.request)
        answer = response["answers"][TAXONOMY["topic_choice_id"]]
        codes = list(answer["probabilities"])
        answer["probabilities"] = {
            code: (0.3 if index == 0 else 0.7 if index == 1 else 0.0)
            for index, code in enumerate(codes)
        }
        with self.assertRaisesRegex(SpikeError, "not a maximum-probability"):
            validate_response(response, self.request, TAXONOMY)

    def test_choice_confidence_does_not_assume_an_undocumented_formula(self) -> None:
        response = _valid_response(self.request)
        response["answers"][TAXONOMY["topic_choice_id"]]["confidence"] = 0.47
        validate_response(response, self.request, TAXONOMY)

    def test_choice_confidence_allows_documented_example_rounding(self) -> None:
        request = copy.deepcopy(self.request)
        question = request["questions"][TAXONOMY["topic_choice_id"]]
        codes = list(question["criteria"])[:3]
        question["criteria"] = {code: "test option" for code in codes}
        response = _valid_response(
            request,
            topic=codes[0],
            topic_confidence=0.81,
            topic_probabilities={codes[0]: 0.88, codes[1]: 0.12, codes[2]: 0.0},
        )
        validate_response(response, request, TAXONOMY)

    def test_unexpected_or_missing_question_answer_is_rejected(self) -> None:
        response = _valid_response(self.request)
        response["answers"].pop("event_sanctions")
        with self.assertRaisesRegex(SpikeError, "question set"):
            validate_response(response, self.request, TAXONOMY)
        response = _valid_response(self.request)
        response["answers"]["unexpected_question"] = {"type": "noul", "noul": 0.0}
        with self.assertRaisesRegex(SpikeError, "question set"):
            validate_response(response, self.request, TAXONOMY)

    def test_choice_confidence_range_and_type_are_checked(self) -> None:
        for invalid in (True, -0.01, 1.01, float("inf"), "0.7"):
            with self.subTest(invalid=invalid):
                response = _valid_response(self.request)
                response["answers"][TAXONOMY["topic_choice_id"]]["confidence"] = invalid
                with self.assertRaisesRegex(SpikeError, "unknown or invalid topic"):
                    validate_response(response, self.request, TAXONOMY)

    def test_malformed_noul_score_is_rejected(self) -> None:
        for invalid in (True, float("nan"), -0.1, 1.2, "0.4"):
            with self.subTest(invalid=invalid):
                response = _valid_response(self.request)
                response["answers"]["event_sanctions"]["noul"] = invalid
                with self.assertRaisesRegex(SpikeError, "invalid Noul"):
                    validate_response(response, self.request, TAXONOMY)

    def test_non_jev_resolved_model_version_is_rejected(self) -> None:
        response = _valid_response(self.request)
        response["model"] = "gpt-4o"
        with self.assertRaisesRegex(SpikeError, "resolved model version"):
            validate_response(response, self.request, TAXONOMY)

    def test_unhashable_choice_is_rejected_without_crashing(self) -> None:
        response = _valid_response(self.request)
        response["answers"][TAXONOMY["topic_choice_id"]]["choice"] = []
        with self.assertRaisesRegex(SpikeError, "unknown or invalid topic"):
            validate_response(response, self.request, TAXONOMY)

    def test_official_response_usage_fields_are_required(self) -> None:
        response = _valid_response(self.request)
        response.pop("usage")
        with self.assertRaisesRegex(SpikeError, "usage metadata"):
            validate_response(response, self.request, TAXONOMY)

        response = _valid_response(self.request)
        response["usage"].pop("output_tokens")
        with self.assertRaisesRegex(SpikeError, "usage metadata"):
            validate_response(response, self.request, TAXONOMY)

        response = _valid_response(self.request)
        response["usage"].pop("input_tokens")
        with self.assertRaisesRegex(SpikeError, "usage metadata"):
            validate_response(response, self.request, TAXONOMY)

        response = _valid_response(self.request)
        response["usage"].pop("cost_rub")
        with self.assertRaisesRegex(SpikeError, "usage metadata"):
            validate_response(response, self.request, TAXONOMY)

    def test_usage_token_counts_must_be_non_negative_integers(self) -> None:
        for invalid in (-1, 1.5, True, "3"):
            with self.subTest(invalid=invalid):
                response = _valid_response(self.request)
                response["usage"]["input_tokens"] = invalid
                with self.assertRaisesRegex(SpikeError, "usage metadata"):
                    validate_response(response, self.request, TAXONOMY)

    def test_usage_cost_must_be_finite_non_negative_number(self) -> None:
        for invalid in (-0.01, True, float("nan"), float("inf"), "0.01"):
            with self.subTest(invalid=invalid):
                response = _valid_response(self.request)
                response["usage"]["cost_rub"] = invalid
                with self.assertRaisesRegex(SpikeError, "usage metadata"):
                    validate_response(response, self.request, TAXONOMY)

    def test_article_fields_and_size_are_validated_before_request(self) -> None:
        for invalid_case in (
            {"title": [], "text": "валидный текст"},
            {"title": "заголовок", "text": None},
        ):
            with (
                self.subTest(invalid_case=invalid_case),
                self.assertRaisesRegex(SpikeError, "must be strings"),
            ):
                make_request(invalid_case, TAXONOMY)
        with self.assertRaisesRegex(SpikeError, "size limit"):
            make_request({"title": "", "text": "x" * 10_001}, TAXONOMY)
        max_size = make_request({"title": "", "text": "x" * 10_000}, TAXONOMY)
        self.assertEqual(len(max_size["state"]["text"]), 10_000)
        preserved = {
            "title": "  заголовок  ",
            "text": "\nТекст с краевыми пробелами. \t",
        }
        request = make_request(preserved, TAXONOMY)
        self.assertEqual(request["state"], preserved)

    def test_case_metadata_and_unknown_fields_are_not_sent_to_provider(self) -> None:
        request = make_request(
            {
                "id": "synthetic-id",
                "title": "Заголовок",
                "text": "Вымышленный материал",
                "expected_events": ["secret-gold-label"],
                "unknown_field": "local-canary-metadata",
            },
            TAXONOMY,
        )
        self.assertEqual(set(request["state"]), {"title", "text"})
        encoded = json.dumps(request, ensure_ascii=False)
        self.assertNotIn("secret-gold-label", encoded)
        self.assertNotIn("local-canary-metadata", encoded)

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

    def test_threshold_boundaries_are_inclusive_as_documented_in_taxonomy(self) -> None:
        case = self.case
        at_negative = _valid_response(
            self.request,
            topic="politics_government",
            event_scores={"sanctions": 0.2},
        )
        result = interpret_response(case, at_negative, self.request, TAXONOMY).result
        self.assertNotIn("sanctions", result["predicted_events"])
        self.assertEqual(result["classification_status"], "classified")

        at_positive = _valid_response(
            self.request,
            topic="politics_government",
            event_scores={"sanctions": 0.8},
        )
        result = interpret_response(case, at_positive, self.request, TAXONOMY).result
        self.assertIn("sanctions", result["predicted_events"])
        self.assertEqual(result["classification_status"], "classified")

        low_choice_confidence = _valid_response(
            self.request,
            topic="politics_government",
            topic_confidence=(0.53 - 1 / 11) / (1 - 1 / 11),
            topic_probabilities={
                row["code"]: (0.53 if row["code"] == "politics_government" else 0.047)
                for row in TAXONOMY["topics"]
            },
        )
        result = interpret_response(
            case, low_choice_confidence, self.request, TAXONOMY
        ).result
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
    def test_offline_test_module_blocks_stdlib_network_entrypoints(self) -> None:
        with self.assertRaisesRegex(AssertionError, "attempted a network"):
            socket.create_connection(("typesafe.ai", 443), timeout=0.01)

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

    def test_live_mode_uses_official_key_variable_and_fails_before_network(
        self,
    ) -> None:
        from argparse import Namespace

        from run_spike import run_live

        args = Namespace(max_calls=1, model=DEFAULT_MODEL, output=None)
        with (
            patch.dict(
                os.environ,
                {
                    "POLZA_AI_API_KEY": "",
                    "TYPESAFE_API_KEY": "legacy-test-fixture",
                },
            ),
            self.assertRaisesRegex(SpikeError, "POLZA_AI_API_KEY"),
        ):
            run_live(args, TAXONOMY, CORPUS, CASES)

    def test_partial_live_run_saves_observation_without_quality_metrics(self) -> None:
        from argparse import Namespace

        import run_spike
        from jev_spike import SPIKE_DIR

        class OfflineJevClient:
            def __init__(self, *_: Any, **__: Any) -> None:
                pass

            def classify(self, request: dict[str, Any]) -> dict[str, Any]:
                return _valid_response(request)

        with tempfile.TemporaryDirectory(dir=SPIKE_DIR) as temporary:
            output_path = Path(temporary) / "partial-live.json"
            args = Namespace(
                max_calls=1,
                model=DEFAULT_MODEL,
                output=str(output_path),
            )
            with (
                patch.dict(os.environ, {"POLZA_AI_API_KEY": "unit-test-fixture"}),
                patch.object(run_spike, "JevClient", OfflineJevClient),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                report = run_spike.run_live(args, TAXONOMY, CORPUS, CASES)

            self.assertEqual(report["successful_calls"], 1)
            self.assertEqual(
                report["quality_metrics_status"], "NOT_MEASURED_INCOMPLETE_RUN"
            )
            self.assertIsNone(report["metrics"])
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["endpoint_host"], "polza.ai")
            self.assertEqual(saved["requested_model_id"], "typesafe/jev")
            self.assertIsNone(saved["metrics"])
            serialized = output_path.read_text(encoding="utf-8")
            self.assertNotIn("unit-test-fixture", serialized)
            self.assertNotIn(CASES[0]["text"], serialized)

    def test_offline_cli_runs_with_network_guard_active(self) -> None:
        from run_spike import main

        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["run_spike.py"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(), 0)
        self.assertIn('"classifier_calls": 0', output.getvalue())

    def test_live_cli_defaults_to_one_call_without_network(self) -> None:
        from run_spike import main

        captured: list[int] = []

        def fake_run_live(args: Any, *_: Any) -> dict[str, Any]:
            captured.append(args.max_calls)
            return {"failures": []}

        with (
            patch.object(sys, "argv", ["run_spike.py", "--live"]),
            patch("run_spike.run_live", side_effect=fake_run_live),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(captured, [1])

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

    def test_https_transport_installs_redirect_refusal(self) -> None:
        from jev_spike import _NoRedirect

        class RedirectingOpener:
            def __init__(self, handlers: tuple[Any, ...]) -> None:
                self.handlers = handlers
                self.calls = 0

            def open(self, *_: Any, **__: Any) -> None:
                self.calls += 1
                handler = next(
                    item for item in self.handlers if isinstance(item, _NoRedirect)
                )
                handler.redirect_request(
                    None, None, 302, "Found", {}, "https://attacker.example/collect"
                )

        opener: RedirectingOpener

        def build_opener(*handlers: Any) -> RedirectingOpener:
            nonlocal opener
            opener = RedirectingOpener(handlers)
            return opener

        with (
            patch("urllib.request.build_opener", side_effect=build_opener),
            self.assertRaisesRegex(LiveRequestError, "redirect_refused"),
        ):
            https_transport(API_ENDPOINT, b"synthetic only", {}, 30)
        self.assertEqual(opener.calls, 1)

    def test_http_error_body_is_suppressed(self) -> None:
        trace_id = "550e8400-e29b-41d4-a716-446655440000"
        provider_canary = "ARTICLE_SECRET"
        trace_canary = "123e4567-e89b-12d3-a456-426614174000"
        body = json.dumps(
            {
                "error": {
                    "code": provider_canary,
                    "message": "provider echoed canary-secret and article text",
                    "trace_id": trace_canary,
                },
                "trace_id": trace_id,
            }
        ).encode()

        class FailingOpener:
            def open(self, *_: Any, **__: Any) -> bytes:
                raise HTTPError(
                    API_ENDPOINT,
                    400,
                    "Unavailable",
                    hdrs=None,
                    fp=io.BytesIO(body),
                )

        with (
            patch("urllib.request.build_opener", return_value=FailingOpener()),
            self.assertRaises(LiveRequestError) as captured,
        ):
            https_transport(API_ENDPOINT, b"safe synthetic request", {}, 30)
        self.assertEqual(str(captured.exception), "http_status_400")
        self.assertNotIn("canary-secret", str(captured.exception))

        from run_spike import _safe_failure

        saved = json.dumps(_safe_failure("synthetic-case", captured.exception))
        self.assertNotIn(provider_canary, saved)
        self.assertNotIn(trace_canary, saved)
        self.assertNotIn(trace_id, saved)
        self.assertNotIn("canary-secret", saved)
        self.assertNotIn("article text", saved)

    def test_http_error_failure_record_contains_only_case_and_status(self) -> None:
        from run_spike import _safe_failure

        error = LiveRequestError("http_status_451")
        self.assertEqual(
            _safe_failure("synthetic-case", error),
            {"case_id": "synthetic-case", "error": "http_status_451"},
        )

    def test_expected_http_status_errors_are_sanitized_without_retry(self) -> None:
        for status in (400, 401, 403, 429, 451, 500, 502, 503, 529):

            class FailingOpener:
                def __init__(self, status_code: int) -> None:
                    self.status_code = status_code
                    self.calls = 0

                def open(self, *_: Any, **__: Any) -> bytes:
                    self.calls += 1
                    raise HTTPError(
                        API_ENDPOINT,
                        self.status_code,
                        "provider detail containing synthetic canary",
                        hdrs=None,
                        fp=io.BytesIO(b"must-not-be-saved"),
                    )

            opener = FailingOpener(status)
            with (
                self.subTest(status=status),
                patch("urllib.request.build_opener", return_value=opener) as build,
            ):
                with self.assertRaises(LiveRequestError) as captured:
                    https_transport(API_ENDPOINT, b"synthetic only", {}, 30)
                self.assertEqual(str(captured.exception), f"http_status_{status}")
                self.assertEqual(build.call_count, 1)
                self.assertEqual(opener.calls, 1)

    def test_direct_transport_disables_environment_proxy_discovery(self) -> None:
        class Response:
            status = 200

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self, _: int) -> bytes:
                return b"{}"

        class Opener:
            def open(self, *_: Any, **__: Any) -> Response:
                return Response()

        with patch("urllib.request.build_opener", return_value=Opener()) as build:
            self.assertEqual(https_transport(API_ENDPOINT, b"{}", {}, 30), b"{}")
        handlers = build.call_args.args
        proxy_handler = next(
            handler
            for handler in handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        )
        self.assertEqual(proxy_handler.proxies, {})

    def test_transport_bounds_oversized_response_before_json_decode(self) -> None:
        class Response:
            status = 200

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self, limit: int) -> bytes:
                return b"x" * limit

        class Opener:
            def open(self, *_: Any, **__: Any) -> Response:
                return Response()

        with (
            patch("urllib.request.build_opener", return_value=Opener()),
            self.assertRaisesRegex(LiveRequestError, "response_too_large"),
        ):
            https_transport(API_ENDPOINT, b"{}", {}, 30)

    def test_transport_errors_for_timeout_and_connection_reset_are_sanitized(
        self,
    ) -> None:
        class TimeoutOpener:
            calls = 0

            def open(self, *_: Any, **__: Any) -> bytes:
                self.calls += 1
                raise TimeoutError("contains key and prompt")

        class ResetOpener:
            calls = 0

            def open(self, *_: Any, **__: Any) -> bytes:
                self.calls += 1
                raise OSError("connection reset contains key and prompt")

        class WrappedTimeoutOpener:
            calls = 0

            def open(self, *_: Any, **__: Any) -> bytes:
                self.calls += 1
                raise URLError(TimeoutError("wrapped timeout details"))

        for opener, expected in (
            (TimeoutOpener(), "timeout"),
            (WrappedTimeoutOpener(), "timeout"),
            (ResetOpener(), "connection_error"),
        ):
            with (
                self.subTest(expected=expected),
                patch("urllib.request.build_opener", return_value=opener),
            ):
                with self.assertRaises(LiveRequestError) as captured:
                    https_transport(API_ENDPOINT, b"{}", {}, 30)
                self.assertEqual(str(captured.exception), expected)
                self.assertEqual(opener.calls, 1)

    def test_unapproved_host_is_rejected_before_transport_creation(self) -> None:
        with (
            patch("urllib.request.build_opener") as build,
            self.assertRaisesRegex(LiveRequestError, "unapproved_endpoint"),
        ):
            https_transport("https://evil.example/v1/systemone", b"{}", {}, 30)
        build.assert_not_called()

    def test_client_rejects_oversized_or_non_byte_transport_body(self) -> None:
        request = make_request(CASES[0], TAXONOMY)
        for body, expected in (
            (b"x" * 1_000_001, "response_too_large"),
            (None, "invalid_response_body"),
        ):
            with self.subTest(expected=expected):
                client = JevClient(
                    "key",
                    allowed_request_hashes={request_hash(request)},
                    transport=lambda *_args, response=body: response,
                )
                with self.assertRaisesRegex(LiveRequestError, expected):
                    client.classify(request)

    def test_client_rejects_malformed_and_non_object_json_responses(self) -> None:
        request = make_request(CASES[0], TAXONOMY)
        for body in (b"not-json", b"\xff", b"[]"):
            with self.subTest(body_length=len(body)):
                client = JevClient(
                    "key",
                    allowed_request_hashes={request_hash(request)},
                    transport=lambda *_args, response=body: response,
                )
                with self.assertRaisesRegex(LiveRequestError, "invalid_json_response"):
                    client.classify(request)

    def test_timeout_is_fixed_and_bounded(self) -> None:
        self.assertEqual(make_request(CASES[0], TAXONOMY)["model"], "typesafe/jev")
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
    def test_empty_evaluation_reports_metrics_as_unavailable_not_zero(self) -> None:
        metrics = evaluate([], [], TAXONOMY)
        self.assertIsNone(metrics["topic_accuracy"])
        self.assertIsNone(metrics["event_micro_precision"])
        self.assertIsNone(metrics["event_micro_recall"])
        self.assertIsNone(metrics["event_micro_f1"])
        self.assertIsNone(metrics["unlisted_event_exact"])
        self.assertIsNone(metrics["latency"]["p95_nearest_rank_ms"])
        self.assertIsNone(metrics["token_usage"]["total_tokens"])
        self.assertIsNone(metrics["review_rate"])

    def test_evaluator_rejects_duplicate_and_unknown_result_ids(self) -> None:
        case = CASES[0]
        result = {
            "case_id": case["id"],
            "topic": case["expected_topic"],
            "event_scores": {event["code"]: 0.0 for event in TAXONOMY["events"]},
            "unlisted_event_score": 0.0,
            "uncertainty_score": 0.0,
            "classification_status": "classified",
        }
        with self.assertRaisesRegex(SpikeError, "duplicate case ids"):
            evaluate([case], [result, dict(result)], TAXONOMY)
        bad_result = dict(result, case_id="not-in-corpus")
        with self.assertRaisesRegex(SpikeError, "unknown case ids"):
            evaluate([case], [bad_result], TAXONOMY)

    def test_missing_measurement_fields_stay_unavailable(self) -> None:
        case = CASES[0]
        result = {
            "case_id": case["id"],
            "topic": case["expected_topic"],
            "topic_confidence": 0.7,
            "event_scores": {event["code"]: 0.0 for event in TAXONOMY["events"]},
            "unlisted_event_score": 0.0,
            "uncertainty_score": 0.0,
            "classification_status": "classified",
        }
        metrics = evaluate([case], [result], TAXONOMY)
        self.assertEqual(metrics["latency"]["n"], 0)
        self.assertIsNone(metrics["latency"]["mean_ms"])
        self.assertIsNone(metrics["token_usage"]["input_tokens"])
        self.assertIsNone(metrics["token_usage"]["total_tokens"])

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
        self.assertEqual(len(metrics["threshold_sweep"]), 7)
        self.assertEqual(len(metrics["event_review_band_sweep"]), 12)
        self.assertEqual(len(metrics["choice_review_threshold_sweep"]), 6)
        self.assertEqual(len(metrics["unlisted_threshold_sweep"]), 7)
        self.assertEqual(len(metrics["uncertainty_threshold_sweep"]), 9)
        self.assertTrue(
            all(
                {"micro_precision", "micro_recall", "macro_f1"}.issubset(row)
                for row in metrics["threshold_sweep"]
            )
        )
        self.assertEqual(metrics["event_exact_match_rate"], 1.0)
        self.assertEqual(metrics["review_count"], 7)
        self.assertEqual(metrics["other_count"], 1)
        self.assertEqual(metrics["event_false_positives"], [])
        self.assertEqual(metrics["event_false_negatives"], [])
        self.assertEqual(
            metrics["topic_confusion_matrix"]["industry_trade_supply"][
                "industry_trade_supply"
            ],
            10,
        )
        self.assertEqual(metrics["latency"]["n"], 49)
        self.assertEqual(metrics["token_usage"]["total_tokens"], 98)
        self.assertAlmostEqual(metrics["token_usage"]["cost_rub"], 0.098)
        self.assertEqual(metrics["expected_unlisted_event_count"], 1)
        self.assertTrue(metrics["unlisted_event_exact"])
        self.assertEqual(metrics["expected_uncertainty_signal_count"], 6)
        self.assertEqual(metrics["uncertainty_signal_precision"], 1.0)
        self.assertEqual(metrics["uncertainty_signal_recall"], 1.0)

    def test_threshold_sweep_math_reports_precision_recall_and_single_errors(
        self,
    ) -> None:
        cases = [
            next(case for case in CASES if case["id"] == "e12-sanctions-assets"),
            next(case for case in CASES if case["id"] == "e36-noevent-rates"),
        ]
        results: list[dict[str, Any]] = []
        for case, scores in zip(
            cases,
            (
                {"sanctions": 0.8},
                {"trade_restriction": 0.8},
            ),
            strict=True,
        ):
            results.append(
                {
                    "case_id": case["id"],
                    "topic": case["expected_topic"],
                    "topic_confidence": 1.0,
                    "event_scores": {
                        event["code"]: scores.get(event["code"], 0.0)
                        for event in TAXONOMY["events"]
                    },
                    "unlisted_event_score": 0.0,
                    "uncertainty_score": 0.0,
                    "classification_status": "classified",
                    "elapsed_ms": 120 if case == cases[0] else 240,
                    "usage": {"input_tokens": 20, "output_tokens": 5},
                }
            )
        metrics = evaluate(cases, results, TAXONOMY)
        row = next(
            item for item in metrics["threshold_sweep"] if item["threshold"] == 0.8
        )
        self.assertEqual((row["tp"], row["fp"], row["fn"]), (1, 1, 0))
        self.assertEqual(row["micro_precision"], 0.5)
        self.assertEqual(row["micro_recall"], 1.0)
        self.assertEqual(row["micro_f1"], 0.6667)
        self.assertEqual(row["review_cells"], 0)
        high_cutoff = next(
            item for item in metrics["threshold_sweep"] if item["threshold"] == 0.9
        )
        self.assertEqual(high_cutoff["review_cells"], 2)
        self.assertEqual(high_cutoff["review_cell_rate"], 0.0667)
        self.assertEqual(metrics["event_exact_match_count"], 1)
        self.assertEqual(
            metrics["event_false_positives"],
            [{"case_id": cases[1]["id"], "code": "trade_restriction"}],
        )
        self.assertEqual(metrics["latency"]["median_ms"], 180.0)
        self.assertEqual(metrics["latency"]["p95_nearest_rank_ms"], 240)


if __name__ == "__main__":
    unittest.main()
