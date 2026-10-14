"""Standalone, opt-in TypeSafe Jev harness for the T08 taxonomy spike.

This module deliberately does not import or register the production runtime.
It accepts only the repository's hand-authored synthetic corpus for live calls.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import ssl
import statistics
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SPIKE_DIR = Path(__file__).resolve().parent
TAXONOMY_PATH = SPIKE_DIR / "taxonomy.json"
CORPUS_PATH = SPIKE_DIR / "corpus.json"
API_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
SUPPORTED_MODEL_ALIASES = frozenset({DEFAULT_MODEL})
RESOLVED_JEV_MODEL = re.compile(r"^jev-[0-9]+\.[0-9]+\.[0-9]+$")
TRUSTED_TAXONOMY_SHA256 = (
    "855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d"
)
TRUSTED_CORPUS_SHA256 = (
    "592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d7"
)
MAX_ARTICLE_CHARS = 10_000
REQUEST_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1_000_000
# The public confidence examples are rounded to two decimals. A 0.02 absolute
# tolerance accepts that displayed precision while rejecting inconsistent data.
CHOICE_CONFIDENCE_ROUNDING_TOLERANCE = 0.02
MAX_TOTAL_QUESTIONS = (
    20  # Spike-local cost guard; TypeSafe documents no total-count limit.
)

JsonObject = dict[str, Any]
Transport = Callable[[str, bytes, dict[str, str], int], bytes]


class SpikeError(ValueError):
    """Safe, user-facing error with no provider body or article text."""


class NoContentError(SpikeError):
    pass


class LiveRequestError(SpikeError):
    pass


@dataclass(frozen=True)
class PreparedDecision:
    case_id: str
    result: JsonObject


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def load_pinned_json(path: Path, expected_sha256: str) -> JsonObject:
    """Load a source-controlled spike input only when its exact bytes are pinned."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SpikeError(f"Cannot read spike data file: {path.name}") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise SpikeError(f"Unapproved changes in spike data file: {path.name}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpikeError(f"Cannot parse spike data file: {path.name}") from exc
    if not isinstance(value, dict):
        raise SpikeError(f"Invalid spike data file: {path.name}")
    return value


def load_verified_inputs() -> tuple[JsonObject, JsonObject, list[JsonObject]]:
    taxonomy = load_pinned_json(TAXONOMY_PATH, TRUSTED_TAXONOMY_SHA256)
    corpus = load_pinned_json(CORPUS_PATH, TRUSTED_CORPUS_SHA256)
    validate_taxonomy(taxonomy)
    cases = validate_corpus(corpus, taxonomy)
    return taxonomy, corpus, cases


def taxonomy_hash(taxonomy: JsonObject) -> str:
    return hashlib.sha256(_canonical_json(taxonomy)).hexdigest()


def validate_taxonomy(taxonomy: JsonObject) -> None:
    if taxonomy.get("status") != "experimental-proposal":
        raise SpikeError("Taxonomy must remain marked experimental-proposal")
    if not isinstance(taxonomy.get("id"), str) or not taxonomy["id"].strip():
        raise SpikeError("Taxonomy id is required")
    if not isinstance(taxonomy.get("version"), str) or not taxonomy["version"].strip():
        raise SpikeError("Taxonomy version is required")
    for group_name in ("topics", "events"):
        rows = taxonomy.get(group_name)
        if not isinstance(rows, list) or not rows:
            raise SpikeError(f"Taxonomy {group_name} must be a non-empty list")
        codes: list[str] = []
        required = {"code", "label", "definition"}
        for row in rows:
            if not isinstance(row, dict) or not required.issubset(row):
                raise SpikeError(f"Invalid {group_name} entry")
            if any(
                not isinstance(row[key], str) or not row[key].strip()
                for key in required
            ):
                raise SpikeError(f"Invalid {group_name} entry")
            codes.append(row["code"])
        if len(codes) != len(set(codes)):
            raise SpikeError(f"Duplicate code in taxonomy {group_name}")
    topic_codes = {row["code"] for row in taxonomy["topics"]}
    event_codes = {row["code"] for row in taxonomy["events"]}
    if taxonomy.get("other_code") not in topic_codes:
        raise SpikeError("Taxonomy needs an explicit other/uncertain topic")
    if not 10 <= len(event_codes) <= 15:
        raise SpikeError("Taxonomy must contain 10–15 business-event categories")
    if taxonomy.get("unlisted_event_code") in event_codes:
        raise SpikeError("Unlisted-event probe must not be a public taxonomy label")
    if taxonomy.get("uncertainty_signal_code") in event_codes:
        raise SpikeError("Uncertainty signal must not be a business-event label")
    question_ids = [
        taxonomy.get("topic_choice_id"),
        taxonomy.get("unlisted_event_code"),
        taxonomy.get("uncertainty_signal_code"),
    ]
    if any(
        not isinstance(question_id, str) or not question_id
        for question_id in question_ids
    ):
        raise SpikeError("Jev question ids are required")
    if len(question_ids) != len(set(question_ids)):
        raise SpikeError("Jev question ids must be unique")
    thresholds = taxonomy.get("thresholds")
    if not isinstance(thresholds, dict):
        raise SpikeError("Threshold policy is missing")
    neg = thresholds.get("noul_negative_at_or_below")
    pos = thresholds.get("noul_positive_at_or_above")
    choice_review = thresholds.get("choice_review_below")
    for number in (neg, pos, choice_review):
        if (
            not isinstance(number, (int, float))
            or isinstance(number, bool)
            or not 0 <= number <= 1
        ):
            raise SpikeError("Invalid experimental threshold")
    if neg >= pos:
        raise SpikeError("Noul review interval must be non-empty")


def validate_corpus(corpus: JsonObject, taxonomy: JsonObject) -> list[JsonObject]:
    if corpus.get("status") != "hand-labeled-synthetic-evaluation":
        raise SpikeError("Live mode accepts only the hand-labeled synthetic corpus")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not 30 <= len(cases) <= 50:
        raise SpikeError("Evaluation corpus must contain 30–50 cases")
    allowed_topics = {row["code"] for row in taxonomy["topics"]}
    allowed_events = {row["code"] for row in taxonomy["events"]}
    seen_ids: set[str] = set()
    event_counts = {code: 0 for code in allowed_events}
    for case in cases:
        if not isinstance(case, dict):
            raise SpikeError("Invalid corpus case")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise SpikeError("Corpus case ids must be unique")
        seen_ids.add(case_id)
        if not isinstance(case.get("title"), str) or not isinstance(
            case.get("text"), str
        ):
            raise SpikeError(f"Invalid text fields in corpus case {case_id}")
        expected_topic = case.get("expected_topic")
        if expected_topic is not None and expected_topic not in allowed_topics:
            raise SpikeError(f"Unknown gold topic in corpus case {case_id}")
        expected_events = case.get("expected_events")
        if not isinstance(expected_events, list) or any(
            code not in allowed_events for code in expected_events
        ):
            raise SpikeError(f"Unknown gold event in corpus case {case_id}")
        if not isinstance(case.get("expected_unlisted_event"), bool):
            raise SpikeError(
                f"Invalid unlisted-event gold label in corpus case {case_id}"
            )
        if not isinstance(case.get("expected_uncertainty_signal"), bool):
            raise SpikeError(f"Invalid uncertainty gold label in corpus case {case_id}")
        if len(expected_events) != len(set(expected_events)):
            raise SpikeError(f"Duplicate gold event in corpus case {case_id}")
        if case.get("expected_status") not in {
            "classified",
            "uncertain",
            "other",
            "no_content",
        }:
            raise SpikeError(f"Invalid gold status in corpus case {case_id}")
        for code in expected_events:
            event_counts[code] += 1
    missing_examples = sorted(code for code, count in event_counts.items() if count < 2)
    if missing_examples:
        raise SpikeError("Each event needs at least two positive examples")
    return cases


def make_request(
    case: JsonObject,
    taxonomy: JsonObject,
    *,
    model: str = DEFAULT_MODEL,
) -> JsonObject:
    if not isinstance(case, dict):
        raise SpikeError("invalid synthetic article")
    title_value = case.get("title")
    text_value = case.get("text")
    if not isinstance(title_value, str) or not isinstance(text_value, str):
        raise SpikeError("synthetic article title and text must be strings")
    title = title_value
    text = text_value
    if not title.strip() and not text.strip():
        raise NoContentError("empty_text")
    if len(title) + len(text) > MAX_ARTICLE_CHARS:
        raise SpikeError("synthetic article exceeds the spike size limit")
    if not isinstance(model, str) or model not in SUPPORTED_MODEL_ALIASES:
        raise SpikeError("invalid model alias")

    topic_rows = list(taxonomy["topics"])
    topic_criteria = {row["code"]: row["definition"] for row in topic_rows}
    event_questions: dict[str, JsonObject] = {}
    for event in taxonomy["events"]:
        event_questions[f"event_{event['code']}"] = {
            "type": "noul",
            "instructions": f"Сообщает ли статья прямо о следующем деловом событии: {event['label']}? Отвечай «да» только для факта, который уже произошёл или официально объявлен.",
            "criteria": {
                "true": event["include"],
                "false": event["exclude"],
            },
        }
    questions: JsonObject = {
        taxonomy["topic_choice_id"]: {
            "type": "choice",
            "instructions": "Какова одна главная тема этой новости? Выбери other_uncertain, если ни одна тема не подходит или данных недостаточно.",
            "criteria": topic_criteria,
        },
        **event_questions,
        taxonomy["unlisted_event_code"]: {
            "type": "noul",
            "instructions": taxonomy["unlisted_event_question"],
            "criteria": taxonomy["unlisted_event_criteria"],
        },
        taxonomy["uncertainty_signal_code"]: {
            "type": "noul",
            "instructions": taxonomy["uncertainty_question"],
            "criteria": taxonomy["uncertainty_criteria"],
        },
    }
    if len(topic_criteria) > 255:
        raise SpikeError("Choice exceeds TypeSafe's documented 255-option limit")
    if len(questions) > MAX_TOTAL_QUESTIONS:
        raise SpikeError(
            "Jev System One request exceeds the spike-local question budget"
        )
    return {
        "state": {"title": title, "text": text},
        "model": model,
        "questions": questions,
    }


def request_hash(request: JsonObject) -> str:
    return hashlib.sha256(_canonical_json(request)).hexdigest()


def approved_request_hashes(
    cases: list[JsonObject], taxonomy: JsonObject, *, model: str
) -> set[str]:
    """Derive the exact one-shot live request set from validated spike data."""
    if not isinstance(model, str) or model not in SUPPORTED_MODEL_ALIASES:
        raise SpikeError("invalid model alias")
    news_cases = [
        case
        for case in cases
        if case.get("expected_status") != "no_content"
        and (case.get("title", "").strip() or case.get("text", "").strip())
    ]
    if not news_cases:
        raise SpikeError("live request set is empty")
    requests = [make_request(case, taxonomy, model=model) for case in news_cases]
    return {request_hash(request) for request in requests}


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_response(
    response: Any, request: JsonObject, taxonomy: JsonObject
) -> JsonObject:
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise SpikeError("Jev returned an invalid response shape")
    model = response.get("model")
    if not isinstance(model, str) or not RESOLVED_JEV_MODEL.fullmatch(model):
        raise SpikeError("Jev response has an invalid resolved model version")
    answers = response["answers"]
    requested = request["questions"]
    if set(answers) != set(requested):
        raise SpikeError("Jev response question set does not match the request")

    topic_id = taxonomy["topic_choice_id"]
    topic_codes = set(requested[topic_id]["criteria"])
    topic = answers[topic_id]
    if not isinstance(topic, dict) or topic.get("type") != "choice":
        raise SpikeError("Jev returned an invalid Choice answer")
    choice = topic.get("choice")
    confidence = topic.get("confidence")
    probabilities = topic.get("probabilities")
    if (
        not isinstance(choice, str)
        or choice not in topic_codes
        or not _number(confidence)
        or not 0 <= confidence <= 1
    ):
        raise SpikeError("Jev returned an unknown or invalid topic Choice")
    if not isinstance(probabilities, dict) or set(probabilities) != topic_codes:
        raise SpikeError("Jev Choice probabilities do not match the allowed taxonomy")
    if any(
        not _number(value) or not 0 <= value <= 1 for value in probabilities.values()
    ):
        raise SpikeError("Jev returned an invalid Choice probability")
    if not math.isclose(sum(probabilities.values()), 1.0, rel_tol=0, abs_tol=1e-5):
        raise SpikeError("Jev Choice probabilities do not sum to one")
    if probabilities[choice] + 1e-8 < max(probabilities.values()):
        raise SpikeError("Jev Choice label is not a maximum-probability option")
    option_count = len(probabilities)
    if option_count < 2:
        raise SpikeError("Jev Choice needs at least two probability options")
    expected_confidence = (max(probabilities.values()) - 1 / option_count) / (
        1 - 1 / option_count
    )
    if not math.isclose(
        confidence,
        expected_confidence,
        rel_tol=0,
        abs_tol=CHOICE_CONFIDENCE_ROUNDING_TOLERANCE,
    ):
        raise SpikeError("Jev Choice confidence does not match its probabilities")

    for question_id in requested:
        if question_id == topic_id:
            continue
        answer = answers[question_id]
        value = answer.get("noul") if isinstance(answer, dict) else None
        if (
            not isinstance(answer, dict)
            or answer.get("type") != "noul"
            or not _number(value)
            or not 0 <= value <= 1
        ):
            raise SpikeError("Jev returned an invalid Noul answer")

    usage = response.get("usage")
    if not isinstance(usage, dict) or not {"input_tokens", "output_tokens"}.issubset(
        usage
    ):
        raise SpikeError("Jev returned invalid usage metadata")
    for key in ("input_tokens", "output_tokens"):
        if (
            not isinstance(usage[key], int)
            or isinstance(usage[key], bool)
            or usage[key] < 0
        ):
            raise SpikeError("Jev returned invalid usage metadata")
    return response


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Any,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        raise LiveRequestError("redirect_refused")


def https_transport(
    url: str, payload: bytes, headers: dict[str, str], timeout: int
) -> bytes:
    """Post once over HTTPS; refuse redirects and cap both time and body size."""
    if url != API_ENDPOINT:
        raise LiveRequestError("unapproved_endpoint")
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    # Do not inherit HTTP(S)_PROXY from the shell: the experiment must use the
    # configured direct route and must never route around provider restrictions.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status < 200 or response.status >= 300:
                raise LiveRequestError(f"http_status_{response.status}")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise LiveRequestError("response_too_large")
            return body
    except LiveRequestError:
        raise
    except urllib.error.HTTPError as exc:
        # Suppress provider text: it may echo prompt fragments or request metadata.
        raise LiveRequestError(f"http_status_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Do not include the raw exception: it can contain URLs, headers, or payload fragments.
        wrapped_timeout = isinstance(exc, urllib.error.URLError) and isinstance(
            exc.reason, TimeoutError
        )
        kind = (
            "timeout"
            if isinstance(exc, TimeoutError) or wrapped_timeout
            else "connection_error"
        )
        raise LiveRequestError(kind) from None


class JevClient:
    def __init__(
        self,
        api_key: str,
        *,
        allowed_request_hashes: set[str],
        transport: Transport = https_transport,
    ) -> None:
        if not api_key or not api_key.strip():
            raise SpikeError("TYPESAFE_API_KEY is required for live mode")
        if not allowed_request_hashes or any(
            not re.fullmatch(r"[0-9a-f]{64}", value) for value in allowed_request_hashes
        ):
            raise SpikeError("live request allowlist is invalid")
        self._api_key = api_key
        self._transport = transport
        self._allowed_request_hashes = frozenset(allowed_request_hashes)
        self._used_request_hashes: set[str] = set()

    def classify(self, request: JsonObject) -> JsonObject:
        payload = _canonical_json(request)
        request_hash = hashlib.sha256(payload).hexdigest()
        if request_hash not in self._allowed_request_hashes:
            raise SpikeError("request_not_authorized")
        if request_hash in self._used_request_hashes:
            raise SpikeError("request_already_used")
        self._used_request_hashes.add(request_hash)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "alfa-t08-classification-spike/0.1",
        }
        started = time.monotonic()
        try:
            body = self._transport(
                API_ENDPOINT, payload, headers, REQUEST_TIMEOUT_SECONDS
            )
        except LiveRequestError:
            raise
        except Exception:  # noqa: BLE001 - custom transports are untrusted; suppress details.
            # Keep test/custom transport failures sanitized too.
            raise LiveRequestError("transport_error") from None
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if not isinstance(body, bytes):
            raise LiveRequestError("invalid_response_body")
        if len(body) > MAX_RESPONSE_BYTES:
            raise LiveRequestError("response_too_large")
        try:
            response = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise LiveRequestError("invalid_json_response") from None
        if not isinstance(response, dict):
            raise LiveRequestError("invalid_json_response")
        response["_local_elapsed_ms"] = elapsed_ms
        return response


def interpret_response(
    case: JsonObject,
    raw_response: JsonObject,
    request: JsonObject,
    taxonomy: JsonObject,
) -> PreparedDecision:
    response = validate_response(raw_response, request, taxonomy)
    answers = response["answers"]
    topic_id = taxonomy["topic_choice_id"]
    topic_answer = answers[topic_id]
    topic_code = topic_answer["choice"]
    topic_confidence = float(topic_answer["confidence"])
    thresholds = taxonomy["thresholds"]
    positive = float(thresholds["noul_positive_at_or_above"])
    negative = float(thresholds["noul_negative_at_or_below"])
    review_below = float(thresholds["choice_review_below"])

    event_scores = {
        event["code"]: float(answers[f"event_{event['code']}"]["noul"])
        for event in taxonomy["events"]
    }
    positive_events = [
        code for code, score in event_scores.items() if score >= positive
    ]
    borderline_events = [
        code for code, score in event_scores.items() if negative < score < positive
    ]
    unlisted_score = float(answers[taxonomy["unlisted_event_code"]]["noul"])
    uncertainty_score = float(answers[taxonomy["uncertainty_signal_code"]]["noul"])
    topic_review = topic_confidence < review_below
    if topic_code == taxonomy["other_code"]:
        status = (
            "uncertain" if topic_review or uncertainty_score > negative else "other"
        )
    elif (
        topic_review
        or borderline_events
        or unlisted_score > negative
        or uncertainty_score > negative
    ):
        status = "uncertain"
    else:
        status = "classified"

    safe_result: JsonObject = {
        "case_id": case["id"],
        "taxonomy_id": taxonomy["id"],
        "taxonomy_version": taxonomy["version"],
        "taxonomy_hash": taxonomy_hash(taxonomy),
        "model_version": response["model"],
        "topic": topic_code,
        "topic_confidence": topic_confidence,
        "topic_probabilities": {
            key: float(value) for key, value in topic_answer["probabilities"].items()
        },
        "event_scores": event_scores,
        "unlisted_event_score": unlisted_score,
        "uncertainty_score": uncertainty_score,
        "predicted_events": positive_events,
        "classification_status": status,
        "usage": {
            key: int(response["usage"][key])
            for key in ("input_tokens", "output_tokens")
            if key in response.get("usage", {})
        },
        "elapsed_ms": int(response.get("_local_elapsed_ms", 0)),
    }
    return PreparedDecision(case["id"], safe_result)


def no_content_result(case: JsonObject, taxonomy: JsonObject) -> JsonObject:
    if case.get("title", "").strip() or case.get("text", "").strip():
        raise SpikeError("no_content_result can only be used for empty text")
    return {
        "case_id": case["id"],
        "taxonomy_id": taxonomy["id"],
        "taxonomy_version": taxonomy["version"],
        "taxonomy_hash": taxonomy_hash(taxonomy),
        "model_version": None,
        "topic": None,
        "topic_confidence": None,
        "topic_probabilities": {},
        "event_scores": {},
        "unlisted_event_score": None,
        "uncertainty_score": None,
        "predicted_events": [],
        "classification_status": "no_content",
        "usage": {},
        "elapsed_ms": 0,
    }


def _f1(tp: int, fp: int, fn: int) -> float:
    denominator = 2 * tp + fp + fn
    return 0.0 if denominator == 0 else (2 * tp) / denominator


def evaluate(
    cases: list[JsonObject], results: list[JsonObject], taxonomy: JsonObject
) -> JsonObject:
    result_ids = [result.get("case_id") for result in results]
    if any(not isinstance(case_id, str) or not case_id for case_id in result_ids):
        raise SpikeError("evaluation results need non-empty case ids")
    if len(result_ids) != len(set(result_ids)):
        raise SpikeError("evaluation results contain duplicate case ids")
    case_ids = {case.get("id") for case in cases}
    if any(case_id not in case_ids for case_id in result_ids):
        raise SpikeError("evaluation results contain unknown case ids")
    by_id = {result["case_id"]: result for result in results}
    evaluated = [
        case
        for case in cases
        if case["expected_status"] != "no_content" and case["id"] in by_id
    ]
    non_empty_case_total = sum(
        case["expected_status"] != "no_content" for case in cases
    )
    topic_correct = sum(
        by_id[case["id"]]["topic"] == case["expected_topic"] for case in evaluated
    )
    event_codes = [event["code"] for event in taxonomy["events"]]
    threshold_rows: list[JsonObject] = []
    fixed_negative_threshold = float(
        taxonomy["thresholds"]["noul_negative_at_or_below"]
    )
    event_threshold_grid: list[JsonObject] = []
    for threshold in [round(step / 10, 1) for step in range(3, 10)]:
        tp = fp = fn = 0
        class_f1_at_threshold: list[float] = []
        review_cells = 0
        for case in evaluated:
            scores = by_id[case["id"]]["event_scores"]
            predicted = {code for code in event_codes if scores[code] >= threshold}
            expected = set(case["expected_events"])
            tp += len(predicted & expected)
            fp += len(predicted - expected)
            fn += len(expected - predicted)
            review_cells += sum(
                fixed_negative_threshold < scores[code] < threshold
                for code in event_codes
            )
        for code in event_codes:
            class_tp = class_fp = class_fn = 0
            for case in evaluated:
                predicted = by_id[case["id"]]["event_scores"][code] >= threshold
                expected = code in case["expected_events"]
                class_tp += int(predicted and expected)
                class_fp += int(predicted and not expected)
                class_fn += int(not predicted and expected)
            if class_tp + class_fn > 0:
                class_f1_at_threshold.append(_f1(class_tp, class_fp, class_fn))
        threshold_rows.append(
            {
                "threshold": threshold,
                "micro_f1": round(_f1(tp, fp, fn), 4) if tp + fp + fn else None,
                "micro_precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "micro_recall": round(tp / (tp + fn), 4) if tp + fn else None,
                "macro_f1": round(
                    sum(class_f1_at_threshold) / len(class_f1_at_threshold), 4
                )
                if class_f1_at_threshold
                else None,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "positive_support": tp + fn,
                "fixed_negative_threshold": fixed_negative_threshold,
                "review_cells": review_cells,
                "review_cell_rate": round(
                    review_cells / (len(evaluated) * len(event_codes)), 4
                )
                if evaluated
                else None,
            }
        )

    for negative_cutoff in (0.1, 0.2, 0.3):
        for positive_cutoff in (0.6, 0.7, 0.8, 0.9):
            if negative_cutoff >= positive_cutoff:
                continue
            review_cells = sum(
                negative_cutoff
                < by_id[case["id"]]["event_scores"][code]
                < positive_cutoff
                for case in evaluated
                for code in event_codes
            )
            total_cells = len(evaluated) * len(event_codes)
            event_threshold_grid.append(
                {
                    "negative_cutoff": negative_cutoff,
                    "positive_cutoff": positive_cutoff,
                    "fixed_as_review_band": True,
                    "review_cells": review_cells,
                    "review_cell_rate": round(review_cells / total_cells, 4)
                    if total_cells
                    else None,
                }
            )

    choice_threshold_rows: list[JsonObject] = []
    for choice_cutoff in [round(step / 10, 1) for step in range(3, 9)]:
        auto_cases = [
            case
            for case in evaluated
            if by_id[case["id"]]["topic_confidence"] >= choice_cutoff
        ]
        auto_correct = sum(
            by_id[case["id"]]["topic"] == case["expected_topic"] for case in auto_cases
        )
        review_count = len(evaluated) - len(auto_cases)
        choice_threshold_rows.append(
            {
                "choice_review_below": choice_cutoff,
                "auto_cases": len(auto_cases),
                "review_cases": review_count,
                "review_rate": round(review_count / len(evaluated), 4)
                if evaluated
                else None,
                "auto_coverage": round(len(auto_cases) / len(evaluated), 4)
                if evaluated
                else None,
                "auto_topic_accuracy": round(auto_correct / len(auto_cases), 4)
                if auto_cases
                else None,
                "all_case_topic_accuracy": round(topic_correct / len(evaluated), 4)
                if evaluated
                else None,
            }
        )

    per_event: dict[str, JsonObject] = {}
    class_f1: list[float] = []
    tp_all = fp_all = fn_all = 0
    event_false_positives: list[JsonObject] = []
    event_false_negatives: list[JsonObject] = []
    threshold = float(taxonomy["thresholds"]["noul_positive_at_or_above"])
    for code in event_codes:
        tp = fp = fn = 0
        for case in evaluated:
            predicted = by_id[case["id"]]["event_scores"][code] >= threshold
            expected = code in case["expected_events"]
            tp += int(predicted and expected)
            fp += int(predicted and not expected)
            fn += int(not predicted and expected)
            if predicted and not expected:
                event_false_positives.append({"case_id": case["id"], "code": code})
            if expected and not predicted:
                event_false_negatives.append({"case_id": case["id"], "code": code})
        f1 = _f1(tp, fp, fn)
        if tp + fn > 0:
            class_f1.append(f1)
        tp_all += tp
        fp_all += fp
        fn_all += fn
        per_event[code] = {
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "f1": round(f1, 4) if tp + fn or tp + fp else None,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "support": tp + fn,
        }
    expected_status_cases = [
        case for case in evaluated if case["expected_status"] in {"uncertain", "other"}
    ]
    uncertain_predicted = [
        case
        for case in evaluated
        if by_id[case["id"]]["classification_status"] in {"uncertain", "other"}
    ]
    correct_uncertain = sum(
        by_id[case["id"]]["classification_status"] == case["expected_status"]
        for case in expected_status_cases
    )
    unlisted_tp = unlisted_fp = unlisted_fn = 0
    unlisted_threshold = float(taxonomy["thresholds"]["noul_positive_at_or_above"])
    for case in evaluated:
        predicted = by_id[case["id"]]["unlisted_event_score"] >= unlisted_threshold
        expected = case["expected_unlisted_event"]
        unlisted_tp += int(predicted and expected)
        unlisted_fp += int(predicted and not expected)
        unlisted_fn += int(not predicted and expected)
    unlisted_threshold_sweep: list[JsonObject] = []
    for cutoff in [round(step / 10, 1) for step in range(3, 10)]:
        tp = fp = fn = 0
        for case in evaluated:
            predicted = by_id[case["id"]]["unlisted_event_score"] >= cutoff
            expected = case["expected_unlisted_event"]
            tp += int(predicted and expected)
            fp += int(predicted and not expected)
            fn += int(not predicted and expected)
        unlisted_threshold_sweep.append(
            {
                "threshold": cutoff,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            }
        )
    uncertainty_review_threshold = float(
        taxonomy["thresholds"]["noul_negative_at_or_below"]
    )
    uncertainty_tp = uncertainty_fp = uncertainty_fn = 0
    for case in evaluated:
        predicted = (
            by_id[case["id"]]["uncertainty_score"] > uncertainty_review_threshold
        )
        expected = case["expected_uncertainty_signal"]
        uncertainty_tp += int(predicted and expected)
        uncertainty_fp += int(predicted and not expected)
        uncertainty_fn += int(not predicted and expected)
    uncertainty_threshold_sweep: list[JsonObject] = []
    for cutoff in [round(step / 10, 1) for step in range(1, 10)]:
        tp = fp = fn = 0
        for case in evaluated:
            predicted = by_id[case["id"]]["uncertainty_score"] > cutoff
            expected = case["expected_uncertainty_signal"]
            tp += int(predicted and expected)
            fp += int(predicted and not expected)
            fn += int(not predicted and expected)
        uncertainty_threshold_sweep.append(
            {
                "threshold_exclusive": cutoff,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "review_rate": round((tp + fp) / len(evaluated), 4)
                if evaluated
                else None,
                "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            }
        )
    topic_codes = [topic["code"] for topic in taxonomy["topics"]]
    topic_confusion = {
        code: {predicted: 0 for predicted in topic_codes} for code in topic_codes
    }
    exact_event_matches = 0
    false_topic_cases: list[JsonObject] = []
    for case in evaluated:
        predicted_topic = by_id[case["id"]]["topic"]
        expected_topic = case["expected_topic"]
        if (
            expected_topic in topic_confusion
            and predicted_topic in topic_confusion[expected_topic]
        ):
            topic_confusion[expected_topic][predicted_topic] += 1
        if predicted_topic != expected_topic:
            false_topic_cases.append(
                {
                    "case_id": case["id"],
                    "expected": expected_topic,
                    "predicted": predicted_topic,
                }
            )
        predicted_events = {
            code
            for code in event_codes
            if by_id[case["id"]]["event_scores"][code] >= threshold
        }
        if predicted_events == set(case["expected_events"]):
            exact_event_matches += 1

    status_codes = ["classified", "uncertain", "other"]
    status_confusion = {
        expected: {predicted: 0 for predicted in status_codes}
        for expected in status_codes
    }
    for case in evaluated:
        expected_status = case["expected_status"]
        predicted_status = by_id[case["id"]]["classification_status"]
        if (
            expected_status in status_confusion
            and predicted_status in status_confusion[expected_status]
        ):
            status_confusion[expected_status][predicted_status] += 1

    case_slices: dict[str, JsonObject] = {}
    slice_types = sorted(
        {
            case["case_type"]
            for case in evaluated
            if isinstance(case.get("case_type"), str)
        }
    )
    for case_type in slice_types:
        subset = [case for case in evaluated if case.get("case_type") == case_type]
        slice_tp = slice_fp = slice_fn = slice_topic_correct = slice_exact = 0
        for case in subset:
            scores = by_id[case["id"]]["event_scores"]
            predicted_events = {
                code for code in event_codes if scores[code] >= threshold
            }
            expected_events = set(case["expected_events"])
            slice_tp += len(predicted_events & expected_events)
            slice_fp += len(predicted_events - expected_events)
            slice_fn += len(expected_events - predicted_events)
            slice_topic_correct += int(
                by_id[case["id"]]["topic"] == case["expected_topic"]
            )
            slice_exact += int(predicted_events == expected_events)
        case_slices[case_type] = {
            "count": len(subset),
            "topic_accuracy": round(slice_topic_correct / len(subset), 4)
            if subset
            else None,
            "event_micro_precision": round(slice_tp / (slice_tp + slice_fp), 4)
            if slice_tp + slice_fp
            else None,
            "event_micro_recall": round(slice_tp / (slice_tp + slice_fn), 4)
            if slice_tp + slice_fn
            else None,
            "event_micro_f1": round(_f1(slice_tp, slice_fp, slice_fn), 4)
            if slice_tp + slice_fp + slice_fn
            else None,
            "event_exact_match_rate": round(slice_exact / len(subset), 4)
            if subset
            else None,
        }

    latencies = sorted(
        float(by_id[case["id"]]["elapsed_ms"])
        for case in evaluated
        if "elapsed_ms" in by_id[case["id"]]
        and _number(by_id[case["id"]]["elapsed_ms"])
        and by_id[case["id"]]["elapsed_ms"] >= 0
    )
    usage_totals = {
        key: sum(
            by_id[case["id"]]["usage"][key]
            for case in evaluated
            if isinstance(by_id[case["id"]].get("usage"), dict)
            and isinstance(by_id[case["id"]]["usage"].get(key), int)
            and not isinstance(by_id[case["id"]]["usage"].get(key), bool)
            and by_id[case["id"]]["usage"][key] >= 0
        )
        if evaluated
        and all(
            isinstance(by_id[case["id"]].get("usage"), dict)
            and isinstance(by_id[case["id"]]["usage"].get(key), int)
            and not isinstance(by_id[case["id"]]["usage"].get(key), bool)
            and by_id[case["id"]]["usage"][key] >= 0
            for case in evaluated
        )
        else None
        for key in ("input_tokens", "output_tokens")
    }
    review_count = sum(
        by_id[case["id"]]["classification_status"] == "uncertain" for case in evaluated
    )
    other_count = sum(
        by_id[case["id"]]["classification_status"] == "other" for case in evaluated
    )
    return {
        "case_count": len(cases),
        "non_empty_case_count": len(evaluated),
        "non_empty_case_total": non_empty_case_total,
        "evaluation_complete": len(evaluated) == non_empty_case_total,
        "evaluation_coverage": round(len(evaluated) / non_empty_case_total, 4)
        if non_empty_case_total
        else None,
        "topic_accuracy": round(topic_correct / len(evaluated), 4)
        if evaluated
        else None,
        "topic_correct": topic_correct,
        "topic_total": len(evaluated),
        "topic_confusion_matrix": topic_confusion,
        "topic_misclassifications": false_topic_cases,
        "classification_status_confusion_matrix": status_confusion,
        "case_type_slices": case_slices,
        "event_exact_match_rate": round(exact_event_matches / len(evaluated), 4)
        if evaluated
        else None,
        "event_exact_match_count": exact_event_matches,
        "event_false_positives": event_false_positives,
        "event_false_negatives": event_false_negatives,
        "event_micro_precision": round(tp_all / (tp_all + fp_all), 4)
        if tp_all + fp_all
        else None,
        "event_micro_recall": round(tp_all / (tp_all + fn_all), 4)
        if tp_all + fn_all
        else None,
        "event_micro_f1": round(_f1(tp_all, fp_all, fn_all), 4)
        if tp_all + fp_all + fn_all
        else None,
        "event_macro_f1": round(sum(class_f1) / len(class_f1), 4) if class_f1 else None,
        "event_macro_f1_supported_classes": len(class_f1),
        "event_threshold": threshold,
        "threshold_sweep_type": "event positive cutoff; negative cutoff fixed, scores between cutoffs route to review",
        "event_review_band_sweep": event_threshold_grid,
        "choice_review_threshold_sweep": choice_threshold_rows,
        "unlisted_threshold_sweep": unlisted_threshold_sweep,
        "uncertainty_threshold_sweep": uncertainty_threshold_sweep,
        "per_event": per_event,
        "threshold_sweep": threshold_rows,
        "review_count": review_count,
        "review_rate": round(review_count / len(evaluated), 4) if evaluated else None,
        "other_count": other_count,
        "other_rate": round(other_count / len(evaluated), 4) if evaluated else None,
        "review_or_other_count": len(uncertain_predicted),
        "review_or_other_rate": round(len(uncertain_predicted) / len(evaluated), 4)
        if evaluated
        else None,
        "expected_review_or_other_count": len(expected_status_cases),
        "expected_review_or_other_exact_matches": correct_uncertain,
        "expected_unlisted_event_count": sum(
            case["expected_unlisted_event"] for case in evaluated
        ),
        "unlisted_event_precision": round(unlisted_tp / (unlisted_tp + unlisted_fp), 4)
        if unlisted_tp + unlisted_fp
        else None,
        "unlisted_event_recall": round(unlisted_tp / (unlisted_tp + unlisted_fn), 4)
        if unlisted_tp + unlisted_fn
        else None,
        "unlisted_event_exact": unlisted_fp == 0 and unlisted_fn == 0
        if evaluated
        else None,
        "expected_uncertainty_signal_count": sum(
            case["expected_uncertainty_signal"] for case in evaluated
        ),
        "uncertainty_signal_precision": round(
            uncertainty_tp / (uncertainty_tp + uncertainty_fp), 4
        )
        if uncertainty_tp + uncertainty_fp
        else None,
        "uncertainty_signal_recall": round(
            uncertainty_tp / (uncertainty_tp + uncertainty_fn), 4
        )
        if uncertainty_tp + uncertainty_fn
        else None,
        "uncertainty_signal_threshold": uncertainty_review_threshold,
        "latency": {
            "n": len(latencies),
            "mean_ms": round(statistics.fmean(latencies), 2) if latencies else None,
            "median_ms": statistics.median(latencies) if latencies else None,
            "p95_nearest_rank_ms": latencies[
                max(0, math.ceil(0.95 * len(latencies)) - 1)
            ]
            if latencies
            else None,
            "p95_method": "nearest-rank; descriptive only; small-sample estimates are unstable",
        },
        "token_usage": {
            "input_tokens": usage_totals["input_tokens"],
            "output_tokens": usage_totals["output_tokens"],
            "total_tokens": sum(usage_totals.values())
            if all(value is not None for value in usage_totals.values())
            else None,
        },
        "note": "Pilot corpus metrics only; synthetic and small. Threshold sweep is descriptive and must not be treated as production calibration.",
    }
