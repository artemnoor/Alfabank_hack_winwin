"""Versioned offline interpretation policies for stored Jev scores.

This module never calls a provider and never changes a stored result. It keeps
the historical v0.3 status rule available for audit while exposing Noul's
negative / positive / abstain states as separate decisions.
"""

from __future__ import annotations

import math
from typing import Any

POLICY_VERSION = "1.0.0-spike"


class PolicyInputError(ValueError):
    """Raised when a saved Jev score cannot be interpreted safely."""


def _score(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise PolicyInputError(f"{name} must be a finite score from 0 to 1")
    return float(value)


def noul_state(value: Any, *, negative_cutoff: float, positive_cutoff: float) -> str:
    """Return a three-way Noul state; never coerce the abstain band to false."""
    score = _score(value, "Noul score")
    negative = _score(negative_cutoff, "negative cutoff")
    positive = _score(positive_cutoff, "positive cutoff")
    if negative >= positive:
        raise PolicyInputError("negative cutoff must be below positive cutoff")
    if score <= negative:
        return "negative"
    if score >= positive:
        return "positive"
    return "abstain"


def decision_states(result: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    """Interpret each independent signal without collapsing their meanings."""
    if not isinstance(result, dict) or not isinstance(taxonomy, dict):
        raise PolicyInputError("result and taxonomy must be objects")
    required = {
        "topic",
        "topic_confidence",
        "event_scores",
        "unlisted_event_score",
        "uncertainty_score",
    }
    if not required.issubset(result):
        raise PolicyInputError("result is missing required classification fields")
    if not isinstance(result["event_scores"], dict):
        raise PolicyInputError("event_scores must be an object")
    if (
        not isinstance(taxonomy.get("topics"), list)
        or not isinstance(taxonomy.get("events"), list)
        or not isinstance(taxonomy.get("thresholds"), dict)
    ):
        raise PolicyInputError(
            "taxonomy topics, events, and thresholds must be defined"
        )
    thresholds = taxonomy["thresholds"]
    negative = thresholds["noul_negative_at_or_below"]
    positive = thresholds["noul_positive_at_or_above"]
    confidence = _score(result["topic_confidence"], "Choice confidence")
    choice_cutoff = _score(thresholds["choice_review_below"], "Choice cutoff")
    event_codes = {event["code"] for event in taxonomy["events"]}
    if set(result["event_scores"]) != event_codes:
        raise PolicyInputError("event_scores do not match the pinned taxonomy")
    event_states = {
        event["code"]: noul_state(
            result["event_scores"][event["code"]],
            negative_cutoff=negative,
            positive_cutoff=positive,
        )
        for event in taxonomy["events"]
    }
    if not isinstance(result["topic"], str):
        raise PolicyInputError("topic must be a category code")
    topic_codes = {
        row.get("code") for row in taxonomy["topics"] if isinstance(row, dict)
    }
    if result["topic"] not in topic_codes:
        raise PolicyInputError("topic is outside the pinned taxonomy")
    return {
        "topic": {
            "code": result["topic"],
            "state": "review" if confidence < choice_cutoff else "accepted",
            "choice_confidence": confidence,
            "cutoff": choice_cutoff,
        },
        "events": event_states,
        "unlisted_event": noul_state(
            result["unlisted_event_score"],
            negative_cutoff=negative,
            positive_cutoff=positive,
        ),
        "insufficient_evidence": noul_state(
            result["uncertainty_score"],
            negative_cutoff=negative,
            positive_cutoff=positive,
        ),
        "score_bands": {
            "negative_at_or_below": negative,
            "positive_at_or_above": positive,
        },
    }


def historical_review_reasons(
    result: dict[str, Any], taxonomy: dict[str, Any]
) -> dict[str, Any]:
    """Reproduce v0.3's actual combined `classification_status` gate.

    For the `other_uncertain` Choice branch the historical implementation only
    checks Choice and insufficient-evidence signals; it ignores event bands and
    the unlisted score. Both the raw and effective trigger sets are returned so
    that this exception stays visible.
    """
    # Reuse the strict score/schema validation used for the separated states.
    decision_states(result, taxonomy)
    thresholds = taxonomy["thresholds"]
    negative = thresholds["noul_negative_at_or_below"]
    positive = thresholds["noul_positive_at_or_above"]
    choice_low = result["topic_confidence"] < thresholds["choice_review_below"]
    borderline_codes = [
        event["code"]
        for event in taxonomy["events"]
        if negative < result["event_scores"][event["code"]] < positive
    ]
    uncertainty_not_negative = result["uncertainty_score"] > negative
    unlisted_not_negative = result["unlisted_event_score"] > negative
    raw = {
        "choice": choice_low,
        "event_scores": bool(borderline_codes),
        "uncertainty": uncertainty_not_negative,
        "unlisted": unlisted_not_negative,
    }
    if result["topic"] == taxonomy["other_code"]:
        active = {
            "choice": choice_low,
            "event_scores": False,
            "uncertainty": uncertainty_not_negative,
            "unlisted": False,
        }
    else:
        active = raw.copy()
    return {
        "raw": raw,
        "active": active,
        "borderline_event_codes": borderline_codes,
        "unlisted_noul_state": noul_state(
            result["unlisted_event_score"],
            negative_cutoff=negative,
            positive_cutoff=positive,
        ),
        "uncertainty_noul_state": noul_state(
            result["uncertainty_score"],
            negative_cutoff=negative,
            positive_cutoff=positive,
        ),
        "expected_status_from_active_gate": (
            "uncertain"
            if any(active.values())
            else "other"
            if result["topic"] == taxonomy["other_code"]
            else "classified"
        ),
    }
