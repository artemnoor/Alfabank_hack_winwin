"""Run one bounded, explicitly authorized DeepSeek extraction pilot.

The script uses only ten fixed synthetic cases with saved Jev outputs. It never
calls Jev, never retries, and writes validated DTOs plus safe metadata rather
than prompts, source articles, or raw provider responses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
T08_DIR = ROOT / "spike" / "T08"
sys.path[:0] = [
    str(ROOT / "packages" / "contracts" / "src"),
    str(T08_DIR),
    str(T08_DIR / "visualization"),
]

from alfalab_contracts import (  # noqa: E402
    PreparedMaterial,
    Provenance,
    RawMaterial,
    SpanMap,
)
from fact_extraction import (  # noqa: E402
    ExtractionContext,
    run_t08_to_t09,
)
from fact_extraction.errors import LiveCallsDisabled  # noqa: E402
from fact_extraction.allowlist import load_approved_pilot_case  # noqa: E402
from fact_extraction.binding import (  # noqa: E402
    candidates_from_t08,
    load_experiment_binding,
)
from fact_extraction.polza import (  # noqa: E402
    LiveCallAuthorization,
    PolzaDeepSeekFlash,
)
from policy_v2 import evaluate_result  # noqa: E402

MAX_PILOT_REQUESTS = 10
PILOT_CASES = (
    ("nb-003", "production_operational_disruption"),
    ("nb-004", "price_cost_change"),
    ("nb-006", "sanctions"),
    ("nb-009", "labor_workforce_event"),
    ("nb-011", "investment_capacity_change"),
    ("nb-012", "product_recall_quality_safety"),
    ("nb-013", "cyber_security_incident"),
    ("nb-014", "environment_disaster_impact"),
    ("nb-016", "corporate_transaction_restructuring"),
    ("nb-033", "supply_chain_disruption"),
)
RESULT_PATH = Path(__file__).with_name("results") / (
    "deepseek-v4-flash-live-pilot-20261015.json"
)


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_dataset() -> tuple[dict[str, dict], dict[str, dict], dict[str, Any]]:
    pilot_dir = T08_DIR / "experiments" / "jev-expanded-pilot-v1"
    news = json.loads((pilot_dir / "news.json").read_text(encoding="utf-8"))
    live_results = json.loads(
        (pilot_dir / "live-results.json").read_text(encoding="utf-8")
    )
    taxonomy = json.loads((T08_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    return (
        {row["id"]: row for row in news["cases"]},
        {row["case_id"]: row for row in live_results["results"]},
        taxonomy,
    )


def preflight_plan(*, max_requests: int) -> list[tuple[str, str, dict, dict, dict]]:
    """Resolve the fixed plan and validate every case before spending anything."""
    if not 1 <= max_requests <= MAX_PILOT_REQUESTS:
        raise ValueError("pilot request limit must be between 1 and 10")
    news_by_id, result_by_id, taxonomy = _load_dataset()
    binding = load_experiment_binding()
    plan = []
    seen_case_ids: set[str] = set()
    seen_codes: set[str] = set()
    for case_id, expected_code in PILOT_CASES[:max_requests]:
        if case_id in seen_case_ids or expected_code in seen_codes:
            raise ValueError("pilot manifest contains duplicate case or event code")
        case = news_by_id[case_id]
        classification = result_by_id[case_id]
        approved = load_approved_pilot_case(case_id, case["text"])
        if classification != approved.classification:
            raise ValueError("saved Jev result differs from the pinned allowlist")
        decision = evaluate_result(classification, taxonomy)
        if decision["candidate_codes"] != [expected_code]:
            raise ValueError("saved Jev policy no longer releases the fixed candidate")
        candidate = candidates_from_t08(decision["candidate_codes"], taxonomy, binding)[
            0
        ]
        plan.append((case_id, expected_code, case, classification, taxonomy))
        seen_case_ids.add(case_id)
        seen_codes.add(candidate.code)
    return plan


def _prepared_material(case: dict[str, Any], recorded_at: str) -> PreparedMaterial:
    text = case["text"]
    digest = _sha256_text(text)
    raw = RawMaterial(
        material_id=case["id"],
        source_id=None,
        source_url=None,
        title=case["title"],
        text=text,
        published_at=None,
        collected_at=recorded_at,
        content_hash=digest,
        language="ru",
        provenance=Provenance(
            origin="synthetic",
            source_refs=[],
            input_statement_refs=[],
            producer_run_id=None,
            derivation_method=None,
            evidence_refs=[],
            origin_verified=True,
        ),
    )
    return PreparedMaterial(
        material=raw,
        raw_hash=digest,
        prepared_hash=digest,
        quality="valid",
        span_map=[
            SpanMap(
                prepared_start=0,
                prepared_end=len(text),
                raw_start=0,
                raw_end=len(text),
            )
        ],
        warnings=[],
    )


def _write_report(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def run_pilot(
    *,
    max_requests: int,
    authorization: LiveCallAuthorization | None = None,
) -> dict[str, Any]:
    if (
        authorization is None
        or authorization.approved_by_user is not True
        or authorization.max_requests != max_requests
    ):
        raise LiveCallsDisabled("live_calls_disabled_pending_user_approval")
    plan = preflight_plan(max_requests=max_requests)
    path = RESULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError("pilot artifact already exists; refusing duplicate spend")
    extractor = PolzaDeepSeekFlash.from_windows_environment(authorization=authorization)
    try:
        with path.open("x", encoding="utf-8"):
            pass
    except FileExistsError:
        raise RuntimeError(
            "pilot artifact already exists; refusing duplicate spend"
        ) from None

    started_at = datetime.now(UTC).isoformat()
    report: dict[str, Any] = {
        "run_id": "deepseek-v4-flash-live-pilot-20261015",
        "started_at_utc": started_at,
        "provider": "Polza AI",
        "model_id": "deepseek/deepseek-v4-flash",
        "endpoint": "https://polza.ai/api/v1/chat/completions",
        "input_source": "exact-hash-allowlisted-synthetic-pilot",
        "jev_source": "saved-live-jev-expanded-pilot-v1",
        "jev_requests_made": 0,
        "request_limit": max_requests,
        "status": "in_progress",
        "records": [],
        "raw_prompts_saved": False,
        "raw_provider_responses_saved": False,
        "source_articles_saved": False,
    }
    _write_report(path, report)
    binding = load_experiment_binding()
    for call_no, (case_id, expected_code, case, classification, taxonomy) in enumerate(
        plan, start=1
    ):
        recorded_at = datetime.now(UTC).isoformat()
        prepared = _prepared_material(case, recorded_at)
        before = extractor.calls_made
        result = run_t08_to_t09(
            prepared=prepared,
            classification=classification,
            taxonomy=taxonomy,
            extractor=extractor,
            binding=binding,
            context=ExtractionContext(
                case_id=case_id,
                recorded_at=recorded_at,
                origin="synthetic",
                origin_verified=True,
                source_refs=[],
                producer_run_id=None,
            ),
        )
        attempted = extractor.calls_made - before
        record = {
            "call_no": call_no,
            "case_id": case_id,
            "jev_candidate_code": expected_code,
            "pipeline_status": result.status,
            "calls_attempted": attempted,
            "latency_ms": extractor.last_elapsed_ms if attempted else None,
            "token_usage": extractor.last_usage if attempted else None,
            "provider_cost_rub": extractor.last_cost_rub if attempted else None,
            "safe_failure_code": result.safe_failure_code,
            "validated_output": (
                result.output.model_dump(mode="json")
                if result.status.startswith("extracted") and result.output
                else None
            ),
        }
        report["records"].append(record)
        report["total_calls_attempted"] = extractor.calls_made
        report["successful_extractions"] = sum(
            row["pipeline_status"].startswith("extracted") for row in report["records"]
        )
        report["status"] = (
            "complete"
            if len(report["records"]) == max_requests
            and report["successful_extractions"] == max_requests
            else "incomplete_stopped_after_first_failure"
        )
        _write_report(path, report)
        print(
            f"{call_no}/{max_requests} {case_id} {expected_code} "
            f"{result.status} calls={attempted} "
            f"latency_ms={record['latency_ms']} usage={record['token_usage']}"
        )
        # A failed request or invalid model output is a stop condition. Never
        # spend the rest of the pilot repeating a failing provider/schema path.
        if result.status != "extracted" or attempted != 1:
            if result.status == "extracted_with_unlisted_review" and attempted == 1:
                continue
            break
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    _write_report(path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--approve-paid-live",
        action="store_true",
        help="explicitly authorize this one paid synthetic pilot",
    )
    parser.add_argument("--max-requests", type=int, default=MAX_PILOT_REQUESTS)
    args = parser.parse_args(argv)
    if not args.approve_paid_live:
        parser.error("live calls require --approve-paid-live")
    try:
        report = run_pilot(
            max_requests=args.max_requests,
            authorization=LiveCallAuthorization(
                approved_by_user=True,
                max_requests=args.max_requests,
            ),
        )
    except Exception as exc:
        # The message is deliberately not printed or persisted: transport and
        # provider exceptions can include secrets or echoed article content.
        print(f"pilot stopped safely: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(
        f"status={report['status']} calls={report.get('total_calls_attempted', 0)} "
        f"artifact={RESULT_PATH.relative_to(ROOT)}"
    )
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
