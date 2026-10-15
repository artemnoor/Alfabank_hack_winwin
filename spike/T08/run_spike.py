"""Run offline checks or an explicitly requested synthetic-only Jev pilot."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jev_spike import (
    CORPUS_PATH,
    DEFAULT_MODEL,
    SPIKE_DIR,
    SUPPORTED_MODEL_ALIASES,
    TAXONOMY_PATH,
    JevClient,
    LiveRequestError,
    SpikeError,
    approved_request_hashes,
    evaluate,
    https_transport,
    interpret_response,
    load_verified_inputs,
    make_request,
    request_hash,
    taxonomy_hash,
)
from live_ledger import AttemptLedger
from stable_hash import sha256_text_file

_OFFICIAL_JEV_CLIENT_CLASS = JevClient


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _sha256_file(path: Path) -> str:
    return sha256_text_file(path)


def _safe_failure(case_id: str, error: Exception) -> dict[str, str]:
    code = str(error)
    allowed = {
        "timeout",
        "connection_error",
        "transport_error",
        "redirect_refused",
        "unapproved_endpoint",
        "invalid_json_response",
        "invalid_response_body",
        "response_too_large",
        "invalid_provider_response",
        "request_already_in_live_ledger",
        "cumulative_live_call_limit_reached",
        "live_attempt_ledger_invalid",
    }
    if code in {
        "Jev returned an invalid response shape",
        "Jev response has an invalid resolved model version",
        "Jev response question set does not match the request",
        "Jev returned an invalid Choice answer",
        "Jev returned an unknown or invalid topic Choice",
        "Jev Choice probabilities do not match the allowed taxonomy",
        "Jev returned an invalid Choice probability",
        "Jev Choice probabilities do not sum to one",
        "Jev Choice label is not a maximum-probability option",
        "Jev Choice needs at least two probability options",
        "Jev returned an invalid Noul answer",
        "Jev returned invalid usage metadata",
    }:
        allowed_code = "invalid_provider_response"
    elif code.startswith("http_status_") and code[12:].isdigit():
        allowed_code = code
    else:
        allowed_code = code if code in allowed else "sanitized_request_error"
    return {"case_id": case_id, "error": allowed_code}


def offline_report(
    taxonomy: dict[str, Any], corpus: dict[str, Any], cases: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "mode": "offline_validation",
        "taxonomy_id": taxonomy["id"],
        "taxonomy_version": taxonomy["version"],
        "topic_count": len(taxonomy["topics"]),
        "business_event_count": len(taxonomy["events"]),
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": _sha256_file(CORPUS_PATH),
        "taxonomy_sha256_raw": _sha256_file(TAXONOMY_PATH),
        "corpus_case_count": len(cases),
        "non_empty_news_count": sum(
            bool(case["title"].strip() or case["text"].strip()) for case in cases
        ),
        "empty_local_validation_count": sum(
            case["expected_status"] == "no_content" for case in cases
        ),
        "single_event_cases": sum(
            case["case_type"] == "single_event" for case in cases
        ),
        "multi_event_cases": sum(case["case_type"] == "multi_event" for case in cases),
        "uncertain_or_negative_cases": sum(
            case["case_type"] in {"ambiguous_or_speculative", "negation_or_rumor"}
            for case in cases
        ),
        "classifier_calls": 0,
        "live_model_quality": "not_measured",
    }


def run_live(
    args: argparse.Namespace,
    taxonomy: dict[str, Any],
    corpus: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    # The project account is hosted by Polza AI; do not fall back to direct TypeSafe keys.
    api_key = os.environ.get("POLZA_AI_API_KEY", "")
    if not 1 <= args.max_calls <= 50:
        raise SpikeError("--max-calls must be between 1 and 50")
    pinned_taxonomy, pinned_corpus, pinned_cases = load_verified_inputs()
    if taxonomy != pinned_taxonomy or corpus != pinned_corpus or cases != pinned_cases:
        raise SpikeError("live mode requires the exact pinned synthetic inputs")
    client = JevClient(
        api_key,
        allowed_request_hashes=approved_request_hashes(
            cases, taxonomy, model=args.model
        ),
    )
    all_news_cases = [case for case in cases if case["expected_status"] != "no_content"]
    case_ids = [case["id"] for case in all_news_cases]
    start_at = getattr(args, "start_at", None)
    if start_at is None:
        start_index = 0
    else:
        try:
            start_index = case_ids.index(start_at)
        except ValueError as exc:
            raise SpikeError(
                "--start-at must name a non-empty pinned corpus case"
            ) from exc
    news_cases = all_news_cases[start_index : start_index + args.max_calls]
    if not news_cases:
        raise SpikeError("--start-at is past the end of the pinned corpus")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    attempted = 0
    request_hashes: dict[str, str] = {}
    ledger_path_value = getattr(args, "ledger_path", None)
    ledger = AttemptLedger(Path(ledger_path_value) if ledger_path_value else None)
    ledger_start_count = ledger.count()
    ledger_end_count = ledger_start_count
    used_official_transport = (
        type(client) is _OFFICIAL_JEV_CLIENT_CLASS
        and getattr(client, "_transport", None) is https_transport
    )
    for case in news_cases:
        try:
            request = make_request(case, taxonomy, model=args.model)
            request_hashes[case["id"]] = request_hash(request)
            before_count, after_count = ledger.reserve(
                case["id"], request_hashes[case["id"]]
            )
            if attempted == 0:
                ledger_start_count = before_count
            ledger_end_count = after_count
            attempted += 1
            response = client.classify(request)
            result = interpret_response(case, response, request, taxonomy).result
            result["request_sha256"] = request_hashes[case["id"]]
            results.append(result)
            print(
                f"LIVE case={case['id']} status={result['classification_status']} model={result['model_version']}"
            )
        except (SpikeError, LiveRequestError) as exc:
            failures.append(_safe_failure(case["id"], exc))
            print(
                f"LIVE case={case['id']} error={failures[-1]['error']}", file=sys.stderr
            )
            # One failure ends the run to avoid repeated billed requests on a broken route.
            break
    complete_case_coverage = not failures and len(results) == len(all_news_cases)
    measurement_eligible = complete_case_coverage and used_official_transport
    if measurement_eligible:
        quality_metrics_status = "MEASURED_FULL_BASELINE"
    elif complete_case_coverage:
        quality_metrics_status = "NOT_MEASURED_CUSTOM_TRANSPORT"
    else:
        quality_metrics_status = "NOT_MEASURED_INCOMPLETE_RUN"
    report: dict[str, Any] = {
        "mode": "live_synthetic_pilot",
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "endpoint_host": "polza.ai",
        "endpoint_path": "/api/v1/systemone",
        "corpus_id": corpus["corpus_id"],
        "taxonomy_id": taxonomy["id"],
        "taxonomy_version": taxonomy["version"],
        "taxonomy_hash": taxonomy_hash(taxonomy),
        "taxonomy_sha256_raw": _sha256_file(TAXONOMY_PATH),
        "corpus_sha256": _sha256_file(CORPUS_PATH),
        "client_sha256": _sha256_file(Path(__file__).with_name("jev_spike.py")),
        "runner_sha256": _sha256_file(Path(__file__)),
        "requested_model_id": args.model,
        "max_calls_per_invocation": args.max_calls,
        "start_at_case_id": news_cases[0]["id"],
        "end_at_case_id": results[-1]["case_id"] if results else None,
        "transport_provenance": "official_polza_https"
        if used_official_transport
        else "custom_or_test_transport",
        "ledger_start_count": ledger_start_count,
        "ledger_end_count": ledger_end_count,
        "attempted_calls": attempted,
        "successful_calls": len(results),
        "control_calls": 0,
        "controls": {},
        "failures": failures,
        "request_sha256_by_case": request_hashes,
        "results": results,
        "provider_response_authenticity": "NOT_CRYPTOGRAPHICALLY_ATTESTED",
        "quality_metrics_status": quality_metrics_status,
        "metrics": evaluate(cases, results, taxonomy) if measurement_eligible else None,
        "note": "Synthetic-only run; aggregate quality metrics are withheld until all 49 non-empty baseline cases complete. Raw articles, prompts, provider response bodies, credentials, and exception details are not saved.",
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        Path(args.output)
        if args.output
        else SPIKE_DIR / "results" / f"jev-live-pilot-{stamp}.json"
    )
    if not output_path.is_absolute():
        output_path = SPIKE_DIR / output_path
    output_path = output_path.resolve()
    if not output_path.is_relative_to(SPIKE_DIR.resolve()):
        raise SpikeError("report path must stay inside spike/T08")
    if output_path.exists():
        raise SpikeError("report path already exists; choose a new filename")
    _write_json(output_path, report)
    print(
        f"REPORT file={output_path.relative_to(SPIKE_DIR) if output_path.is_relative_to(SPIKE_DIR) else output_path.name}"
    )
    if failures:
        print("PILOT=INCOMPLETE")
    elif len(results) != len(all_news_cases):
        print("PILOT=PARTIAL_BY_CALL_LIMIT")
    else:
        print("PILOT=COMPLETE")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="send only the pinned synthetic corpus to the official Polza AI Jev API",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=sorted(SUPPORTED_MODEL_ALIASES),
        help="approved Polza AI Jev model id; exact resolved model version is recorded",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=1,
        help="per-invocation live-call cap (default 1; hard maximum 50)",
    )
    parser.add_argument(
        "--start-at",
        help="start at this exact non-empty case id from the pinned baseline (for staged pilots)",
    )
    parser.add_argument("--output", help="optional sanitized JSON report path")
    args = parser.parse_args()
    try:
        taxonomy, corpus, cases = load_verified_inputs()
        if args.live:
            report = run_live(args, taxonomy, corpus, cases)
            return 1 if report["failures"] else 0
        report = offline_report(taxonomy, corpus, cases)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (SpikeError, OSError, ValueError) as exc:
        # Error strings are locally authored safe codes/messages, never raw provider text.
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
