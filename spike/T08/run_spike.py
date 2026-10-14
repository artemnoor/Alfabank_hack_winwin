"""Run offline checks or an explicitly requested synthetic-only Jev pilot."""

from __future__ import annotations

import argparse
import hashlib
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
    interpret_response,
    load_verified_inputs,
    make_request,
    request_hash,
    taxonomy_hash,
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_failure(case_id: str, error: Exception) -> dict[str, str]:
    code = str(error)
    allowed = {
        "timeout",
        "connection_error",
        "redirect_refused",
        "unapproved_endpoint",
        "invalid_json_response",
        "invalid_response_body",
        "response_too_large",
    }
    if code.startswith("http_status_") and code[12:].isdigit():
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
    # TYPESAFE_API_KEY is the variable used by TypeSafe's official examples.
    api_key = os.environ.get("TYPESAFE_API_KEY", "")
    if not 1 <= args.max_calls <= 50:
        raise SpikeError("--max-calls must be between 1 and 50")
    client = JevClient(
        api_key,
        allowed_request_hashes=approved_request_hashes(
            cases, taxonomy, model=args.model
        ),
    )
    all_news_cases = [case for case in cases if case["expected_status"] != "no_content"]
    news_cases = list(all_news_cases)
    if args.max_calls < len(news_cases):
        news_cases = news_cases[: args.max_calls]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    attempted = 0
    request_hashes: dict[str, str] = {}
    for case in news_cases:
        attempted += 1
        try:
            request = make_request(case, taxonomy, model=args.model)
            request_hashes[case["id"]] = request_hash(request)
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
    report: dict[str, Any] = {
        "mode": "live_synthetic_pilot",
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "endpoint_host": "api.typesafe.ai",
        "endpoint_path": "/v1/systemone",
        "corpus_id": corpus["corpus_id"],
        "taxonomy_id": taxonomy["id"],
        "taxonomy_version": taxonomy["version"],
        "taxonomy_hash": taxonomy_hash(taxonomy),
        "taxonomy_sha256_raw": _sha256_file(TAXONOMY_PATH),
        "corpus_sha256": _sha256_file(CORPUS_PATH),
        "client_sha256": _sha256_file(Path(__file__).with_name("jev_spike.py")),
        "runner_sha256": _sha256_file(Path(__file__)),
        "requested_model_alias": args.model,
        "attempted_calls": attempted,
        "successful_calls": len(results),
        "control_calls": 0,
        "controls": {},
        "failures": failures,
        "request_sha256_by_case": request_hashes,
        "results": results,
        "metrics": evaluate(cases, results, taxonomy) if results else None,
        "note": "Synthetic-only pilot; raw articles, prompts, provider response bodies, credentials, and exception details are not saved.",
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
        help="send only the embedded synthetic corpus to the official TypeSafe API",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=sorted(SUPPORTED_MODEL_ALIASES),
        help="approved TypeSafe Jev alias; exact resolved version is recorded",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=50,
        help="hard cap for live calls; one call per synthetic news case",
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
