"""Run one-shot Jev calls against the frozen synthetic pilot.

This runner is isolated from the exhausted historical T08 call ledger. It
reserves each request before sending, never retries, and stores sanitized
interpretations only. It is intentionally Jev-only; there is no model fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

T08_DIR = Path(__file__).resolve().parents[2]
STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(T08_DIR))

from jev_spike import (  # noqa: E402
    DEFAULT_MODEL,
    JevClient,
    LiveRequestError,
    SpikeError,
    evaluate,
    interpret_response,
    make_request,
    request_hash,
    taxonomy_hash,
    validate_taxonomy,
)
from visualization.policy_v2 import compare_policies  # noqa: E402

STUDY_ID = "jev-ru-expanded-pilot-1.0.0"
MAX_CALLS = 50
SOFT_STOP_AFTER_COST_RUB = 10.0
ESTIMATED_COST_PER_CALL_RUB = 0.20
NEWS_SHA256 = "d99b0d85ba29028fc96f74315cd38c15b768e2d060037d3b892b953b16c26dcc"
ANNOTATIONS_SHA256 = "466617b5dcfdea4eadee181358bc20f2cc21471bea8d4e95b518727e07bf07d0"
TAXONOMY_RAW_SHA256 = "855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d"
SOURCE_NEWS_PATH = T08_DIR / "experiments" / "future-blind-candidate-v1" / "news.json"
SOURCE_NEWS_SHA256 = "ac3b8582c0f228b35259c3dcbba0e1dc3070e079c00fa4d97e0961bc7bd15f7c"
ANNOTATION_REVIEW_PATH = STUDY_DIR / "ANNOTATION_REVIEW.md"
DATASET_BUILDER_PATH = STUDY_DIR / "build_dataset.py"
NEWS_PATH = STUDY_DIR / "news.json"
ANNOTATIONS_PATH = STUDY_DIR / "annotations.json"
TAXONOMY_PATH = T08_DIR / "taxonomy.json"
RESULTS_PATH = STUDY_DIR / "live-results.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".jev-study-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(
                json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
            )
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _saved_result_is_valid(
    result: dict[str, Any], case: dict[str, Any], taxonomy: dict[str, Any]
) -> bool:
    """Revalidate persisted scores through the exact live response validator."""
    expected_keys = {
        "case_id",
        "taxonomy_id",
        "taxonomy_version",
        "taxonomy_hash",
        "model_version",
        "topic",
        "topic_confidence",
        "topic_probabilities",
        "event_scores",
        "unlisted_event_score",
        "uncertainty_score",
        "predicted_events",
        "classification_status",
        "usage",
        "elapsed_ms",
        "request_sha256",
    }
    if not isinstance(result, dict) or set(result) != expected_keys:
        return False
    if (
        not isinstance(result.get("elapsed_ms"), int)
        or isinstance(result.get("elapsed_ms"), bool)
        or result["elapsed_ms"] < 0
    ):
        return False
    request = make_request(case, taxonomy, model=DEFAULT_MODEL)
    answers = {
        taxonomy["topic_choice_id"]: {
            "type": "choice",
            "choice": result["topic"],
            "confidence": result["topic_confidence"],
            "probabilities": result["topic_probabilities"],
        },
        **{
            f"event_{code}": {"type": "noul", "noul": score}
            for code, score in result["event_scores"].items()
        },
        taxonomy["unlisted_event_code"]: {
            "type": "noul",
            "noul": result["unlisted_event_score"],
        },
        taxonomy["uncertainty_signal_code"]: {
            "type": "noul",
            "noul": result["uncertainty_score"],
        },
    }
    response = {
        "model": result["model_version"],
        "answers": answers,
        "usage": result["usage"],
        "_local_elapsed_ms": result["elapsed_ms"],
    }
    try:
        recomputed = interpret_response(case, response, request, taxonomy).result
    except (SpikeError, LiveRequestError, KeyError, TypeError, ValueError):
        return False
    recomputed["request_sha256"] = result["request_sha256"]
    return recomputed == result


def _state_root() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    return Path(root) if root else Path.home() / ".local" / "state"


class StudyLedger:
    """Per-study ledger; never seeds or edits the historical T08 ledger."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (
            _state_root()
            / "AlfaBankHackathon"
            / "T08"
            / "studies"
            / STUDY_ID
            / "attempts.json"
        )
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "study_id": STUDY_ID, "attempts": []}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise SpikeError("study_ledger_invalid") from None
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "study_id", "attempts"}
            or value.get("schema_version") != 1
            or value.get("study_id") != STUDY_ID
            or not isinstance(value.get("attempts"), list)
            or len(value["attempts"]) > MAX_CALLS
        ):
            raise SpikeError("study_ledger_invalid")
        seen: set[str] = set()
        for entry in value["attempts"]:
            if (
                not isinstance(entry, dict)
                or set(entry)
                != {
                    "case_id",
                    "request_sha256",
                    "status",
                    "timestamp_utc",
                    "error_code",
                    "result_sha256",
                }
                or not isinstance(entry.get("case_id"), str)
                or not isinstance(entry.get("request_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["request_sha256"])
                or entry["status"] not in {"reserved", "succeeded", "failed"}
                or (
                    entry["status"] == "failed"
                    and (
                        not isinstance(entry.get("error_code"), str)
                        or not re.fullmatch(r"[a-z0-9_]+", entry["error_code"])
                    )
                )
                or (entry["status"] != "failed" and entry.get("error_code") is not None)
                or (
                    entry["status"] == "succeeded"
                    and (
                        not isinstance(entry.get("result_sha256"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", entry["result_sha256"])
                    )
                )
                or (
                    entry["status"] != "succeeded"
                    and entry.get("result_sha256") is not None
                )
                or entry["case_id"] in seen
            ):
                raise SpikeError("study_ledger_invalid")
            seen.add(entry["case_id"])
            if entry["status"] == "reserved":
                raise SpikeError("study_ledger_has_incomplete_attempt")
        return value

    def save(self, data: dict[str, Any]) -> None:
        _dump_atomic(self.path, data)


def _load_study() -> tuple[
    dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]
]:
    if _sha(NEWS_PATH) != NEWS_SHA256:
        raise SpikeError("study_news_hash_mismatch")
    if _sha(ANNOTATIONS_PATH) != ANNOTATIONS_SHA256:
        raise SpikeError("study_annotations_hash_mismatch")
    if _sha(TAXONOMY_PATH) != TAXONOMY_RAW_SHA256:
        raise SpikeError("study_taxonomy_hash_mismatch")
    try:
        news = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
        annotations = json.loads(ANNOTATIONS_PATH.read_text(encoding="utf-8"))
        taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
        manifest = json.loads((STUDY_DIR / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SpikeError("study_input_invalid") from None
    if (
        not isinstance(news, dict)
        or not isinstance(annotations, dict)
        or not isinstance(manifest, dict)
    ):
        raise SpikeError("study_input_invalid")
    validate_taxonomy(taxonomy)
    cases = news.get("cases") if isinstance(news, dict) else None
    labels = annotations.get("cases") if isinstance(annotations, dict) else None
    if (
        news.get("dataset_id") != "jev-ru-expanded-pilot"
        or news.get("version") != "1.0.0"
        or news.get("status") != "pre-registered-synthetic-only-exploratory"
        or not isinstance(cases, list)
        or len(cases) != MAX_CALLS
        or not isinstance(labels, list)
        or len(labels) != len(cases)
    ):
        raise SpikeError("study_input_invalid")
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    label_ids = [label.get("case_id") for label in labels if isinstance(label, dict)]
    if (
        len(case_ids) != MAX_CALLS
        or len(set(case_ids)) != MAX_CALLS
        or case_ids != label_ids
    ):
        raise SpikeError("study_case_labels_mismatch")
    topic_codes = {row["code"] for row in taxonomy["topics"]}
    event_codes = {row["code"] for row in taxonomy["events"]}
    for case, label in zip(cases, labels, strict=True):
        if (
            not isinstance(case.get("title"), str)
            or not isinstance(case.get("text"), str)
            or not case["title"].strip()
            or not case["text"].strip()
            or set(case).difference({"id", "title", "text"})
            or label.get("topic") not in topic_codes
            or not isinstance(label.get("events"), list)
            or not set(label["events"]).issubset(event_codes)
            or not isinstance(label.get("unlisted_event"), bool)
            or not isinstance(label.get("insufficient_evidence"), bool)
        ):
            raise SpikeError("study_case_or_annotation_invalid")
        if not isinstance(label.get("evidence_spans"), dict):
            raise SpikeError("study_evidence_span_invalid")
        for code, quote in label["evidence_spans"].items():
            if code not in event_codes | {
                "unlisted_business_event",
                "insufficient_evidence",
            }:
                raise SpikeError("study_evidence_span_invalid")
            if not isinstance(quote, str) or quote not in case["text"]:
                raise SpikeError("study_evidence_span_invalid")
    runner_path = STUDY_DIR / "run_pilot.py"
    if (
        manifest.get("study_id") != f"{news['dataset_id']}-{news['version']}"
        or manifest.get("news_sha256") != NEWS_SHA256
        or manifest.get("annotations_sha256") != ANNOTATIONS_SHA256
        or manifest.get("baseline_taxonomy_sha256") != TAXONOMY_RAW_SHA256
        or manifest.get("source_candidate_news_sha256") != SOURCE_NEWS_SHA256
        or manifest.get("source_candidate_pool_blind") is not False
        or manifest.get("annotation_review_sha256") != _sha(ANNOTATION_REVIEW_PATH)
        or manifest.get("dataset_builder_sha256") != _sha(DATASET_BUILDER_PATH)
        or manifest.get("runner_sha256") != _sha(runner_path)
        or manifest.get("maximum_new_jev_calls") != MAX_CALLS
        or manifest.get("soft_stop_after_cost_rub") != SOFT_STOP_AFTER_COST_RUB
        or manifest.get("estimated_cost_per_request_rub") != ESTIMATED_COST_PER_CALL_RUB
    ):
        raise SpikeError("study_manifest_hash_mismatch")
    expected_taxonomy_hash = taxonomy_hash(taxonomy)
    if manifest.get("baseline_taxonomy_canonical_sha256") != expected_taxonomy_hash:
        raise SpikeError("study_manifest_hash_mismatch")
    if _sha(SOURCE_NEWS_PATH) != SOURCE_NEWS_SHA256:
        raise SpikeError("study_source_candidate_hash_mismatch")
    request_hashes = {
        case["id"]: request_hash(make_request(case, taxonomy, model=DEFAULT_MODEL))
        for case in cases
    }
    if manifest.get("approved_request_sha256_by_case") != request_hashes:
        raise SpikeError("study_request_manifest_mismatch")
    return news, cases, taxonomy, labels


def run(count: int, ledger: StudyLedger | None = None) -> dict[str, Any]:
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= MAX_CALLS
    ):
        raise SpikeError("call_count_out_of_range")
    ledger = ledger or StudyLedger()
    with ledger.exclusive():
        return _run_locked(count, ledger)


def _run_locked(count: int, ledger: StudyLedger) -> dict[str, Any]:
    news, cases, taxonomy, _labels = _load_study()
    state = ledger.load()
    attempts = state["attempts"]
    if any(item["status"] == "failed" for item in attempts):
        raise SpikeError("study_previous_attempt_failed")
    if len(attempts) >= MAX_CALLS:
        raise SpikeError("study_call_budget_exhausted")
    expected_order = [case["id"] for case in cases[: len(attempts)]]
    if [item["case_id"] for item in attempts] != expected_order:
        raise SpikeError("study_ledger_case_order_invalid")
    pending = cases[len(attempts) : len(attempts) + count]
    if not pending:
        raise SpikeError("study_has_no_pending_cases")
    if RESULTS_PATH.exists():
        try:
            previous = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise SpikeError("study_results_invalid") from None
        results = previous.get("results", []) if isinstance(previous, dict) else None
        successful_attempts = [x for x in attempts if x["status"] == "succeeded"]
        if (
            not isinstance(previous, dict)
            or previous.get("schema_version") != "t08-jev-expanded-pilot-results-v1"
            or previous.get("study_id") != STUDY_ID
            or previous.get("news_sha256") != NEWS_SHA256
            or previous.get("annotations_sha256") != ANNOTATIONS_SHA256
            or previous.get("taxonomy_sha256") != TAXONOMY_RAW_SHA256
            or not isinstance(results, list)
            or any(not isinstance(row, dict) for row in results)
            or len(results) != len(successful_attempts)
        ):
            raise SpikeError("study_results_ledger_mismatch")
        if [row.get("case_id") for row in results] != [
            entry["case_id"] for entry in successful_attempts
        ]:
            raise SpikeError("study_results_ledger_mismatch")
        case_by_id = {case["id"]: case for case in cases}
        for result, attempt in zip(results, successful_attempts, strict=True):
            case = case_by_id.get(result.get("case_id"))
            if (
                case is None
                or result.get("request_sha256") != attempt["request_sha256"]
                or attempt["request_sha256"]
                != request_hash(make_request(case, taxonomy, model=DEFAULT_MODEL))
                or hashlib.sha256(_canonical(result)).hexdigest()
                != attempt["result_sha256"]
                or not _saved_result_is_valid(result, case, taxonomy)
            ):
                raise SpikeError("study_results_ledger_mismatch")
    else:
        if attempts:
            raise SpikeError("study_results_missing_after_attempt")
        results = []
    initial_cost = sum(
        float(row.get("usage", {}).get("cost_rub", 0)) for row in results
    )
    if initial_cost + ESTIMATED_COST_PER_CALL_RUB > SOFT_STOP_AFTER_COST_RUB:
        report = _report(news, taxonomy, results, attempts, None, "cost_guard")
        _dump_atomic(RESULTS_PATH, report)
        print("PILOT stopped=cost_guard")
        return report

    requests = [make_request(case, taxonomy, model=DEFAULT_MODEL) for case in cases]
    hashes = [request_hash(request) for request in requests]
    if len(set(hashes)) != MAX_CALLS:
        raise SpikeError("study_requests_not_unique")
    client = JevClient(
        os.environ.get("POLZA_AI_API_KEY", ""),
        allowed_request_hashes=set(hashes),
    )

    stop_reason = None
    for case in pending:
        spent = sum(float(row["usage"]["cost_rub"]) for row in results)
        if spent + ESTIMATED_COST_PER_CALL_RUB > SOFT_STOP_AFTER_COST_RUB:
            stop_reason = "cost_guard"
            break
        index = len(attempts)
        digest = hashes[index]
        reservation = {
            "case_id": case["id"],
            "request_sha256": digest,
            "status": "reserved",
            "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "error_code": None,
            "result_sha256": None,
        }
        attempts.append(reservation)
        ledger.save(state)
        try:
            response = client.classify(requests[index])
            result = interpret_response(
                case, response, requests[index], taxonomy
            ).result
            result["request_sha256"] = digest
            results.append(result)
            reservation["status"] = "succeeded"
            reservation["result_sha256"] = hashlib.sha256(
                _canonical(result)
            ).hexdigest()
            _dump_atomic(RESULTS_PATH, _report(news, taxonomy, results, attempts, None))
            ledger.save(state)
            print(
                f"LIVE case={case['id']} model={result['model_version']} latency_ms={result['elapsed_ms']}"
            )
            if result["usage"]["cost_rub"] > ESTIMATED_COST_PER_CALL_RUB:
                stop_reason = "single_call_cost_exceeded_reserve"
                break
        except (SpikeError, LiveRequestError) as exc:
            # Only local safe error codes are persisted; never provider body/text.
            reservation["status"] = "failed"
            reservation["error_code"] = str(exc)
            ledger.save(state)
            _dump_atomic(
                RESULTS_PATH, _report(news, taxonomy, results, attempts, str(exc))
            )
            print(f"LIVE case={case['id']} error={exc}", file=sys.stderr)
            break
        except Exception:  # noqa: BLE001 - hide all unexpected/provider details.
            reservation["status"] = "failed"
            reservation["error_code"] = "unexpected_runtime_error"
            ledger.save(state)
            _dump_atomic(
                RESULTS_PATH,
                _report(news, taxonomy, results, attempts, "unexpected_runtime_error"),
            )
            print(
                f"LIVE case={case['id']} error=unexpected_runtime_error",
                file=sys.stderr,
            )
            break
    final_error = next(
        (x["error_code"] for x in attempts if x["status"] == "failed"), None
    )
    report = _report(news, taxonomy, results, attempts, final_error, stop_reason)
    _dump_atomic(RESULTS_PATH, report)
    print(
        f"PILOT successful={len(results)} attempted={len(attempts)} complete={report['complete']}"
    )
    return report


def _report(
    news: dict[str, Any],
    taxonomy: dict[str, Any],
    results: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    failure: str | None,
    stop_reason: str | None = None,
) -> dict[str, Any]:
    metrics = None
    policy_comparison = None
    if len(results) == MAX_CALLS and failure is None:
        _news, cases, loaded_taxonomy, labels = _load_study()
        label_by_id = {label["case_id"]: label for label in labels}
        result_by_id = {row["case_id"]: row for row in results}
        scored_cases: list[dict[str, Any]] = []
        for case in cases:
            label = label_by_id[case["id"]]
            uncertainty = label["insufficient_evidence"]
            topic = label["topic"]
            expected_status = (
                "uncertain"
                if uncertainty
                else "other"
                if topic == loaded_taxonomy["other_code"]
                else "classified"
            )
            event_count = len(label["events"])
            case_type = (
                "ambiguous_or_speculative"
                if uncertainty
                else "out_of_taxonomy_business_event"
                if label["unlisted_event"]
                else "multi_event"
                if event_count > 1
                else "single_event"
                if event_count == 1
                else "no_listed_event"
            )
            scored_cases.append(
                {
                    **case,
                    "expected_topic": topic,
                    "expected_events": label["events"],
                    "expected_unlisted_event": label["unlisted_event"],
                    "expected_uncertainty_signal": uncertainty,
                    "expected_status": expected_status,
                    "case_type": case_type,
                    "result": result_by_id[case["id"]],
                }
            )
        metrics = evaluate(scored_cases, results, loaded_taxonomy)
        policy_comparison = compare_policies(
            scored_cases,
            loaded_taxonomy,
            legacy_predictions={
                case["id"]: set(result_by_id[case["id"]]["predicted_events"])
                for case in scored_cases
            },
            legacy_review_ids={
                case["id"]
                for case in scored_cases
                if result_by_id[case["id"]]["classification_status"]
                in {"uncertain", "other"}
            },
        )
    return {
        "schema_version": "t08-jev-expanded-pilot-results-v1",
        "study_id": STUDY_ID,
        "status": "complete"
        if len(results) == MAX_CALLS and failure is None and stop_reason is None
        else "incomplete",
        "complete": len(results) == MAX_CALLS
        and failure is None
        and stop_reason is None,
        "request_model_id": DEFAULT_MODEL,
        "resolved_model_versions": sorted({r["model_version"] for r in results}),
        "news_sha256": NEWS_SHA256,
        "annotations_sha256": ANNOTATIONS_SHA256,
        "taxonomy_sha256": TAXONOMY_RAW_SHA256,
        "taxonomy_canonical_sha256": taxonomy_hash(taxonomy),
        "attempt_count": len(attempts),
        "successful_count": len(results),
        "call_budget": MAX_CALLS,
        "soft_stop_after_cost_rub": SOFT_STOP_AFTER_COST_RUB,
        "estimated_cost_per_call_rub": ESTIMATED_COST_PER_CALL_RUB,
        "cost_guard_is_hard_cap": False,
        "successful_cost_total_rub": round(
            sum(float(row["usage"]["cost_rub"]) for row in results), 8
        ),
        "retries": 0,
        "fallback_used": False,
        "failed_attempt_cost_status": "UNKNOWN_POSSIBLY_BILLED" if failure else None,
        "label_status": "preliminary_single_curator_not_human_adjudicated",
        "metrics_status": "measured_on_draft_labels"
        if metrics is not None
        else "not_measured_incomplete_run",
        "metrics": metrics,
        "policy_v2_1_comparison": policy_comparison,
        "failure_code": failure,
        "stop_reason": stop_reason,
        "results": results,
        "note": "Synthetic-only exploratory pilot. Responses are sanitized; annotations are single-curator draft labels, not human-adjudicated gold. No automatic retries or model fallback. The cost stop uses a per-call estimate; one call can exceed the threshold before its returned usage is known.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="attempt at most this many next cases (1..50)",
    )
    args = parser.parse_args()
    try:
        report = run(args.count)
        return 1 if report["failure_code"] else 0
    except (SpikeError, OSError, ValueError) as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
