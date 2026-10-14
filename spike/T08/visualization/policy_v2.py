"""Experimental, offline Policy v2 interpretation for the T08 visualization.

This module only re-reads the pinned Jev aggregate. Positive event scores are
forwarded as *candidates*, never as confirmed facts. It does not call Jev or
modify the source corpus, taxonomy, aggregate, or historical policy.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

POLICY_VERSION = "2.0.0-spike"
PROVISIONAL_HIGH_CONSEQUENCE_CODES = frozenset(
    {
        "sanctions",
        "trade_restriction",
        "legal_enforcement",
        "insolvency_default",
        "product_recall_quality_safety",
        "production_operational_disruption",
    }
)


class PolicyV2InputError(ValueError):
    """Raised when a stored score cannot be interpreted safely."""


def _score(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise PolicyV2InputError(f"{name} must be a finite score from 0 to 1")
    return float(value)


def tri_state(score: Any, *, negative: float, positive: float, name: str) -> str:
    """Map a score to inclusive negative/positive bands and an abstain band."""
    score_value = _score(score, name)
    negative_value = _score(negative, "negative threshold")
    positive_value = _score(positive, "positive threshold")
    if negative_value >= positive_value:
        raise PolicyV2InputError("negative threshold must be below positive threshold")
    if score_value <= negative_value:
        return "negative"
    if score_value >= positive_value:
        return "positive"
    return "abstain"


def evaluate_result(
    result: dict[str, Any],
    taxonomy: dict[str, Any],
    *,
    choice_cutoff: float | None = None,
    negative_cutoff: float | None = None,
    positive_cutoff: float | None = None,
    evidence_cutoff: float | None = None,
    unlisted_cutoff: float | None = None,
) -> dict[str, Any]:
    """Evaluate independent signals and the candidates eligible for routing.

    Routing rule (pre-registered for this offline comparison): only a positive
    event score is a candidate, and any non-negative insufficient-evidence
    state holds all candidates for human evidence review. Choice, an event's
    own abstain state, and the unlisted-event signal create scoped review items
    but do not suppress unrelated event candidates.
    """
    if not isinstance(result, dict) or not isinstance(taxonomy, dict):
        raise PolicyV2InputError("result and taxonomy must be objects")
    thresholds = taxonomy.get("thresholds")
    if not isinstance(thresholds, dict):
        raise PolicyV2InputError("taxonomy thresholds must be an object")
    events = taxonomy.get("events")
    topics = taxonomy.get("topics")
    if not isinstance(events, list) or not isinstance(topics, list):
        raise PolicyV2InputError("taxonomy events and topics must be lists")
    if not isinstance(result.get("event_scores"), dict):
        raise PolicyV2InputError("event_scores must be an object")

    topic_codes = {row.get("code") for row in topics if isinstance(row, dict)}
    if result.get("topic") not in topic_codes:
        raise PolicyV2InputError("topic is outside the pinned taxonomy")
    event_code_list = [row.get("code") for row in events if isinstance(row, dict)]
    event_codes = set(event_code_list)
    if set(result["event_scores"]) != event_codes:
        raise PolicyV2InputError("event_scores do not match the pinned taxonomy")

    choice_threshold = _score(
        thresholds["choice_review_below"] if choice_cutoff is None else choice_cutoff,
        "Choice threshold",
    )
    negative = _score(
        thresholds["noul_negative_at_or_below"]
        if negative_cutoff is None
        else negative_cutoff,
        "negative threshold",
    )
    positive = _score(
        thresholds["noul_positive_at_or_above"]
        if positive_cutoff is None
        else positive_cutoff,
        "positive threshold",
    )
    if negative >= positive:
        raise PolicyV2InputError("negative threshold must be below positive threshold")
    evidence_threshold = (
        negative
        if evidence_cutoff is None
        else _score(evidence_cutoff, "evidence threshold")
    )
    unlisted_threshold = (
        negative
        if unlisted_cutoff is None
        else _score(unlisted_cutoff, "unlisted threshold")
    )

    confidence = _score(result.get("topic_confidence"), "Choice confidence")
    event_states = {
        code: tri_state(
            result["event_scores"][code],
            negative=negative,
            positive=positive,
            name=f"event score {code}",
        )
        for code in event_code_list
    }
    evidence_score = _score(
        result.get("uncertainty_score"), "insufficient-evidence score"
    )
    unlisted_score = _score(result.get("unlisted_event_score"), "unlisted-event score")
    evidence_state = tri_state(
        evidence_score,
        negative=evidence_threshold,
        positive=positive,
        name="insufficient-evidence score",
    )
    unlisted_state = tri_state(
        unlisted_score,
        negative=unlisted_threshold,
        positive=positive,
        name="unlisted-event score",
    )

    choice_review = confidence < choice_threshold
    evidence_review = evidence_state != "negative"
    unlisted_review = unlisted_state != "negative"
    event_review_codes = sorted(
        code for code, state in event_states.items() if state == "abstain"
    )
    positive_codes = sorted(
        code for code, state in event_states.items() if state == "positive"
    )
    candidate_blocked_by_evidence = evidence_state != "negative"
    candidate_codes = [] if candidate_blocked_by_evidence else positive_codes
    blocked_codes = positive_codes if candidate_blocked_by_evidence else []
    review_story = bool(
        choice_review or evidence_review or unlisted_review or event_review_codes
    )
    return {
        "topic_state": "review" if choice_review else "accepted",
        "topic_confidence": confidence,
        "event_states": event_states,
        "event_review_codes": event_review_codes,
        "positive_event_codes": positive_codes,
        "candidate_codes": candidate_codes,
        "candidate_blocked_codes": blocked_codes,
        "insufficient_evidence_state": evidence_state,
        "unlisted_event_state": unlisted_state,
        "choice_review": choice_review,
        "evidence_review": evidence_review,
        "unlisted_review": unlisted_review,
        "candidate_blocked_by_evidence": candidate_blocked_by_evidence,
        "needs_any_review": review_story,
    }


def evaluate_case(
    case: dict[str, Any], taxonomy: dict[str, Any], **thresholds: Any
) -> dict[str, Any]:
    """Evaluate one visualization case, preserving absent results as absent."""
    result = case.get("result")
    if result is None:
        return {
            "status": "missing" if case.get("text", "").strip() else "no_content",
            "candidate_codes": [],
            "candidate_blocked_codes": [],
            "event_review_codes": [],
            "needs_any_review": bool(case.get("text", "").strip()),
            "missing_result": bool(case.get("text", "").strip()),
        }
    return {
        "status": "review"
        if (decision := evaluate_result(result, taxonomy, **thresholds))[
            "needs_any_review"
        ]
        else "no_review",
        "missing_result": False,
        **decision,
    }


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _event_counts(
    cases: list[dict[str, Any]],
    event_codes: Iterable[str],
    emitted_by_case: dict[str, set[str]],
) -> dict[str, Any]:
    tp = fp = fn = exact = 0
    false_positives: list[dict[str, str]] = []
    for case in cases:
        predicted = emitted_by_case.get(case["id"], set())
        expected = set(case.get("expected_events", []))
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        exact += int(predicted == expected)
        false_positives.extend(
            {"case_id": case["id"], "code": code}
            for code in sorted(predicted - expected)
        )
    return {
        **_prf(tp, fp, fn),
        "exact_count": exact,
        "exact_rate": exact / len(cases) if cases else None,
        "case_count": len(cases),
        "false_positives": false_positives,
        "event_code_count": len(tuple(event_codes)),
    }


def compare_policies(
    cases: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    *,
    legacy_predictions: dict[str, set[str]],
    legacy_review_ids: set[str],
    **thresholds: Any,
) -> dict[str, Any]:
    """Compare actual gated delivery, not all raw scores, on the same 45 rows."""
    observed = [case for case in cases if case.get("result") is not None]
    event_codes = [row["code"] for row in taxonomy["events"]]
    decisions = {
        case["id"]: evaluate_case(case, taxonomy, **thresholds) for case in observed
    }
    v2_outputs = {
        case_id: set(decision["candidate_codes"])
        for case_id, decision in decisions.items()
    }
    legacy_events = _event_counts(observed, event_codes, legacy_predictions)
    v2_events = _event_counts(observed, event_codes, v2_outputs)
    total_positive = sum(len(set(case["expected_events"])) for case in observed)
    legacy_emitted_ids = {
        case_id for case_id, codes in legacy_predictions.items() if codes
    }
    v2_emitted_ids = {case_id for case_id, codes in v2_outputs.items() if codes}
    event_review_count = sum(
        len(decision["event_review_codes"]) for decision in decisions.values()
    )
    choice_review_count = sum(
        decision["choice_review"] for decision in decisions.values()
    )
    evidence_review_count = sum(
        decision["evidence_review"] for decision in decisions.values()
    )
    unlisted_review_count = sum(
        decision["unlisted_review"] for decision in decisions.values()
    )
    review_ids = {
        case_id
        for case_id, decision in decisions.items()
        if decision["needs_any_review"]
    }
    candidate_blocked = sum(
        bool(decision["candidate_blocked_codes"]) for decision in decisions.values()
    )
    v2_events["false_negatives_as_not_forwarded"] = v2_events["fn"]
    v2_events["expected_event_total"] = total_positive
    legacy_events["expected_event_total"] = total_positive
    v2_events["provisional_high_consequence_fp"] = [
        item
        for item in v2_events["false_positives"]
        if item["code"] in PROVISIONAL_HIGH_CONSEQUENCE_CODES
    ]
    legacy_events["provisional_high_consequence_fp"] = [
        item
        for item in legacy_events["false_positives"]
        if item["code"] in PROVISIONAL_HIGH_CONSEQUENCE_CODES
    ]
    v2_events["provisional_high_consequence_fp_count"] = len(
        v2_events["provisional_high_consequence_fp"]
    )
    legacy_events["provisional_high_consequence_fp_count"] = len(
        legacy_events["provisional_high_consequence_fp"]
    )
    return {
        "policy_version": POLICY_VERSION,
        "denominator": len(observed),
        "expected_event_total": total_positive,
        "legacy": {
            "full_story_auto_count": len(observed) - len(legacy_review_ids),
            "full_story_review_count": len(legacy_review_ids),
            "stories_with_emitted_events": len(legacy_emitted_ids),
            "emitted_event_count": sum(map(len, legacy_predictions.values())),
            "event_output_metrics": legacy_events,
        },
        "policy_v2": {
            "stories_with_candidates": len(v2_emitted_ids),
            "candidate_coverage": len(v2_emitted_ids) / len(observed)
            if observed
            else None,
            "candidate_event_count": sum(map(len, v2_outputs.values())),
            "stories_with_any_review": len(review_ids),
            "stories_without_review": len(observed) - len(review_ids),
            "stories_with_candidate_blocked_by_evidence": candidate_blocked,
            "choice_review_stories": choice_review_count,
            "insufficient_evidence_review_stories": evidence_review_count,
            "unlisted_event_review_stories": unlisted_review_count,
            "event_abstain_cells": event_review_count,
            "event_abstain_stories": sum(
                bool(decision["event_review_codes"]) for decision in decisions.values()
            ),
            "scoped_review_items": (
                choice_review_count
                + evidence_review_count
                + unlisted_review_count
                + event_review_count
            ),
            "event_output_metrics": v2_events,
            "cases": decisions,
        },
        "interpretation": {
            "candidate_is_fact": False,
            "evidence_route": "candidate only when insufficient-evidence state is negative",
            "choice_blocks_event_candidates": False,
            "unlisted_blocks_known_event_candidates": False,
            "event_abstain_blocks_other_event_candidates": False,
            "provisional_risk_codes": sorted(PROVISIONAL_HIGH_CONSEQUENCE_CODES),
            "provisional_risk_policy_approved": False,
        },
    }
