"""Offline experiments for evidence integrity and trust-policy boundaries.

This module is deliberately not an Evidence.register/read implementation. It
accepts materialized contract records, immutable source snapshots, and explicit
hand-authored source-assertion annotations, then returns a read-only assessment.
"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Mapping, Sequence

from pydantic import ValidationError

from alfalab_contracts.models import SCHEMA_TYPES


logger = logging.getLogger("t11.evidence_trust")
OWNER_POLICY_SCHEMA = "alfalab.spike.synthetic-owner-policy/v1"
OWNER_POLICY_VERSION = "1.0.1"

TEST_OWNER_POLICY_ID = "test-owner-policy-t09-t13-v1"
TEST_OWNER_POLICY_SCHEMA = OWNER_POLICY_SCHEMA
TEST_OWNER_POLICY_VERSION = OWNER_POLICY_VERSION
TEST_OWNER_POLICY_DATASET_ID = "t09-t13-independent-v1"
TEST_OWNER_POLICY_CANONICAL_SHA256 = "sha256:7ab45d5de57f60f612f11820a444bacf216cd77704f5e5598218eae7ca0e6327"


class AnchorIntegrity(StrEnum):
    VERIFIED = "verified"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class ClaimStatus(StrEnum):
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    HISTORICAL = "historical"
    DISPUTED = "disputed"
    SUPPORTED_UNCONFIRMED = "supported_unconfirmed"


@dataclass(frozen=True, slots=True)
class AnchorCheck:
    integrity: AnchorIntegrity
    reason_codes: tuple[str, ...]
    source_document_id: str | None
    source_version: int | None
    source_hash: str | None
    locator_kind: str | None
    locator_start: int | None
    locator_end: int | None
    quote_hash: str | None
    declared_verification: str | None


@dataclass(frozen=True, slots=True)
class SourceAssertion:
    """A precomputed relation between one cited source and one proposition.

    The relation is supplied as a provisional hand-authored fixture annotation.
    T11 does not extract it from source text or treat it as a truth label.
    """

    annotation_id: str
    evidence_ref: str
    claim_id: str
    relation: Literal["supports", "contradicts", "mentions_only", "unknown"]
    value: str | None
    temporal_scope: Literal["current", "historical", "unknown"]
    annotation_provenance: str = "t11-evidence-trust-cases-v1.0.0:hand-authored-synthetic"

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.annotation_id, self.evidence_ref, self.claim_id, self.annotation_provenance,
        )):
            raise ValueError("source-assertion identifiers and provenance must be non-empty strings")
        if not isinstance(self.relation, str) or self.relation not in {"supports", "contradicts", "mentions_only", "unknown"}:
            raise ValueError("unsupported source-assertion relation")
        if not isinstance(self.temporal_scope, str) or self.temporal_scope not in {"current", "historical", "unknown"}:
            raise ValueError("unsupported source-assertion temporal scope")
        if self.value is not None and not isinstance(self.value, str):
            raise ValueError("source-assertion value must be a string or null")

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> SourceAssertion:
        allowed = {
            "annotation_id", "evidence_ref", "claim_id", "relation", "value",
            "temporal_scope", "annotation_provenance",
        }
        if set(row) - allowed:
            raise ValueError("unknown source-assertion annotation fields")
        required = {"annotation_id", "evidence_ref", "claim_id", "relation", "value", "temporal_scope"}
        if not required <= set(row):
            raise ValueError("source-assertion annotation is incomplete")
        strings = (row["annotation_id"], row["evidence_ref"], row["claim_id"])
        if any(not isinstance(value, str) or not value.strip() for value in strings):
            raise ValueError("source-assertion identifiers must be non-empty strings")
        if not isinstance(row["relation"], str) or row["relation"] not in {"supports", "contradicts", "mentions_only", "unknown"}:
            raise ValueError("unsupported source-assertion relation")
        if not isinstance(row["temporal_scope"], str) or row["temporal_scope"] not in {"current", "historical", "unknown"}:
            raise ValueError("unsupported source-assertion temporal scope")
        value = row["value"]
        if value is not None and not isinstance(value, str):
            raise ValueError("source-assertion value must be a string or null")
        provenance = row.get("annotation_provenance", "t11-evidence-trust-cases-v1.0.0:hand-authored-synthetic")
        if not isinstance(provenance, str) or not provenance:
            raise ValueError("source-assertion provenance must be explicit")
        return cls(
            annotation_id=row["annotation_id"],
            evidence_ref=row["evidence_ref"],
            claim_id=row["claim_id"],
            relation=row["relation"],
            value=value,
            temporal_scope=row["temporal_scope"],
            annotation_provenance=provenance,
        )


@dataclass(frozen=True, slots=True)
class ObservationAssessment:
    annotation_id: str
    annotation_provenance: str
    evidence_ref: str
    claim_id: str
    relation: str
    value: str | None
    temporal_scope: str
    anchor: AnchorCheck
    source_ref: tuple[str, str, int, str]
    source_availability: str | None
    source_published_at: str | None
    source_collected_at: str | None
    source_recorded_at: str | None
    source_registration_at: str | None
    source_registration_method: str | None
    applicability_reason_codes: tuple[str, ...]
    source_type: str | None
    source_origin: str | None
    source_publisher_id: str | None
    publisher_root_id: str | None
    syndication_group_id: str | None
    applicable_as_of: bool


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    claim_id: str
    valid_as_of: str | None
    known_as_of: str | None
    status: ClaimStatus
    source_assertion_state: str
    evidence_refs: tuple[str, ...]
    verified_evidence_refs: tuple[str, ...]
    asserted_values: tuple[str, ...]
    observations: tuple[ObservationAssessment, ...]
    distinct_supporting_publisher_roots: int
    reason_codes: tuple[str, ...]
    final_status: Literal["not_confirmed"] = "not_confirmed"


@dataclass(frozen=True, slots=True)
class ProvenanceSummary:
    copy_count: int
    independent_root_count: int
    publisher_root_ids: tuple[str, ...]
    syndication_groups: tuple[tuple[str, str], ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerPolicyResult:
    eligible_for_owner_review: bool
    decision: Literal["eligible_for_explicit_owner_review", "not_eligible"]
    policy_id: str | None
    policy_version: str | None
    policy_hash: str | None
    reason_codes: tuple[str, ...]
    final_status: Literal["not_confirmed"] = "not_confirmed"


def project_catalog_record(catalog_row: Mapping[str, Any]) -> dict[str, Any]:
    """Select the normative EvidenceRecord fields from a richer test-catalog row."""
    names = set(SCHEMA_TYPES["EvidenceRecord"].model_fields)
    if not names <= set(catalog_row):
        raise ValueError("catalog row is missing normative EvidenceRecord fields")
    return {name: deepcopy(catalog_row[name]) for name in sorted(names)}


def check_anchor(record_payload: Mapping[str, Any], source: Mapping[str, Any]) -> AnchorCheck:
    """Recheck identity, immutable-source hash, and exact locator integrity.

    The returned `verified` state only means that the cited content is present
    in this supplied immutable snapshot. It is never a statement about truth.
    """
    if not isinstance(source, Mapping):
        return _anchor_result(
            AnchorIntegrity.UNAVAILABLE, ("source_snapshot_invalid",), None,
            None, None, None, None, None, None,
            _optional_string(record_payload.get("verification")) if isinstance(record_payload, Mapping) else None,
        )
    source_id = _optional_string(source.get("document_id"))
    source_version = source.get("version") if type(source.get("version")) is int else None
    source_hash = _optional_string(source.get("content_hash"))
    locator = record_payload.get("locator") if isinstance(record_payload, Mapping) else None
    locator = locator if isinstance(locator, Mapping) else {}
    locator_kind = _optional_string(locator.get("kind"))
    locator_start = locator.get("start") if type(locator.get("start")) is int else None
    locator_end = locator.get("end") if type(locator.get("end")) is int else None
    quote_hash = _optional_string(locator.get("quote_hash"))
    declared_verification = _optional_string(record_payload.get("verification")) if isinstance(record_payload, Mapping) else None

    try:
        wire_payload = json.dumps(dict(record_payload), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        record = SCHEMA_TYPES["EvidenceRecord"].model_validate_json(wire_payload, strict=True)
    except (ValidationError, TypeError, ValueError):
        return _anchor_result(
            AnchorIntegrity.INVALID, ("evidence_record_dto_invalid",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )

    if record.source_ref.owner != "Documents":
        return _anchor_result(
            AnchorIntegrity.UNAVAILABLE, ("unsupported_source_owner",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )
    if source.get("availability") != "available" or not isinstance(source.get("text"), str):
        return _anchor_result(
            AnchorIntegrity.UNAVAILABLE, ("source_content_unavailable",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )
    if source_id != record.source_ref.object_id:
        return _anchor_result(
            AnchorIntegrity.INVALID, ("source_identity_mismatch",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )
    if source_version != record.source_ref.revision:
        return _anchor_result(
            AnchorIntegrity.INVALID, ("source_version_mismatch",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )

    actual_hash = _hash_text(source["text"])
    if source_hash != actual_hash:
        return _anchor_result(
            AnchorIntegrity.INVALID, ("source_content_hash_mismatch",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )
    if record.source_hash != actual_hash or record.source_ref.hash != actual_hash:
        return _anchor_result(
            AnchorIntegrity.INVALID, ("evidence_source_hash_mismatch",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )

    if locator_kind == "text_span":
        start, end = locator_start, locator_end
        text = source["text"]
        if start is None or end is None or start < 0 or end > len(text) or start >= end:
            return _anchor_result(
                AnchorIntegrity.INVALID, ("text_span_out_of_bounds_or_empty",), source_id,
                source_version, source_hash, locator_kind, locator_start, locator_end,
                quote_hash, declared_verification,
            )
        actual_quote_hash = _hash_text(text[start:end])
        if quote_hash != actual_quote_hash:
            return _anchor_result(
                AnchorIntegrity.INVALID, ("quote_hash_mismatch",), source_id,
                source_version, source_hash, locator_kind, locator_start, locator_end,
                quote_hash, declared_verification,
            )
    elif locator_kind != "whole_artifact":
        return _anchor_result(
            AnchorIntegrity.INVALID, ("unsupported_locator_kind",), source_id,
            source_version, source_hash, locator_kind, locator_start, locator_end,
            quote_hash, declared_verification,
        )

    reasons = ("record_declared_unverified",) if record.verification.value == "unverified" else ()
    result = _anchor_result(
        AnchorIntegrity.VERIFIED, reasons, source_id, source_version, source_hash,
        locator_kind, locator_start, locator_end, quote_hash, declared_verification,
    )
    logger.debug("anchor check integrity=%s reasons=%s", result.integrity.value, ",".join(result.reason_codes))
    return result


def _time_slice_applicability(
    source: Mapping[str, Any],
    *,
    valid_as_of: datetime | None,
    known_as_of: datetime | None,
) -> tuple[bool, tuple[str, ...], str | None, str | None]:
    """Apply valid-time publication and knowledge-time registration cutoffs separately.

    A source with no usable registration timestamp is not assumed to have been
    known. When both collection and storage timestamps are supplied, the later
    timestamp bounds when the material could have entered a historical view.
    """
    reasons: set[str] = set()
    registered: list[tuple[str, datetime]] = []
    for field in ("collected_at", "recorded_at"):
        raw = source.get(field)
        if raw is None or raw == "":
            continue
        try:
            registered.append((field, _parse_timestamp(raw)))
        except ValueError:
            reasons.add("source_registration_time_invalid")
            return False, tuple(sorted(reasons)), None, None

    registration_at: str | None = None
    registration_method: str | None = None
    if not registered:
        reasons.add("source_registration_time_missing")
    else:
        latest = max(value for _, value in registered)
        registration_at = latest.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        latest_fields = sorted(field for field, value in registered if value == latest)
        registration_method = "+".join(latest_fields)
        if known_as_of is not None and latest > known_as_of:
            reasons.add("source_registered_after_knowledge_snapshot")

    if valid_as_of is not None:
        published_at = source.get("published_at")
        if not isinstance(published_at, str) or not published_at:
            reasons.add("source_publication_time_missing")
        else:
            try:
                publication_time = _parse_timestamp(published_at)
            except ValueError:
                reasons.add("source_publication_time_invalid")
            else:
                if publication_time > valid_as_of:
                    reasons.add("future_source_not_applicable")

    return not reasons, tuple(sorted(reasons)), registration_at, registration_method


def assess_claim(
    claim_id: str,
    assertions: Sequence[SourceAssertion],
    records_by_id: Mapping[str, Mapping[str, Any]],
    sources_by_id: Mapping[str, Mapping[str, Any]],
    *,
    valid_as_of: str | None = None,
    known_as_of: str | None = None,
) -> ClaimAssessment:
    """Assess explicit source-assertion annotations in a bitemporal snapshot."""
    if not isinstance(claim_id, str) or not claim_id.strip():
        raise ValueError("claim_id must be a non-empty string")
    valid_cutoff = _parse_timestamp(valid_as_of) if valid_as_of is not None else None
    known_cutoff = _parse_timestamp(known_as_of) if known_as_of is not None else None
    matching = sorted(
        (item for item in assertions if item.claim_id == claim_id),
        key=lambda item: (item.evidence_ref, item.annotation_id),
    )
    observations: list[ObservationAssessment] = []
    reasons: set[str] = set()
    seen_annotations: set[str] = set()
    for item in matching:
        if item.annotation_id in seen_annotations:
            reasons.add("duplicate_annotation_id")
            continue
        seen_annotations.add(item.annotation_id)
        record = records_by_id.get(item.evidence_ref)
        if record is None:
            reasons.add("evidence_ref_missing")
            continue
        source_ref = record.get("source_ref")
        if not isinstance(source_ref, Mapping):
            reasons.add("source_ref_missing")
            continue
        source_id = source_ref.get("object_id")
        if not isinstance(source_id, str) or source_id not in sources_by_id:
            reasons.add("source_snapshot_missing")
            continue
        source = sources_by_id[source_id]
        anchor = check_anchor(record, source)
        if anchor.integrity is not AnchorIntegrity.VERIFIED:
            reasons.update(anchor.reason_codes)
        applicable, applicability_reasons, registration_at, registration_method = _time_slice_applicability(
            source, valid_as_of=valid_cutoff, known_as_of=known_cutoff,
        )
        reasons.update(applicability_reasons)
        raw_revision = source_ref.get("revision")
        revision = raw_revision if type(raw_revision) is int else -1
        ref_fields = (
            str(source_ref.get("owner", "")), str(source_id), revision,
            str(source_ref.get("hash", "")),
        )
        observations.append(ObservationAssessment(
            annotation_id=item.annotation_id,
            annotation_provenance=item.annotation_provenance,
            evidence_ref=item.evidence_ref,
            claim_id=item.claim_id,
            relation=item.relation,
            value=item.value,
            temporal_scope=item.temporal_scope,
            anchor=anchor,
            source_ref=ref_fields,
            source_availability=_optional_string(source.get("availability")),
            source_published_at=_optional_string(source.get("published_at")),
            source_collected_at=_optional_string(source.get("collected_at")),
            source_recorded_at=_optional_string(source.get("recorded_at")),
            source_registration_at=registration_at,
            source_registration_method=registration_method,
            applicability_reason_codes=applicability_reasons,
            source_type=_optional_string(source.get("source_type")),
            source_origin=_optional_string(source.get("origin")),
            source_publisher_id=_optional_string(source.get("publisher_id")),
            publisher_root_id=_optional_string(source.get("publisher_root_id")),
            syndication_group_id=_optional_string(source.get("syndication_group_id")),
            applicable_as_of=applicable,
        ))

    usable = [
        row for row in observations
        if row.anchor.integrity is AnchorIntegrity.VERIFIED and row.applicable_as_of
    ]
    current = [row for row in usable if row.temporal_scope == "current"]
    historical = [row for row in usable if row.temporal_scope == "historical"]
    positive = [row for row in current if row.relation == "supports"]
    negative = [row for row in current if row.relation == "contradicts"]
    mentions = [row for row in current if row.relation == "mentions_only"]
    any_mentions = [row for row in usable if row.relation == "mentions_only"]
    values = {row.value for row in (*positive, *negative) if row.value is not None}
    evidence_refs = tuple(sorted({item.evidence_ref for item in matching}))
    verified_evidence_refs = tuple(sorted({row.evidence_ref for row in usable}))
    roots = tuple(sorted({row.publisher_root_id for row in positive if row.publisher_root_id}))

    if positive and negative:
        status = ClaimStatus.DISPUTED
        reasons.add("support_and_contradiction_present")
    elif len(values) > 1:
        status = ClaimStatus.DISPUTED
        reasons.add("conflicting_current_values")
    elif negative:
        status = ClaimStatus.DISPUTED
        reasons.add("claim_contradicted_by_source_annotation")
    elif positive:
        status = ClaimStatus.SUPPORTED_UNCONFIRMED
    elif historical:
        status = ClaimStatus.HISTORICAL
        reasons.add("historical_assertion_not_current")
    elif mentions or any_mentions:
        status = ClaimStatus.UNKNOWN
        reasons.add("source_mentions_but_does_not_assert_claim")
    elif observations and all(row.anchor.integrity is not AnchorIntegrity.VERIFIED for row in observations):
        status = ClaimStatus.UNVERIFIED
    else:
        status = ClaimStatus.UNKNOWN
        if not observations:
            reasons.add("no_evidence_or_source_assertion")
        elif not any(row.applicable_as_of for row in observations):
            reasons.add("no_source_applicable_at_snapshot")
        else:
            reasons.add("insufficient_assertion_for_claim")

    relations = {row.relation for row in usable}
    if status is ClaimStatus.UNVERIFIED or reasons.intersection({
        "evidence_ref_missing", "source_ref_missing", "source_snapshot_missing",
    }):
        assertion_state = "unverified"
    elif positive and negative:
        assertion_state = "mixed"
    elif positive:
        assertion_state = "asserts"
    elif negative:
        assertion_state = "contradicts"
    elif mentions or any_mentions:
        assertion_state = "mentions_only"
    elif historical:
        assertion_state = "historical"
    elif relations:
        assertion_state = "unknown"
    else:
        assertion_state = "none"

    result = ClaimAssessment(
        claim_id=claim_id,
        valid_as_of=valid_as_of,
        known_as_of=known_as_of,
        status=status,
        source_assertion_state=assertion_state,
        evidence_refs=evidence_refs,
        verified_evidence_refs=verified_evidence_refs,
        asserted_values=tuple(sorted(values)),
        observations=tuple(observations),
        distinct_supporting_publisher_roots=len(roots),
        reason_codes=tuple(sorted(reasons)),
    )
    logger.debug("claim assessment status=%s observations=%d reasons=%s", status.value, len(observations), ",".join(result.reason_codes))
    return result

def summarize_provenance(
    assertions: Sequence[SourceAssertion],
    records_by_id: Mapping[str, Mapping[str, Any]],
    sources_by_id: Mapping[str, Mapping[str, Any]],
) -> ProvenanceSummary:
    """Count exact cited records and known origins without assigning reliability."""
    evidence_refs: set[str] = set()
    roots: set[str] = set()
    groups: set[tuple[str, str]] = set()
    reasons: set[str] = set()
    for item in assertions:
        record = records_by_id.get(item.evidence_ref)
        if record is None:
            reasons.add("evidence_ref_missing")
            continue
        source_ref = record.get("source_ref")
        source_id = source_ref.get("object_id") if isinstance(source_ref, Mapping) else None
        source = sources_by_id.get(source_id) if isinstance(source_id, str) else None
        if source is None:
            reasons.add("source_snapshot_missing")
            continue
        if check_anchor(record, source).integrity is not AnchorIntegrity.VERIFIED:
            reasons.add("anchor_not_verified")
            continue
        evidence_refs.add(item.evidence_ref)
        root = _optional_string(source.get("publisher_root_id"))
        group = _optional_string(source.get("syndication_group_id"))
        if root is None:
            reasons.add("publisher_root_missing")
            continue
        roots.add(root)
        if group is not None:
            groups.add((root, group))
    return ProvenanceSummary(
        copy_count=len(evidence_refs),
        independent_root_count=len(roots),
        publisher_root_ids=tuple(sorted(roots)),
        syndication_groups=tuple(sorted(groups)),
        reason_codes=tuple(sorted(reasons)),
    )


def _canonical_policy_snapshot(policy: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        canonical = json.dumps(
            dict(policy), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        snapshot = json.loads(canonical)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(snapshot, dict):
        return None, None
    return snapshot, _hash_text(canonical)


def evaluate_owner_policy(
    statement_id: str,
    assessment: ClaimAssessment,
    assertions: Sequence[SourceAssertion],
    records_by_id: Mapping[str, Mapping[str, Any]],
    sources_by_id: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any] | None,
    *,
    dataset_id: str,
) -> OwnerPolicyResult:
    """Evaluate only the byte-for-byte-equivalent canonical test-only policy.

    The code-pinned digest prevents a caller-supplied mapping from changing the
    test allow-list. This is not a trusted production owner registry and never
    confirms the assessed claim.
    """
    reasons: set[str] = set()
    policy_id: str | None = None
    policy_version: str | None = None
    policy_hash: str | None = None
    policy_snapshot: dict[str, Any] | None = None
    if policy is None:
        reasons.add("explicit_owner_policy_missing")
    else:
        policy_snapshot, policy_hash = _canonical_policy_snapshot(policy)
        if policy_snapshot is None or policy_hash is None:
            reasons.add("policy_content_hash_unavailable")
            policy_snapshot = None
        else:
            policy_id = _optional_string(policy_snapshot.get("policy_id"))
            policy_version = _optional_string(policy_snapshot.get("version"))
            if policy_hash != TEST_OWNER_POLICY_CANONICAL_SHA256:
                reasons.add("policy_content_hash_mismatch")
            if policy_id != TEST_OWNER_POLICY_ID:
                reasons.add("unsupported_policy_id")
            if (
                policy_snapshot.get("schema") != TEST_OWNER_POLICY_SCHEMA
                or policy_version != TEST_OWNER_POLICY_VERSION
            ):
                reasons.add("unsupported_policy_schema_or_version")
            if (
                dataset_id != policy_snapshot.get("dataset_id")
                or dataset_id != TEST_OWNER_POLICY_DATASET_ID
            ):
                reasons.add("dataset_scope_mismatch")
            if policy_snapshot.get("scope") != "Named assertions in this provisional synthetic dataset only.":
                reasons.add("policy_scope_mismatch")
            if policy_snapshot.get("manual_approval") != "provisional":
                reasons.add("policy_provenance_not_provisional")
            if "No universal" not in str(policy_snapshot.get("explicit_non_policy", "")):
                reasons.add("policy_claims_universal_threshold")
            rules = policy_snapshot.get("rules")
            required_rule_fragments = (
                "at least two Evidence refs",
                "distinct publisher_root_id",
                "No unresolved same-time contradiction",
                "A verified anchor establishes only that a quote is present",
            )
            if not isinstance(rules, list) or any(
                not any(fragment in rule for rule in rules if isinstance(rule, str))
                for fragment in required_rule_fragments
            ):
                reasons.add("required_policy_guard_missing")
            authorized = policy_snapshot.get("authorized_statement_ids")
            if not isinstance(authorized, list) or statement_id not in authorized:
                reasons.add("statement_not_authorized")
            if statement_id != assessment.claim_id:
                reasons.add("statement_claim_mismatch")
            if assessment.status is not ClaimStatus.SUPPORTED_UNCONFIRMED:
                reasons.add("claim_not_unambiguously_supported")

    scoped = [
        item for item in assertions
        if item.claim_id == assessment.claim_id
        and item.relation == "supports"
        and item.temporal_scope == "current"
    ]
    assessed_observations = {
        (row.annotation_id, row.evidence_ref): row for row in assessment.observations
    }
    try:
        valid_cutoff = _parse_timestamp(assessment.valid_as_of) if assessment.valid_as_of is not None else None
        known_cutoff = _parse_timestamp(assessment.known_as_of) if assessment.known_as_of is not None else None
    except ValueError:
        valid_cutoff = None
        known_cutoff = None
        reasons.add("assessment_time_slice_invalid")

    valid_refs: set[str] = set()
    valid_roots: set[str] = set()
    for item in scoped:
        observed = assessed_observations.get((item.annotation_id, item.evidence_ref))
        record = records_by_id.get(item.evidence_ref)
        source_ref = record.get("source_ref") if record is not None else None
        source_id = source_ref.get("object_id") if isinstance(source_ref, Mapping) else None
        source = sources_by_id.get(source_id) if isinstance(source_id, str) else None
        if observed is None or not observed.applicable_as_of or source is None:
            reasons.add("supporting_source_not_applicable_at_snapshot")
            continue
        currently_applicable, time_reasons, _, _ = _time_slice_applicability(
            source, valid_as_of=valid_cutoff, known_as_of=known_cutoff,
        )
        if not currently_applicable:
            reasons.add("supporting_source_not_applicable_at_snapshot")
            reasons.update(time_reasons)
            continue
        if (
            record is None
            or observed.anchor.integrity is not AnchorIntegrity.VERIFIED
            or check_anchor(record, source).integrity is not AnchorIntegrity.VERIFIED
        ):
            reasons.add("supporting_anchor_not_verified")
            continue
        valid_refs.add(item.evidence_ref)
        root = _optional_string(source.get("publisher_root_id"))
        if root is None:
            reasons.add("supporting_publisher_root_missing")
        else:
            valid_roots.add(root)
    if len(valid_refs) < 2:
        reasons.add("insufficient_distinct_evidence_refs")
    if len(valid_roots) < 2:
        reasons.add("insufficient_independent_publisher_roots")

    eligible = not reasons
    return OwnerPolicyResult(
        eligible_for_owner_review=eligible,
        decision="eligible_for_explicit_owner_review" if eligible else "not_eligible",
        policy_id=policy_id,
        policy_version=policy_version,
        policy_hash=policy_hash,
        reason_codes=tuple(sorted(reasons)),
    )

def _anchor_result(
    integrity: AnchorIntegrity,
    reasons: tuple[str, ...],
    source_id: str | None,
    source_version: int | None,
    source_hash: str | None,
    locator_kind: str | None,
    locator_start: int | None,
    locator_end: int | None,
    quote_hash: str | None,
    declared_verification: str | None,
) -> AnchorCheck:
    logger.debug("anchor check integrity=%s reasons=%s", integrity.value, ",".join(reasons))
    return AnchorCheck(
        integrity=integrity,
        reason_codes=reasons,
        source_document_id=source_id,
        source_version=source_version,
        source_hash=source_hash,
        locator_kind=locator_kind,
        locator_start=locator_start,
        locator_end=locator_end,
        quote_hash=quote_hash,
        declared_verification=declared_verification,
    )


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed
