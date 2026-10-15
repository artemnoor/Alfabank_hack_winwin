"""Build a redacted, reproducible summary from saved Polza pilot artifacts."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

RESULTS_DIR = Path(__file__).with_name("results")
OUTPUT_PATH = RESULTS_DIR / "deepseek-v4-flash-live-pilot-20261015-summary.json"
PREFLIGHT_PATH = RESULTS_DIR / "polza-models-preflight-20261015.json"
RUN_GLOB = "deepseek-v4-flash-live-pilot-20261015*.json"


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("pilot artifact must be an object")
    return value


def build_summary() -> dict:
    preflight = _load_json(PREFLIGHT_PATH)
    records = []
    current_hash = None
    current_allowlist = None
    current_attempts = []
    for path in sorted(RESULTS_DIR.glob(RUN_GLOB)):
        if path == OUTPUT_PATH or path == PREFLIGHT_PATH:
            continue
        run = _load_json(path)
        prompt_hash = run.get("prompt_sha256")
        allowlist_id = run.get("allowlist_id")
        for row in run.get("records", []):
            safe_record = {
                "run_id": run.get("run_id"),
                "case_id": row.get("case_id"),
                "candidate_code": row.get("jev_candidate_code"),
                "status": row.get("pipeline_status"),
                "safe_failure_code": row.get("safe_failure_code"),
                "latency_ms": row.get("latency_ms"),
                "token_usage": row.get("token_usage"),
                "provider_cost_rub": row.get("provider_cost_rub"),
            }
            records.append(safe_record)
            if prompt_hash:
                if current_hash is None:
                    current_hash = prompt_hash
                    current_allowlist = allowlist_id
                if prompt_hash == current_hash and allowlist_id == current_allowlist:
                    current_attempts.append(safe_record)

    costs = [
        row["provider_cost_rub"]
        for row in records
        if isinstance(row.get("provider_cost_rub"), (int, float))
    ]
    latencies = [
        row["latency_ms"] for row in records if isinstance(row.get("latency_ms"), int)
    ]
    current_successes = sum(row["status"] == "extracted" for row in current_attempts)
    result = {
        "report_version": "1.0.0",
        "provider": "Polza AI",
        "model_id": "deepseek/deepseek-v4-flash",
        "endpoint": "https://polza.ai/api/v1/chat/completions",
        "model_catalog_preflight": preflight,
        "request_budget": {
            "authorized": 10,
            "used": len(records),
            "remaining": 10 - len(records),
        },
        "aggregate": {
            "attempts": len(records),
            "successful_extractions": sum(
                row["status"] == "extracted" for row in records
            ),
            "safely_rejected_or_unavailable": sum(
                row["status"] != "extracted" for row in records
            ),
            "jev_requests": 0,
            "known_cost_rub": round(sum(costs), 8),
            "unknown_cost_attempts": len(records) - len(costs),
            "mean_latency_ms": round(statistics.mean(latencies), 2)
            if latencies
            else None,
            "median_latency_ms": statistics.median(latencies) if latencies else None,
        },
        "current_prompt_version": {
            "prompt_sha256": current_hash,
            "allowlist_id": current_allowlist,
            "attempts": len(current_attempts),
            "successful_extractions": current_successes,
            "safe_rejections": len(current_attempts) - current_successes,
            "model_quality_status": "not_measured",
            "reason": "No independently human-reviewed gold labels exist for extracted facts.",
        },
        "privacy": {
            "api_key_saved": False,
            "raw_prompts_saved": False,
            "raw_provider_responses_saved": False,
            "source_articles_saved": False,
            "validated_t09_dtos_saved_in_run_artifacts": True,
        },
        "records": records,
    }
    return result


def main() -> int:
    summary = build_summary()
    temporary = OUTPUT_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(OUTPUT_PATH)
    print(
        "attempts={attempts} extracted={successful_extractions} known_cost_rub={known_cost_rub}".format(
            **summary["aggregate"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
