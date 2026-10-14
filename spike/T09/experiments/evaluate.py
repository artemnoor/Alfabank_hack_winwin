"""Compute reproducible, explicitly provisional T09 case metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t09_events.resolution import propose_resolution
from t09_events.scenarios import EXPECTED_DATASET_VERSION, EXPECTED_DATA_HASH, input_from_fixture, load_cases


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "spike" / "T09" / "results" / "metrics-v1.json"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def calculate() -> dict[str, Any]:
    cases = load_cases()
    decisions_by_case: dict[str, list[str]] = {}
    focus_by_case: dict[str, str] = {}
    expected_by_case: dict[str, str] = {}
    per_case = []

    for case in cases:
        request = input_from_fixture(case)
        proposal = propose_resolution(request).proposal
        case_id = case["fixture_id"].removeprefix("fixture-t09-")
        expected = case["provisional_expectation"]
        focus_id = case["input_data"]["focus_mention_id"]
        focus = next(decision for decision in proposal.decisions if focus_id in decision.mention_ids)
        actions = [decision.action.value for decision in proposal.decisions]
        decisions_by_case[case_id] = actions
        focus_by_case[case_id] = focus.action.value
        expected_by_case[case_id] = expected
        per_case.append(
            {
                "case_id": case_id,
                "manual_approval": case["manual_approval"],
                "focus_mention_id": focus_id,
                "expected_focus_action": expected,
                "predicted_focus_action": focus.action.value,
                "all_actions": actions,
            }
        )

    expected_merges = {case_id for case_id, action in expected_by_case.items() if action == "merge"}
    predicted_merges = {case_id for case_id, actions in decisions_by_case.items() if "merge" in actions}
    true_merge = len(expected_merges & predicted_merges)
    false_merge = len(predicted_merges - expected_merges)
    missed_merge = len(expected_merges - predicted_merges)
    nonmerge_cases = len(expected_by_case) - len(expected_merges)

    expected_splits = {case_id for case_id, action in expected_by_case.items() if action == "split"}
    predicted_splits = {case_id for case_id, actions in decisions_by_case.items() if "split" in actions}
    false_split = len(predicted_splits - expected_splits)
    missed_split = len(expected_splits - predicted_splits)
    nonsplit_cases = len(expected_by_case) - len(expected_splits)

    total_decisions = sum(len(actions) for actions in decisions_by_case.values())
    defer_decisions = sum(actions.count("defer") for actions in decisions_by_case.values())
    correct_focus = sum(expected_by_case[key] == focus_by_case[key] for key in expected_by_case)

    return {
        "schema": "alfalab.spike.t09-metrics/v1",
        "dataset": {
            "id": "t09-t13-independent-v1",
            "version": EXPECTED_DATASET_VERSION,
            "hash": EXPECTED_DATA_HASH,
            "manual_approval": "provisional_not_gold_not_approved",
            "case_count": len(cases),
        },
        "algorithm": {
            "mode": "deterministic_offline_rules",
            "model_quality": "NOT MEASURED",
            "quality_status": "PRELIMINARY",
        },
        "metrics": {
            "merge_precision": _ratio(true_merge, true_merge + false_merge),
            "merge_precision_counts": {"true_positive": true_merge, "false_positive": false_merge},
            "merge_recall": _ratio(true_merge, true_merge + missed_merge),
            "merge_recall_counts": {"true_positive": true_merge, "false_negative": missed_merge},
            "false_merge_rate": _ratio(false_merge, nonmerge_cases),
            "false_merge_counts": {"false_merge_cases": false_merge, "nonmerge_cases": nonmerge_cases},
            "false_split_rate": _ratio(false_split, nonsplit_cases),
            "false_split_counts": {"false_split_cases": false_split, "nonsplit_cases": nonsplit_cases},
            "defer_rate": _ratio(defer_decisions, total_decisions),
            "defer_counts": {"defer_decisions": defer_decisions, "all_decisions": total_decisions},
            "focus_decision_kind_accuracy": _ratio(correct_focus, len(cases)),
            "focus_decision_counts": {"correct": correct_focus, "cases": len(cases)},
        },
        "limitations": [
            "The expected case properties are provisional hand-authored annotations, not an approved gold set.",
            "The score is in-sample engineering feedback for this deterministic prototype, not an estimate of production accuracy.",
            "The normative EventMention DTO does not contain article title/body, so text similarity and semantic models were not evaluated.",
        ],
        "case_results": per_case,
    }


def main() -> None:
    result = calculate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    print(json.dumps(result["metrics"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
