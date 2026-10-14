"""Create a hash-pinned manifest for the experimental Policy v2.1 handoff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stable_hash import sha256_text_bytes

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "visualization" / "policy-v2-results.json"
CORPUS = ROOT / "corpus.json"
TAXONOMY = ROOT / "taxonomy.json"
AGGREGATE = ROOT / "results" / "jev-live-aggregate-20261014-v4.json"
PY_POLICY = ROOT / "visualization" / "policy_v2.py"
JS_POLICY = ROOT / "visualization" / "app.js"
OUTPUT = ROOT / "POLICY_V2.1.manifest.json"


def _sha256(raw: bytes) -> str:
    return sha256_text_bytes(raw)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object at {path}")
    return value


def build_manifest() -> dict[str, Any]:
    result = _read(RESULTS)
    corpus = _read(CORPUS)
    comparison = result["policy_comparison"]
    policy = comparison["policy_v2"]
    if result.get("policy_version") != "2.1.0-spike":
        raise ValueError("saved calculation result is not Policy v2.1")
    if result.get("generated_from_saved_outputs_only") is not True:
        raise ValueError("policy result must only use stored Jev outputs")
    expected_sources = {
        "corpus": _sha256(CORPUS.read_bytes()),
        "taxonomy": _sha256(TAXONOMY.read_bytes()),
        "aggregate": _sha256(AGGREGATE.read_bytes()),
    }
    if result.get("source_hashes") != expected_sources:
        raise ValueError("saved policy report source hashes do not match inputs")
    if (
        comparison["denominator"],
        policy["stories_with_candidates"],
        policy["candidate_event_count"],
    ) != (45, 32, 40):
        raise ValueError("saved Policy v2.1 headline counts changed")
    event_metrics = policy["event_output_metrics"]
    if (event_metrics["tp"], event_metrics["fp"], event_metrics["fn"]) != (34, 6, 7):
        raise ValueError("saved Policy v2.1 disagreement counts changed")
    missing = [
        case
        for case in corpus["cases"]
        if case.get("text", "").strip()
        and (
            case["id"] not in policy["cases"]
            or policy["cases"][case["id"]].get("missing_result")
        )
    ]
    if len(missing) != 4:
        raise ValueError("the four missing saved responses must remain explicit")

    code_files = {
        "python_policy": PY_POLICY,
        "browser_policy_and_presentation": JS_POLICY,
    }
    return {
        "schema_version": "t08-policy-freeze-manifest-v1",
        "policy_version": "2.1.0-spike",
        "freeze_status": "frozen_for_experimental_handoff_only",
        "runtime_integration": False,
        "public_contract_changed": False,
        "new_jev_api_requests": 0,
        "source_hashes": expected_sources,
        "implementation_hashes": {
            name: _sha256(path.read_bytes()) for name, path in code_files.items()
        },
        "saved_policy_report_sha256": _sha256(RESULTS.read_bytes()),
        "thresholds": {
            "candidate_positive_at_or_above": 0.8,
            "noul_negative_at_or_below": 0.2,
            "noul_positive_at_or_above": 0.8,
            "insufficient_evidence_hold_at_or_above": 0.8,
            "unlisted_separate_task_at_or_above": 0.8,
            "boundary_semantics": "inclusive",
        },
        "routing_invariants": {
            "preserve_choice_and_all_event_scores": True,
            "positive_events_are_unconfirmed_candidates": True,
            "insufficient_evidence_holds_only_existing_candidates": True,
            "unlisted_task_does_not_block_known_candidates": True,
            "choice_confidence_does_not_block_candidates": True,
            "event_abstain_does_not_block_other_candidates": True,
            "missing_result_is_not_empty_classification": True,
        },
        "observed_saved_run": {
            "nonempty_input_count": 49,
            "saved_answer_count": comparison["denominator"],
            "missing_answer_count": len(missing),
            "candidate_bearing_stories": policy["stories_with_candidates"],
            "candidate_event_count": policy["candidate_event_count"],
            "stories_with_review": policy["stories_with_any_review"],
            "tp_fp_fn_against_preliminary_labels": {
                "tp": event_metrics["tp"],
                "fp": event_metrics["fp"],
                "fn": event_metrics["fn"],
            },
        },
        "gold_status": "preliminary_single_author_unadjudicated",
        "known_semantic_limit": (
            "Taxonomy v0.3 insufficient_evidence combines primary-topic and event "
            "uncertainty; it may conservatively hold an event candidate for topic-only doubt."
        ),
        "candidate_transport": "released event codes may be extraction hints only; never facts",
        "manifest_path": "spike/T08/POLICY_V2.1.manifest.json",
        "policy_spec_path": "spike/T08/POLICY_V2.1.md",
    }


def write_manifest() -> dict[str, Any]:
    manifest = build_manifest()
    OUTPUT.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    manifest = write_manifest()
    print(f"POLICY={manifest['policy_version']} STATUS={manifest['freeze_status']}")
    print(f"POLICY_REPORT_SHA256={manifest['saved_policy_report_sha256']}")
