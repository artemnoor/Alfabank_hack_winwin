"""Exact-hash allowlist for the one synthetic Jev pilot eligible for egress."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .binding import CandidateEvent, candidates_from_t08
from .errors import ExtractionValidationError

T08_DIR = Path(__file__).resolve().parents[1]
PILOT_DIR = T08_DIR / "experiments" / "jev-expanded-pilot-v1"
ALLOWLIST_PATH = Path(__file__).with_name("synthetic-live-allowlist-v2.json")
TAXONOMY_PATH = T08_DIR / "taxonomy.json"
POLICY_PATH = T08_DIR / "visualization" / "policy_v2.py"


@dataclass(frozen=True)
class ApprovedPilotCase:
    case: dict
    classification: dict
    taxonomy: dict


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_approved_pilot_case(case_id: str, article_text: str) -> ApprovedPilotCase:
    """Verify byte-pinned source files, then require an exact case-text match."""
    try:
        allowlist = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
        news_bytes = (PILOT_DIR / "news.json").read_bytes()
        results_bytes = (PILOT_DIR / "live-results.json").read_bytes()
        taxonomy_bytes = TAXONOMY_PATH.read_bytes()
        policy_bytes = POLICY_PATH.read_bytes()
        from .prompt import PROMPT_SHA256

        if (
            _sha256_bytes(news_bytes) != allowlist["news_file_sha256"]
            or _sha256_bytes(results_bytes) != allowlist["results_file_sha256"]
            or _sha256_bytes(taxonomy_bytes) != allowlist["taxonomy_file_sha256"]
            or _sha256_bytes(policy_bytes) != allowlist["policy_file_sha256"]
            or PROMPT_SHA256 != allowlist["prompt_sha256"]
        ):
            raise ExtractionValidationError("synthetic_corpus_integrity_mismatch")
        news = json.loads(news_bytes)
        results = json.loads(results_bytes)
        taxonomy = json.loads(taxonomy_bytes)
        if (
            news["dataset_id"] != allowlist["allowed_dataset_id"]
            or news["version"] != allowlist["allowed_dataset_version"]
            or len(news["cases"]) != allowlist["allowed_case_count"]
        ):
            raise ExtractionValidationError("synthetic_corpus_integrity_mismatch")
        case = next(row for row in news["cases"] if row["id"] == case_id)
        classification = next(
            row for row in results["results"] if row["case_id"] == case_id
        )
    except ExtractionValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, StopIteration):
        raise ExtractionValidationError(
            "trusted_synthetic_case_not_allowlisted"
        ) from None
    if case["text"] != article_text:
        raise ExtractionValidationError("trusted_synthetic_case_not_allowlisted")
    return ApprovedPilotCase(
        case=case, classification=classification, taxonomy=taxonomy
    )


def validate_approved_extraction_payload(
    *, case_id: str, article_text: str, classification: dict, candidate: CandidateEvent
) -> None:
    """Prove direct adapter use cannot bypass saved Jev policy and taxonomy."""
    approved = load_approved_pilot_case(case_id, article_text)
    if classification != approved.classification:
        raise ExtractionValidationError("trusted_jev_result_not_allowlisted")
    try:
        from policy_v2 import evaluate_result

        decision = evaluate_result(approved.classification, approved.taxonomy)
        allowed_candidates = candidates_from_t08(
            decision["candidate_codes"],
            approved.taxonomy,
            _binding_for(approved.taxonomy),
        )
    except (ImportError, KeyError, TypeError, ValueError) as exc:
        raise ExtractionValidationError("jev_result_or_policy_invalid") from exc
    if candidate not in allowed_candidates:
        raise ExtractionValidationError("candidate_not_released_by_saved_jev_policy")


def _binding_for(taxonomy: dict):
    """Load the pinned code binding after the allowlisted taxonomy is verified."""
    from .binding import load_experiment_binding

    binding = load_experiment_binding()
    taxonomy_codes = {row["code"] for row in taxonomy["events"]}
    if binding.event_codes != taxonomy_codes:
        raise ExtractionValidationError("schema_binding_event_codes_mismatch")
    return binding
