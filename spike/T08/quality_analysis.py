"""Reproduce and audit the pinned T08 Jev pilot without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jev_spike import SPIKE_DIR, evaluate, load_verified_inputs
from quality_policy import POLICY_VERSION, decision_states, historical_review_reasons

AGGREGATE_PATH = SPIKE_DIR / "results" / "jev-live-aggregate-20261014-v4.json"
OUTPUT_PATH = SPIKE_DIR / "QUALITY_ANALYSIS.json"
TRUSTED_AGGREGATE_SHA256 = (
    "a5e95d2367cbe81fa62665e7ef42b201316136c6c08dbac23c35798996e82286"
)
HIGH_CONSEQUENCE_EVENT_CODES = {
    # Provisional audit grouping only; the project has not approved a risk
    # taxonomy. Keep the per-code counts in the report as the authoritative view.
    "sanctions",
    "trade_restriction",
    "legal_enforcement",
    "insolvency_default",
    "product_recall_quality_safety",
    "production_operational_disruption",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _event_metrics(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    event_codes: list[str],
    *,
    threshold: float,
) -> dict[str, Any]:
    by_case = {row["case_id"]: row for row in results}
    tp = fp = fn = 0
    exact = 0
    fp_rows: list[dict[str, str]] = []
    fn_rows: list[dict[str, str]] = []
    for case in cases:
        result = by_case[case["id"]]
        expected = set(case["expected_events"])
        predicted = {
            code for code in event_codes if result["event_scores"][code] >= threshold
        }
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        exact += int(predicted == expected)
        fp_rows.extend(
            {"case_id": case["id"], "code": code}
            for code in sorted(predicted - expected)
        )
        fn_rows.extend(
            {"case_id": case["id"], "code": code}
            for code in sorted(expected - predicted)
        )
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "exact_count": exact,
        "case_count": len(cases),
        "exact_rate": exact / len(cases) if cases else None,
        "false_positives": fp_rows,
        "false_negatives": fn_rows,
    }


def _subset_metrics(
    cases: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    event_codes: list[str],
    accepted_ids: set[str],
    *,
    event_threshold: float,
) -> dict[str, Any]:
    selected = [case for case in cases if case["id"] in accepted_ids]
    rows = [by_id[case["id"]] for case in selected]
    topic_correct = sum(
        row["topic"] == case["expected_topic"]
        for case, row in zip(selected, rows, strict=True)
    )
    event = (
        _event_metrics(selected, rows, event_codes, threshold=event_threshold)
        if selected
        else {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "precision": None,
            "recall": None,
            "f1": None,
            "exact_count": 0,
            "case_count": 0,
            "exact_rate": None,
            "false_positives": [],
            "false_negatives": [],
            "threshold": event_threshold,
        }
    )
    joint_exact = 0
    case_errors = []
    event_set_errors = []
    for case, row in zip(selected, rows, strict=True):
        expected_events = set(case["expected_events"])
        predicted_events = {
            code for code in event_codes if row["event_scores"][code] >= event_threshold
        }
        topic_error = row["topic"] != case["expected_topic"]
        event_error = predicted_events != expected_events
        joint_exact += int(not topic_error and not event_error)
        if event_error:
            event_set_errors.append(case["id"])
        if topic_error or event_error:
            case_errors.append(case["id"])
    critical_fps = [
        row
        for row in event["false_positives"]
        if row["code"] in HIGH_CONSEQUENCE_EVENT_CODES
    ]
    unlisted_auto_misses = [
        case["id"] for case in selected if case["expected_unlisted_event"]
    ]
    evidence_positive_auto = [
        case["id"] for case in selected if case["expected_uncertainty_signal"]
    ]
    nonclassified_gold_auto = [
        {"case_id": case["id"], "expected_status": case["expected_status"]}
        for case in selected
        if case["expected_status"] != "classified"
    ]
    return {
        "accepted_case_count": len(selected),
        "total_case_count": len(cases),
        "coverage": len(selected) / len(cases) if cases else None,
        "review_rate": 1 - len(selected) / len(cases) if cases else None,
        "topic_accuracy": topic_correct / len(selected) if selected else None,
        "topic_correct": topic_correct,
        "topic_total": len(selected),
        "event_metrics": event,
        "joint_exact_count": joint_exact,
        "joint_exact_rate": joint_exact / len(selected) if selected else None,
        "case_error_count": len(case_errors),
        "case_error_rate": len(case_errors) / len(selected) if selected else None,
        "case_error_ids": case_errors,
        "event_set_error_ids": event_set_errors,
        "high_consequence_false_positive_count_provisional": len(critical_fps),
        "high_consequence_false_positives_provisional": critical_fps,
        "provisional_high_consequence_event_codes": sorted(
            HIGH_CONSEQUENCE_EVENT_CODES
        ),
        "unlisted_gold_cases_accepted": unlisted_auto_misses,
        "insufficient_evidence_gold_cases_accepted": evidence_positive_auto,
        "nonclassified_gold_cases_accepted": nonclassified_gold_auto,
    }


def _policy_rows(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = {row["case_id"]: row for row in results}
    event_codes = [event["code"] for event in taxonomy["events"]]
    gates = {
        "current_strict": {
            "choice": True,
            "event_band": True,
            "uncertainty": True,
            "unlisted": True,
        },
        "ignore_unlisted_gate": {
            "choice": True,
            "event_band": True,
            "uncertainty": True,
            "unlisted": False,
        },
        "ignore_uncertainty_gate": {
            "choice": True,
            "event_band": True,
            "uncertainty": False,
            "unlisted": True,
        },
        "ignore_both_signal_gates": {
            "choice": True,
            "event_band": True,
            "uncertainty": False,
            "unlisted": False,
        },
        "choice_only": {
            "choice": True,
            "event_band": False,
            "uncertainty": False,
            "unlisted": False,
        },
    }
    out = []
    for name, enabled in gates.items():
        accepted: set[str] = set()
        for case in cases:
            row = by_id[case["id"]]
            signals = historical_review_reasons(row, taxonomy)
            active = signals["active"]
            blocked = (
                (enabled["choice"] and active["choice"])
                or (enabled["event_band"] and active["event_scores"])
                or (enabled["uncertainty"] and active["uncertainty"])
                or (enabled["unlisted"] and active["unlisted"])
            )
            if not blocked:
                accepted.add(case["id"])
        metrics = _subset_metrics(
            cases,
            by_id,
            event_codes,
            accepted,
            event_threshold=taxonomy["thresholds"]["noul_positive_at_or_above"],
        )
        out.append({"policy_id": name, "gates": enabled, **metrics})
    return out


def _case_rows(
    cases: list[dict[str, Any]], results: list[dict[str, Any]], taxonomy: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {row["case_id"]: row for row in results}
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for case in cases:
        result = by_id[case["id"]]
        reasons = historical_review_reasons(result, taxonomy)
        states = decision_states(result, taxonomy)
        predicted = set(result["predicted_events"])
        expected = set(case["expected_events"])
        fp = sorted(predicted - expected)
        fn = sorted(expected - predicted)
        topic_mismatch = result["topic"] != case["expected_topic"]
        row = {
            "case_id": case["id"],
            "title": case["title"],
            "text": case["text"],
            "case_type": case["case_type"],
            "gold": {
                "topic": case["expected_topic"],
                "events": sorted(expected),
                "status": case["expected_status"],
                "unlisted_event": case["expected_unlisted_event"],
                "insufficient_evidence": case["expected_uncertainty_signal"],
            },
            "jev": {
                "topic": result["topic"],
                "choice_confidence": result["topic_confidence"],
                "topic_probabilities": result["topic_probabilities"],
                "events": sorted(predicted),
                "event_scores": result["event_scores"],
                "unlisted_score": result["unlisted_event_score"],
                "uncertainty_score": result["uncertainty_score"],
                "status": result["classification_status"],
                "model_version": result["model_version"],
            },
            "topic_mismatch": topic_mismatch,
            "event_false_positives": fp,
            "event_false_negatives": fn,
            "event_set_exact": not fp and not fn,
            "review": {
                "raw_triggers": reasons["raw"],
                "active_code_triggers": reasons["active"],
                "borderline_event_codes": reasons["borderline_event_codes"],
                "unlisted_noul_state": reasons["unlisted_noul_state"],
                "uncertainty_noul_state": reasons["uncertainty_noul_state"],
                "expected_status_from_active_gate": reasons[
                    "expected_status_from_active_gate"
                ],
                "decision_states": states,
                "final_status": result["classification_status"],
            },
        }
        rows.append(row)
        if (
            topic_mismatch
            or fp
            or fn
            or result["classification_status"] != case["expected_status"]
        ):
            error_types = []
            if topic_mismatch:
                error_types.append("topic_mismatch")
            if fp:
                error_types.append("event_false_positive")
            if fn:
                error_types.append("event_false_negative")
            if result["classification_status"] != case["expected_status"]:
                error_types.append("review_status_mismatch")
            errors.append({**row, "error_types": error_types})
    return rows, errors


def _review_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reason_names = ["choice", "event_scores", "uncertainty", "unlisted"]
    review_rows = [row for row in rows if row["jev"]["status"] == "uncertain"]
    counts = {
        name: sum(row["review"]["active_code_triggers"][name] for row in review_rows)
        for name in reason_names
    }
    combination_counts = Counter(
        "+".join(
            name for name in reason_names if row["review"]["active_code_triggers"][name]
        )
        for row in review_rows
    )
    exclusive_counts = {
        name: sum(
            sum(row["review"]["active_code_triggers"].values()) == 1
            and row["review"]["active_code_triggers"][name]
            for row in review_rows
        )
        for name in reason_names
    }
    raw_counts = {
        name: sum(row["review"]["raw_triggers"][name] for row in rows)
        for name in reason_names
    }
    event_cells = sum(len(row["review"]["borderline_event_codes"]) for row in rows)
    return {
        "case_count": len(rows),
        "review_count": len(review_rows),
        "review_rate": len(review_rows) / len(rows) if rows else None,
        "automatic_status_count": len(rows) - len(review_rows),
        "active_trigger_case_counts_overlapping": counts,
        "raw_trigger_case_counts_before_other_topic_exception": raw_counts,
        "exclusive_single_reason_counts": exclusive_counts,
        "trigger_combination_counts": dict(sorted(combination_counts.items())),
        "review_cases_with_multiple_reasons": sum(
            sum(row["review"]["active_code_triggers"].values()) > 1
            for row in review_rows
        ),
        "review_cases_with_exactly_one_reason": sum(
            sum(row["review"]["active_code_triggers"].values()) == 1
            for row in review_rows
        ),
        "borderline_event_score_cells": event_cells,
        "total_event_score_cells": len(rows) * len(rows[0]["jev"]["event_scores"])
        if rows
        else 0,
        "cases_with_at_least_one_borderline_event_score": sum(
            bool(row["review"]["borderline_event_codes"]) for row in rows
        ),
        "noul_state_counts": {
            "unlisted": dict(
                Counter(row["review"]["unlisted_noul_state"] for row in rows)
            ),
            "insufficient_evidence": dict(
                Counter(row["review"]["uncertainty_noul_state"] for row in rows)
            ),
        },
        "note": "Overlapping trigger counts must not be summed as distinct reviewed cases. The historical other_uncertain branch ignores event-band and unlisted triggers.",
    }


def _signal_quality(
    cases: list[dict[str, Any]], rows: list[dict[str, Any]], *, signal: str
) -> dict[str, Any]:
    expected_key = (
        "expected_unlisted_event"
        if signal == "unlisted"
        else "expected_uncertainty_signal"
    )
    state_key = (
        "unlisted_noul_state" if signal == "unlisted" else "uncertainty_noul_state"
    )
    cases_by_id = {case["id"]: case for case in cases}
    tp = fp = fn = tn = unresolved_positive = unresolved_negative = 0
    for row in rows:
        expected = cases_by_id[row["case_id"]][expected_key]
        state = row["review"][state_key]
        if state == "positive":
            tp += int(expected)
            fp += int(not expected)
        elif state == "negative":
            fn += int(expected)
            tn += int(not expected)
        else:
            unresolved_positive += int(expected)
            unresolved_negative += int(not expected)
    return {
        "signal": signal,
        "positive_cutoff": 0.8,
        "negative_cutoff": 0.2,
        "tp": tp,
        "fp": fp,
        "fn_on_decided_cases": fn,
        "tn": tn,
        "unresolved_positive_gold": unresolved_positive,
        "unresolved_negative_gold": unresolved_negative,
        "decided_case_count": tp + fp + fn + tn,
        "decision_accuracy": (tp + tn) / (tp + fp + fn + tn)
        if tp + fp + fn + tn
        else None,
        "positive_precision": tp / (tp + fp) if tp + fp else None,
        "positive_recall_over_all_gold_positive": tp / (tp + fn + unresolved_positive)
        if tp + fn + unresolved_positive
        else None,
        "warning": "These counts use single-author draft labels and are descriptive only; unresolved values are not coerced to positive or negative.",
    }


def _threshold_sweeps(
    cases: list[dict[str, Any]], results: list[dict[str, Any]], taxonomy: dict[str, Any]
) -> dict[str, Any]:
    event_codes = [event["code"] for event in taxonomy["events"]]
    by_id = {row["case_id"]: row for row in results}
    topic_rows = []
    for cutoff in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        accepted = {
            case["id"]
            for case in cases
            if by_id[case["id"]]["topic_confidence"] >= cutoff
        }
        metrics = _subset_metrics(
            cases, by_id, event_codes, accepted, event_threshold=0.8
        )
        topic_rows.append({"choice_cutoff": cutoff, **metrics})
    event_rows = [
        _event_metrics(cases, results, event_codes, threshold=cutoff)
        for cutoff in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    ]
    # The existing v4 sweep uses a fixed .2 negative cutoff and binary labels
    # at each positive cutoff. Preserve that view, but pair it with the
    # three-state event review-band cell/case coverage.
    band_rows = []
    for low in (0.1, 0.2, 0.3):
        for high in (0.6, 0.7, 0.8, 0.9):
            cells = sum(
                low < row["event_scores"][code] < high
                for row in results
                for code in event_codes
            )
            cases_with_band = sum(
                any(low < row["event_scores"][code] < high for code in event_codes)
                for row in results
            )
            band_rows.append(
                {
                    "negative_cutoff": low,
                    "positive_cutoff": high,
                    "ambiguous_cells": cells,
                    "cell_coverage": 1 - cells / (len(results) * len(event_codes)),
                    "cases_with_any_ambiguous_event": cases_with_band,
                    "case_rate_with_any_ambiguous_event": cases_with_band
                    / len(results),
                }
            )
    return {
        "choice_threshold_sweep": topic_rows,
        "event_positive_cutoff_sweep": event_rows,
        "event_ambiguous_band_sweep": band_rows,
        "warning": "Every sweep reuses the same 45 partially observed cases and draft labels. Do not select a production cutoff from these rows.",
    }


def _review_gate_sweeps(
    cases: list[dict[str, Any]], results: list[dict[str, Any]], taxonomy: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Vary one historical review trigger while holding the other gates fixed."""
    by_id = {row["case_id"]: row for row in results}
    event_codes = [event["code"] for event in taxonomy["events"]]
    thresholds = taxonomy["thresholds"]
    negative = thresholds["noul_negative_at_or_below"]
    positive = thresholds["noul_positive_at_or_above"]
    choice_cutoff = thresholds["choice_review_below"]

    def evaluate_gate(varied: str, cutoff: float) -> dict[str, Any]:
        accepted: set[str] = set()
        for case in cases:
            row = by_id[case["id"]]
            other_topic = row["topic"] == taxonomy["other_code"]
            choice_trigger = row["topic_confidence"] < choice_cutoff
            event_trigger = not other_topic and any(
                negative < row["event_scores"][code] < positive for code in event_codes
            )
            uncertainty_trigger = row["uncertainty_score"] > (
                cutoff if varied == "uncertainty" else negative
            )
            unlisted_trigger = not other_topic and row["unlisted_event_score"] > (
                cutoff if varied == "unlisted" else negative
            )
            if not any(
                (choice_trigger, event_trigger, uncertainty_trigger, unlisted_trigger)
            ):
                accepted.add(case["id"])
        metrics = _subset_metrics(
            cases,
            by_id,
            event_codes,
            accepted,
            event_threshold=positive,
        )
        return {"gate": varied, "trigger_when_score_above": cutoff, **metrics}

    values = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
    return {
        "uncertainty_gate_threshold_sweep": [
            evaluate_gate("uncertainty", value) for value in values
        ],
        "unlisted_gate_threshold_sweep": [
            evaluate_gate("unlisted", value) for value in values
        ],
    }


def build_quality_analysis() -> dict[str, Any]:
    taxonomy, corpus, all_cases = load_verified_inputs()
    cases = [case for case in all_cases if case["expected_status"] != "no_content"]
    aggregate = _load(AGGREGATE_PATH)
    if _sha256(AGGREGATE_PATH) != TRUSTED_AGGREGATE_SHA256:
        raise ValueError("pinned aggregate v4 hash changed")
    results = aggregate.get("results")
    if not isinstance(results, list):
        raise TypeError("pinned aggregate has no results list")
    recomputed = evaluate(all_cases, results, taxonomy)
    if recomputed != aggregate.get("metrics"):
        raise ValueError("current evaluator does not reproduce aggregate v4 metrics")
    by_id = {row["case_id"]: row for row in results}
    if len(by_id) != len(results) or not set(by_id).issubset(
        {case["id"] for case in cases}
    ):
        raise ValueError("aggregate result ids are duplicate or outside baseline")
    observed_cases = [case for case in cases if case["id"] in by_id]
    missing_ids = [case["id"] for case in cases if case["id"] not in by_id]
    if missing_ids != aggregate.get("missing_result_case_ids"):
        raise ValueError("aggregate missing-result list is inconsistent")
    if len(results) + len(missing_ids) != len(cases):
        raise ValueError("aggregate does not account for every nonempty baseline case")
    rows, errors = _case_rows(observed_cases, results, taxonomy)
    summary = _review_summary(rows)
    if summary["review_count"] != recomputed["review_count"]:
        raise ValueError("reconstructed review count differs from aggregate v4")
    return {
        "analysis_version": "1.0.0",
        "policy_version": POLICY_VERSION,
        "generated_from": {
            "aggregate_file": AGGREGATE_PATH.name,
            "aggregate_sha256": _sha256(AGGREGATE_PATH),
            "corpus_sha256": _sha256(SPIKE_DIR / "corpus.json"),
            "taxonomy_sha256": _sha256(SPIKE_DIR / "taxonomy.json"),
            "corpus_version": corpus["version"],
            "taxonomy_version": taxonomy["version"],
            "model_version": aggregate["model_version"],
            "result_count": len(results),
            "expected_nonempty_count": len(cases),
            "observed_case_ids": [case["id"] for case in observed_cases],
            "missing_case_ids": aggregate["missing_result_case_ids"],
            "all_new_live_calls": 0,
            "gold_status": "single-author synthetic draft; not independently adjudicated",
            "holdout_status": "no blind holdout; deep-v1 D is visible and excluded from this analysis",
        },
        "reproduction": {
            "legacy_metrics_exactly_reproduced": True,
            "legacy_metrics": recomputed,
            "note": "Recomputed from saved v4 rows and the unchanged baseline evaluator; no provider request was made.",
        },
        "review_summary": summary,
        "signal_quality": {
            "unlisted": _signal_quality(observed_cases, rows, signal="unlisted"),
            "insufficient_evidence": _signal_quality(
                observed_cases, rows, signal="uncertainty"
            ),
        },
        "policies": _policy_rows(observed_cases, results, taxonomy),
        "threshold_sweeps": _threshold_sweeps(observed_cases, results, taxonomy),
        "review_gate_sweeps": _review_gate_sweeps(observed_cases, results, taxonomy),
        "high_consequence_fp_policy": {
            "event_codes": sorted(HIGH_CONSEQUENCE_EVENT_CODES),
            "status": "provisional audit grouping; not approved project risk taxonomy",
        },
        "cases": rows,
        "error_cases": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_PATH, help="JSON output within spike/T08"
    )
    parser.add_argument(
        "--check", action="store_true", help="compare generated bytes without writing"
    )
    args = parser.parse_args()
    try:
        output_path = args.output.resolve()
        spike_root = SPIKE_DIR.resolve()
        if output_path != spike_root and spike_root not in output_path.parents:
            raise ValueError("output must remain inside spike/T08")
        encoded = (
            json.dumps(build_quality_analysis(), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        if args.check:
            if not output_path.is_file() or output_path.read_bytes() != encoded:
                raise ValueError(
                    "quality analysis output is missing or not reproducible"
                )
            print(
                f"QUALITY_ANALYSIS_REPRODUCIBLE={output_path.relative_to(spike_root)}"
            )
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(encoded)
            print(f"QUALITY_ANALYSIS={output_path.relative_to(spike_root)}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
