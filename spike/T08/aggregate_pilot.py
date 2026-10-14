"""Safely merge non-overlapping, sanitized segments of the pinned live pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jev_spike import (
    CORPUS_PATH,
    RESOLVED_JEV_MODEL,
    SPIKE_DIR,
    TAXONOMY_PATH,
    SpikeError,
    choice_confidence_matches,
    evaluate,
    load_verified_inputs,
    make_request,
    request_hash,
    taxonomy_hash,
)
from live_ledger import HISTORICAL_CASE_ID, HISTORICAL_REQUEST_SHA256

JsonObject = dict[str, Any]
MAX_REPORT_BYTES = 2_000_000
SAFE_FAILURE_CODES = {
    "timeout",
    "connection_error",
    "redirect_refused",
    "unapproved_endpoint",
    "invalid_json_response",
    "invalid_response_body",
    "response_too_large",
    "invalid_provider_response",
    "sanitized_request_error",
}
HISTORICAL_SMOKE_PATH = SPIKE_DIR / "results" / "jev-live-pilot-20261014T094655Z.json"
HISTORICAL_SMOKE_SHA256 = (
    "2c08601efae297f58df6de808d87e1c255a61778a3a4bf66a781a6eb6057fcff"
)
HISTORICAL_LEGACY_FAILURE_PATH = (
    SPIKE_DIR / "results" / "jev-live-pilot-20261014T094544Z.json"
)
HISTORICAL_LEGACY_FAILURE_SHA256 = (
    "129faa1b0b9e7f05aa06dcaffcf7f6eec20c97052ac5ed11b4a32ab5dce27cfa"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_safe_failure_code(value: Any) -> bool:
    if value in SAFE_FAILURE_CODES:
        return True
    return (
        isinstance(value, str)
        and value.startswith("http_status_")
        and value[12:].isdigit()
        and 400 <= int(value[12:]) <= 599
    )


def _inside_spike(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(SPIKE_DIR.resolve()):
        raise SpikeError("report path must stay inside spike/T08")
    return resolved


def _read_report(path: Path) -> JsonObject:
    resolved = _inside_spike(path)
    try:
        if resolved.stat().st_size > MAX_REPORT_BYTES:
            raise SpikeError("pilot report is too large")
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpikeError("pilot report cannot be read") from exc
    if not isinstance(value, dict):
        raise SpikeError("pilot report must be a JSON object")
    return value


def _validate_historical_legacy_failure() -> JsonObject:
    """Validate the separately recorded, failed legacy TypeSafe probe."""
    path = HISTORICAL_LEGACY_FAILURE_PATH.resolve()
    if _sha256(path) != HISTORICAL_LEGACY_FAILURE_SHA256:
        raise SpikeError("pinned historical legacy failure artifact changed")
    report = _read_report(path)
    if (
        report.get("mode") != "live_synthetic_pilot"
        or report.get("endpoint_host") != "api.typesafe.ai"
        or report.get("endpoint_path") != "/v1/systemone"
        or report.get("attempted_calls") != 1
        or report.get("successful_calls") != 0
        or report.get("request_sha256_by_case")
        != {
            "e01-supply-rail": "32267acce614055107a4c627a29167d0b9d19603d412c0a6722df3a0f1558291"
        }
        or report.get("failures")
        != [{"case_id": "e01-supply-rail", "error": "sanitized_request_error"}]
        or report.get("results") != []
        or report.get("metrics") is not None
    ):
        raise SpikeError("pinned historical legacy failure has changed shape")
    return {
        "case_id": "e01-supply-rail",
        "endpoint_host": "api.typesafe.ai",
        "endpoint_path": "/v1/systemone",
        "error": "sanitized_request_error",
        "artifact": path.name,
        "artifact_sha256": HISTORICAL_LEGACY_FAILURE_SHA256,
    }


def _validate_result(
    result: Any,
    *,
    case: JsonObject,
    taxonomy: JsonObject,
    expected_request_hash: str,
) -> str:
    required = {
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
    if not isinstance(result, dict) or set(result) != required:
        raise SpikeError("pilot result has an unexpected or sensitive field")
    if result["case_id"] != case["id"]:
        raise SpikeError("pilot result case order does not match the pinned corpus")
    if (
        result["taxonomy_id"] != taxonomy["id"]
        or result["taxonomy_version"] != taxonomy["version"]
        or result["taxonomy_hash"] != taxonomy_hash(taxonomy)
    ):
        raise SpikeError("pilot result taxonomy does not match the pinned taxonomy")
    model_version = result["model_version"]
    if not isinstance(model_version, str) or not RESOLVED_JEV_MODEL.fullmatch(
        model_version
    ):
        raise SpikeError("pilot result has an invalid resolved model version")
    topic_codes = {row["code"] for row in taxonomy["topics"]}
    event_codes = {row["code"] for row in taxonomy["events"]}
    if result["topic"] not in topic_codes:
        raise SpikeError("pilot result contains an unknown topic")
    if (
        not _number(result["topic_confidence"])
        or not 0 <= result["topic_confidence"] <= 1
    ):
        raise SpikeError("pilot result has invalid Choice confidence")
    topic_probabilities = result["topic_probabilities"]
    if (
        not isinstance(topic_probabilities, dict)
        or set(topic_probabilities) != topic_codes
    ):
        raise SpikeError("pilot result has an invalid Choice probability set")
    if any(
        not _number(score) or not 0 <= score <= 1
        for score in topic_probabilities.values()
    ):
        raise SpikeError("pilot result has an invalid Choice probability")
    if not math.isclose(sum(topic_probabilities.values()), 1.0, abs_tol=1e-6):
        raise SpikeError("pilot result Choice probabilities do not sum to one")
    if topic_probabilities[result["topic"]] != max(topic_probabilities.values()):
        raise SpikeError("pilot result Choice does not match its highest probability")
    if not choice_confidence_matches(topic_probabilities, result["topic_confidence"]):
        raise SpikeError("pilot result Choice confidence does not match probabilities")
    event_scores = result["event_scores"]
    if not isinstance(event_scores, dict) or set(event_scores) != event_codes:
        raise SpikeError("pilot result has an invalid event score set")
    if any(
        not _number(score) or not 0 <= score <= 1 for score in event_scores.values()
    ):
        raise SpikeError("pilot result has an invalid event score")
    for key in ("unlisted_event_score", "uncertainty_score"):
        if not _number(result[key]) or not 0 <= result[key] <= 1:
            raise SpikeError(f"pilot result has invalid {key}")
    expected_events = [
        row["code"]
        for row in taxonomy["events"]
        if event_scores[row["code"]]
        >= taxonomy["thresholds"]["noul_positive_at_or_above"]
    ]
    if result["predicted_events"] != expected_events:
        raise SpikeError("pilot result predicted events disagree with the scores")
    thresholds = taxonomy["thresholds"]
    negative = thresholds["noul_negative_at_or_below"]
    positive = thresholds["noul_positive_at_or_above"]
    review_below = thresholds["choice_review_below"]
    borderline_events = any(
        negative < score < positive for score in event_scores.values()
    )
    needs_review = (
        result["topic_confidence"] < review_below
        or borderline_events
        or result["unlisted_event_score"] > negative
        or result["uncertainty_score"] > negative
    )
    if result["topic"] == taxonomy["other_code"]:
        expected_status = (
            "uncertain"
            if result["topic_confidence"] < review_below
            or result["uncertainty_score"] > negative
            else "other"
        )
    else:
        expected_status = "uncertain" if needs_review else "classified"
    if result["classification_status"] != expected_status:
        raise SpikeError("pilot result status disagrees with the pinned thresholds")
    usage = result["usage"]
    if not isinstance(usage, dict) or set(usage) != {
        "input_tokens",
        "output_tokens",
        "cost_rub",
    }:
        raise SpikeError("pilot result has invalid usage metadata")
    for key in ("input_tokens", "output_tokens"):
        if (
            not isinstance(usage[key], int)
            or isinstance(usage[key], bool)
            or usage[key] < 0
        ):
            raise SpikeError("pilot result has invalid usage metadata")
    if not _number(usage["cost_rub"]) or usage["cost_rub"] < 0:
        raise SpikeError("pilot result has invalid usage metadata")
    if not _number(result["elapsed_ms"]) or result["elapsed_ms"] < 0:
        raise SpikeError("pilot result has invalid elapsed time")
    if result["request_sha256"] != expected_request_hash:
        raise SpikeError("pilot result request hash does not match the pinned request")
    return model_version


def aggregate_reports(report_paths: list[Path]) -> JsonObject:
    if not report_paths:
        raise SpikeError("at least one segment report is required")
    taxonomy, corpus, all_cases = load_verified_inputs()
    cases = [case for case in all_cases if case["expected_status"] != "no_content"]
    expected_ids = [case["id"] for case in cases]
    pinned_hashes = {
        case["id"]: request_hash(make_request(case, taxonomy)) for case in cases
    }

    reports: list[tuple[Path, JsonObject, bool]] = []
    expected_metadata: dict[str, Any] | None = None
    for path in report_paths:
        resolved = _inside_spike(path)
        report = _read_report(resolved)
        is_historical_seed = resolved == HISTORICAL_SMOKE_PATH.resolve()
        if is_historical_seed and _sha256(resolved) != HISTORICAL_SMOKE_SHA256:
            raise SpikeError("pinned historical smoke artifact changed")
        metadata = {
            key: report.get(key)
            for key in (
                "mode",
                "endpoint_host",
                "endpoint_path",
                "corpus_id",
                "taxonomy_id",
                "taxonomy_version",
                "taxonomy_hash",
                "taxonomy_sha256_raw",
                "corpus_sha256",
                "requested_model_id",
            )
        }
        if expected_metadata is None:
            expected_metadata = metadata
        elif metadata != expected_metadata:
            raise SpikeError("pilot segments have incompatible pinned metadata")
        for code_hash in (report.get("client_sha256"), report.get("runner_sha256")):
            if not isinstance(code_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", code_hash
            ):
                raise SpikeError("pilot segment code hash is invalid")
        if is_historical_seed:
            historical_results = report.get("results")
            if (
                report.get("successful_calls") != 1
                or report.get("attempted_calls") != 1
                or report.get("request_sha256_by_case")
                != {HISTORICAL_CASE_ID: HISTORICAL_REQUEST_SHA256}
                or not isinstance(historical_results, list)
                or len(historical_results) != 1
                or not isinstance(historical_results[0], dict)
                or historical_results[0].get("case_id") != HISTORICAL_CASE_ID
            ):
                raise SpikeError("pinned historical smoke artifact has changed shape")
            start_case_id = HISTORICAL_CASE_ID
            end_case_id = HISTORICAL_CASE_ID
            transport_provenance = "historical_artifact_unattested"
            ledger_start_count = 0
            ledger_end_count = 1
            failures = []
        else:
            if report.get("transport_provenance") not in {
                "official_polza_https",
                "custom_or_test_transport",
            }:
                raise SpikeError("pilot segment transport provenance is missing")
            start_case_id = report.get("start_at_case_id")
            end_case_id = report.get("end_at_case_id")
            transport_provenance = report["transport_provenance"]
            ledger_start_count = report.get("ledger_start_count")
            ledger_end_count = report.get("ledger_end_count")
            failures = report.get("failures")
            if (
                not isinstance(failures, list)
                or len(failures) > 1
                or any(
                    not isinstance(item, dict)
                    or set(item) != {"case_id", "error"}
                    or not isinstance(item.get("case_id"), str)
                    or not _is_safe_failure_code(item.get("error"))
                    for item in failures
                )
            ):
                raise SpikeError("pilot segment has an invalid sanitized failure")
            results = report.get("results")
            attempted_calls = report.get("attempted_calls")
            if (
                not isinstance(ledger_start_count, int)
                or isinstance(ledger_start_count, bool)
                or not isinstance(ledger_end_count, int)
                or isinstance(ledger_end_count, bool)
                or not isinstance(attempted_calls, int)
                or isinstance(attempted_calls, bool)
                or ledger_start_count < 1
                or ledger_end_count - ledger_start_count != attempted_calls
                or not isinstance(results, list)
                or attempted_calls != len(results) + len(failures)
            ):
                raise SpikeError("pilot segment cumulative ledger range is invalid")
        if (
            report.get("mode") != "live_synthetic_pilot"
            or report.get("endpoint_host") != "polza.ai"
            or report.get("endpoint_path") != "/api/v1/systemone"
            or report.get("corpus_id") != corpus["corpus_id"]
            or report.get("taxonomy_id") != taxonomy["id"]
            or report.get("taxonomy_version") != taxonomy["version"]
            or report.get("taxonomy_hash") != taxonomy_hash(taxonomy)
            or report.get("taxonomy_sha256_raw") != _sha256(TAXONOMY_PATH)
            or report.get("corpus_sha256") != _sha256(CORPUS_PATH)
            or report.get("requested_model_id") != "typesafe/jev"
        ):
            raise SpikeError("pilot segment does not match the pinned Polza baseline")
        if report.get("control_calls") != 0 or report.get("controls") != {}:
            raise SpikeError("unexpected control calls in pilot segment")
        if (
            report.get("metrics") is not None
            or report.get("quality_metrics_status") != "NOT_MEASURED_INCOMPLETE_RUN"
        ):
            raise SpikeError("only partial segment reports may be aggregated")
        results = report.get("results")
        if not isinstance(results, list) or not results:
            raise SpikeError("pilot segment has no successful results")
        if (
            report.get("successful_calls") != len(results)
            or report.get("attempted_calls") != len(results) + len(failures)
            or (
                not is_historical_seed
                and report.get("max_calls_per_invocation", 0)
                < report.get("attempted_calls", 0)
            )
        ):
            raise SpikeError("pilot segment call counts are inconsistent")
        ids = [
            result.get("case_id") if isinstance(result, dict) else None
            for result in results
        ]
        try:
            start_index = expected_ids.index(start_case_id)
        except ValueError as exc:
            raise SpikeError("pilot segment starts at an unknown case") from exc
        if ids != expected_ids[start_index : start_index + len(ids)]:
            raise SpikeError("pilot segment is not a consecutive pinned corpus range")
        if end_case_id != ids[-1]:
            raise SpikeError("pilot segment end case does not match its results")
        failure_ids = [item["case_id"] for item in failures]
        attempted_ids = ids + failure_ids
        if (
            failure_ids
            and failure_ids
            != expected_ids[start_index + len(ids) : start_index + len(ids) + 1]
        ):
            raise SpikeError("pilot segment failure is not the next pinned case")
        hash_map = report.get("request_sha256_by_case")
        if not isinstance(hash_map, dict) or set(hash_map) != set(attempted_ids):
            raise SpikeError("pilot segment request hash index is invalid")
        for case_id in attempted_ids:
            if hash_map[case_id] != pinned_hashes[case_id]:
                raise SpikeError("pilot segment request hash is not approved")
        segment_model_versions: set[str] = set()
        for case_id, result in zip(ids, results, strict=True):
            expected_hash = pinned_hashes[case_id]
            case = cases[expected_ids.index(case_id)]
            model_version = _validate_result(
                result,
                case=case,
                taxonomy=taxonomy,
                expected_request_hash=expected_hash,
            )
            segment_model_versions.add(model_version)
        if len(segment_model_versions) != 1:
            raise SpikeError("resolved Jev model version changed within a segment")
        report["_normalized_start_case_id"] = start_case_id
        report["_normalized_end_case_id"] = end_case_id
        report["_normalized_transport_provenance"] = transport_provenance
        report["_normalized_ledger_start_count"] = ledger_start_count
        report["_normalized_ledger_end_count"] = ledger_end_count
        report["_normalized_attempted_ids"] = attempted_ids
        report["_normalized_failures"] = failures
        reports.append((resolved, report, is_historical_seed))

    # Flatten only after every segment has passed schema and hash checks.
    rows: dict[str, JsonObject] = {}
    source_hashes: dict[Path, str] = {}
    model_versions: set[str] = set()
    segments: list[JsonObject] = []
    common_current_code_hashes: tuple[str, str] | None = None
    ledger_cursor = 0
    attempted_case_ids: list[str] = []
    failures: list[JsonObject] = []
    current_attempted_calls = 0
    current_successful_calls = 0
    for path, report, is_historical_seed in reports:
        if path not in source_hashes:
            source_hashes[path] = _sha256(path)
        code_hashes = (report["client_sha256"], report["runner_sha256"])
        if not is_historical_seed:
            if common_current_code_hashes is None:
                common_current_code_hashes = code_hashes
            elif code_hashes != common_current_code_hashes:
                raise SpikeError(
                    "current pilot segments use different source revisions"
                )
        if report["_normalized_ledger_start_count"] != ledger_cursor:
            raise SpikeError("pilot segments do not continue the cumulative ledger")
        ledger_cursor = report["_normalized_ledger_end_count"]
        attempted_case_ids.extend(report["_normalized_attempted_ids"])
        failures.extend(report["_normalized_failures"])
        if not is_historical_seed:
            current_attempted_calls += report["attempted_calls"]
            current_successful_calls += report["successful_calls"]
        model_versions.update(row["model_version"] for row in report["results"])
        segment_ids = [row["case_id"] for row in report["results"]]
        for row in report["results"]:
            if row["case_id"] in rows:
                raise SpikeError("duplicate case across pilot segments")
            rows[row["case_id"]] = row
        segments.append(
            {
                "start_at_case_id": report["_normalized_start_case_id"],
                "end_at_case_id": report["_normalized_end_case_id"],
                "calls": len(segment_ids),
                "attempted_calls": len(report["_normalized_attempted_ids"]),
                "failed_case_ids": [
                    failure["case_id"] for failure in report["_normalized_failures"]
                ],
                "transport_provenance": report["_normalized_transport_provenance"],
                "source_revision": {
                    "client_sha256": report["client_sha256"],
                    "runner_sha256": report["runner_sha256"],
                },
                "cumulative_ledger_range": [
                    report["_normalized_ledger_start_count"],
                    report["_normalized_ledger_end_count"],
                ],
            }
        )
    if len(model_versions) != 1:
        raise SpikeError("resolved Jev model version changed between pilot segments")
    if attempted_case_ids != expected_ids[: len(attempted_case_ids)]:
        raise SpikeError("pilot segment attempts skip or repeat a pinned baseline case")

    ordered_results = [rows[case_id] for case_id in expected_ids if case_id in rows]
    metrics = evaluate(all_cases, ordered_results, taxonomy)
    if not ordered_results:
        raise SpikeError("pilot segments contain no validated provider results")
    metadata = expected_metadata or {}
    request_hashes = {case_id: pinned_hashes[case_id] for case_id in attempted_case_ids}
    current_transports = [
        report["_normalized_transport_provenance"]
        for _, report, is_historical_seed in reports
        if not is_historical_seed
    ]
    official_transport_only = bool(current_transports) and all(
        provenance == "official_polza_https" for provenance in current_transports
    )
    if not official_transport_only:
        metrics = None
    complete = bool(metrics and metrics["evaluation_complete"] and not failures)
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        **metadata,
        "mode": "live_synthetic_pilot_aggregate",
        "model_version": next(iter(model_versions)),
        "attempted_calls": current_attempted_calls + 2,
        "current_attempted_calls": current_attempted_calls,
        "current_successful_calls": current_successful_calls,
        "current_failed_calls": len(failures),
        "historical_attempted_calls": 2,
        "historical_failed_calls": 1,
        "failed_calls": len(failures) + 1,
        "successful_calls": len(ordered_results),
        "control_calls": 0,
        "controls": {},
        "failures": failures,
        "historical_failures": [_validate_historical_legacy_failure()],
        "missing_result_case_ids": [
            case_id for case_id in expected_ids if case_id not in rows
        ],
        "request_sha256_by_case": request_hashes,
        "results": ordered_results,
        "segments": segments,
        "source_reports": [
            {
                "file": path.name,
                "sha256": digest,
                "kind": "historical_pinned_smoke"
                if path.resolve() == HISTORICAL_SMOKE_PATH.resolve()
                else "current_segment",
            }
            for path, digest in source_hashes.items()
        ],
        "cumulative_attempts": ledger_cursor,
        "known_total_attempts": ledger_cursor + 1,
        "quality_metrics_status": (
            "NOT_MEASURED_CUSTOM_TRANSPORT"
            if not official_transport_only
            else "COMPUTED_FULL_BASELINE_PROVENANCE_UNATTESTED"
            if complete
            else "COMPUTED_PARTIAL_BASELINE_PROVENANCE_UNATTESTED"
        ),
        "metrics": metrics,
        "known_successful_response_cost_rub": (
            metrics["token_usage"]["cost_rub"] if metrics is not None else None
        ),
        "failed_attempt_cost_status": "UNKNOWN_POSSIBLY_BILLED",
        "gold_label_status": "single-annotator synthetic baseline; metrics are conditional on draft labels",
        "provider_response_authenticity": "NOT_CRYPTOGRAPHICALLY_ATTESTED",
        "note": "Metrics are computed only when every current segment declares the official Polza HTTPS transport and use only successfully validated responses; failed cases are excluded and may create selection bias. The original baseline is synthetic and small, with single-author draft labels that have not been independently adjudicated. These descriptive metrics are neither independent validation nor calibration and do not prove production quality. Segment JSON and the local cumulative-attempt ledger can be modified/reset by the local user; Polza provides no signed response proof in this flow, so API origin is not cryptographically attested. One case is a pinned historical artifact from an earlier client revision; current staged segments record their source hashes. The observed segment ledger records 49 attempts; one additional failed legacy TypeSafe POST is separately pinned, bringing known live attempts to 50. Cost is reported only for successful response usage; failed requests may also have been billed. No raw articles, prompts, provider bodies, credentials, or raw error details are included.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports", nargs="+", help="sanitized segment JSON files under spike/T08"
    )
    parser.add_argument(
        "--output", required=True, help="aggregate output path under spike/T08"
    )
    args = parser.parse_args()
    try:
        output_path = _inside_spike(Path(args.output))
        if output_path.exists():
            raise SpikeError("output path already exists")
        report = aggregate_reports([Path(path) for path in args.reports])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"AGGREGATE={output_path.relative_to(SPIKE_DIR)}")
        print(f"CASES={report['successful_calls']}")
        print(f"MODEL={report['model_version']}")
        print(
            "COST_RUB="
            + (
                str(report["metrics"]["token_usage"]["cost_rub"])
                if report["metrics"] is not None
                else "NOT_MEASURED"
            )
        )
        return 0
    except (OSError, ValueError, SpikeError) as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
