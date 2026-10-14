"""Deterministic T09 candidate retrieval and conservative resolution rules.

The module accepts only the normative, materialized Events DTOs. It neither
reads a database nor calls a model, embedding service, or network endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import logging
import re
from typing import Any, Iterable, Mapping, Sequence

from alfalab_contracts.models import SCHEMA_TYPES

logger = logging.getLogger(__name__)

ResolutionInput = SCHEMA_TYPES["ResolutionInput"]
ResolutionOutput = SCHEMA_TYPES["ResolutionOutput"]
EventMention = SCHEMA_TYPES["EventMention"]
EventRecord = SCHEMA_TYPES["EventRecord"]
EventDecision = SCHEMA_TYPES["EventDecision"]
EventChangeProposal = SCHEMA_TYPES["EventChangeProposal"]
ObjectRef = SCHEMA_TYPES["ObjectRef"]

METHOD_ID = "t09.deterministic-resolution-rules"
METHOD_VERSION = "1.0.0"
METHOD_HASH = "sha256:" + hashlib.sha256(b"t09-deterministic-resolution-rules:1.0.0").hexdigest()


@dataclass(frozen=True, slots=True)
class ResolutionPolicy:
    """Versioned experimental thresholds; values are ranking aids, not confidence."""

    same_event_window_days: int = 14
    near_name_candidate_threshold: float = 0.72
    candidate_limit: int = 20

    def __post_init__(self) -> None:
        if self.same_event_window_days < 0:
            raise ValueError("same_event_window_days must be non-negative")
        if not 0.0 <= self.near_name_candidate_threshold <= 1.0:
            raise ValueError("near_name_candidate_threshold must be between zero and one")
        if self.candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    """Explainable candidate retrieval result for one mention and event."""

    target: Any
    rank_score: float
    exact_event_type: bool
    shared_entity_ids: tuple[str, ...]
    near_name_pairs: tuple[tuple[str, str, float], ...]
    time_delta_days: int | None
    time_compatible: bool | None
    relation: str
    reasons: tuple[str, ...]


def canonical_json(value: Any) -> str:
    """Serialize deterministically using the spike's canonical JSON profile."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _event_type(value: Any) -> tuple[str, str, str]:
    ref = _dict(value)
    return (str(ref.get("namespace", "")), str(ref.get("code", "")), str(ref.get("version", "")))


def _entity_id(value: Any) -> str | None:
    if value is None:
        return None
    raw = _dict(value)
    entity_id = raw.get("entity_id")
    return str(entity_id) if entity_id else None


def _entity_name(value: Any) -> str:
    raw = _dict(value)
    return str(raw.get("display_name") or "")


def _entity_kind(value: Any) -> str:
    raw = _dict(value)
    kind = raw.get("kind") or {}
    return str(kind.get("id") or "")


def _mention_entities(mention: Any) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {"actor": {}, "object": {}}
    for role, values in (("actor", mention.actors), ("object", mention.objects)):
        for entity in values:
            raw = _dict(entity)
            entity_id = raw.get("entity_id")
            if entity_id:
                result[role][str(entity_id)] = raw
    return result


def _record_entities(record: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Extract participants exposed by EventRecord statements.

    Framework v1 EventRecord has no actor/object fields. For this experiment,
    statement subjects are actor-side participants and entity values are
    object-side participants. This mapping is a retrieval heuristic only.
    """
    result: dict[str, dict[str, dict[str, Any]]] = {"actor": {}, "object": {}}
    for statement in record.statements:
        subject = _dict(statement.subject)
        if subject.get("entity_id"):
            result["actor"][str(subject["entity_id"])] = subject
        value = _dict(statement.value)
        if value.get("kind") == "entity" and isinstance(value.get("value"), dict):
            entity = value["value"]
            if entity.get("entity_id"):
                result["object"][str(entity["entity_id"])] = entity
    return result


def _flatten_ids(entities: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> set[str]:
    return set(entities["actor"]) | set(entities["object"])


def _normalize_name(name: str) -> str:
    return " ".join(re.findall(r"[\w]+", name.casefold(), flags=re.UNICODE))


def _name_similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    left_kind = _entity_kind(left)
    right_kind = _entity_kind(right)
    if left_kind and right_kind and left_kind != right_kind:
        return 0.0
    a = _normalize_name(str(left.get("display_name", "")))
    b = _normalize_name(str(right.get("display_name", "")))
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mention_time(mention: Any) -> datetime | None:
    return _parse_time(mention.effective_at)


def _record_time(record: Any) -> datetime | None:
    # EventRecord has no effective_at. Prefer validity bounds; recorded_at is a
    # documented fallback for ranking only and is not treated as event time.
    parsed = []
    for statement in record.statements:
        validity = _dict(statement.validity)
        for key in ("valid_from", "valid_to"):
            stamp = _parse_time(validity.get(key))
            if stamp:
                parsed.append(stamp)
    if parsed:
        return min(parsed)
    return None


def _identity_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result = {key: _identity_payload(item) for key, item in value.items()}
        if result.get("entity_id"):
            result.pop("display_name", None)
        return result
    if isinstance(value, list):
        return [_identity_payload(item) for item in value]
    return value


def _statement_signature(statement: Any, *, include_validity: bool = True) -> str:
    raw = _dict(statement)
    raw.pop("statement_id", None)
    raw.pop("revision", None)
    raw.pop("provenance", None)
    # Certainty is compared by resolution policy, not event identity. An
    # upstream EventRecord may already have owner-confirmed the same assertion
    # that a new mention reports as observed; this difference must not create a
    # second event or count as a factual contradiction.
    raw.pop("epistemic_status", None)
    raw = _identity_payload(raw)
    if include_validity:
        validity = raw.get("validity", {})
        validity.pop("recorded_at", None)
    else:
        raw.pop("validity", None)
    return canonical_json(raw)


def _statement_core(statement: Any) -> str:
    return _statement_signature(statement, include_validity=False)


def _all_evidence_ids(input_data: Any, mentions: Sequence[Any]) -> dict[str, Any]:
    source_ids: set[str] = set()
    for mention in mentions:
        source_ids.update(ref.object_id for ref in mention.provenance.source_refs)
    result: dict[str, Any] = {}
    for evidence in input_data.evidence:
        if evidence.source_ref.object_id in source_ids:
            result[evidence.ref.object_id] = evidence.ref
    return result


def _evidence_for_mentions(input_data: Any, mentions: Sequence[Any]) -> list[Any]:
    source_ids = {
        ref.object_id
        for mention in mentions
        for ref in mention.provenance.source_refs
    }
    by_id = {
        evidence.ref.object_id: evidence.ref
        for evidence in input_data.evidence
        if evidence.source_ref.object_id in source_ids
    }
    for mention in mentions:
        for ref in mention.provenance.evidence_refs:
            by_id[ref.object_id] = ref
    return [by_id[key] for key in sorted(by_id)]


def retrieve_candidates(
    mention: Any,
    existing: Any,
    policy: ResolutionPolicy = ResolutionPolicy(),
) -> list[CandidateMatch]:
    """Retrieve plausible events; similarity only ranks and never authorizes a merge.

    Candidate keys are exact taxonomy version, exact participant IDs, same-role
    name-near matches, and (only when identities are absent) event type/time.
    Raw article text is not part of the normative ResolutionInput DTO.
    """
    mention_type = _event_type(mention.event_type)
    mention_entities = _mention_entities(mention)
    mention_ids = _flatten_ids(mention_entities)
    mention_time = _mention_time(mention)
    matches: list[CandidateMatch] = []

    for record in existing.events:
        if record.lifecycle.value != "active":
            continue
        exact_type = mention_type == _event_type(record.event_type)
        if not exact_type:
            continue
        record_entities = _record_entities(record)
        record_ids = _flatten_ids(record_entities)
        shared = tuple(sorted(mention_ids & record_ids))
        near_pairs: list[tuple[str, str, float]] = []
        for role in ("actor", "object"):
            for left_id, left in mention_entities[role].items():
                for right_id, right in record_entities[role].items():
                    if left_id == right_id:
                        continue
                    similarity = _name_similarity(left, right)
                    if similarity >= policy.near_name_candidate_threshold:
                        near_pairs.append((left_id, right_id, round(similarity, 4)))
        record_time = _record_time(record)
        delta: int | None = None
        time_compatible: bool | None = None
        if mention_time and record_time:
            delta = abs((mention_time - record_time).days)
            time_compatible = delta <= policy.same_event_window_days

        if not (shared or near_pairs or not mention_ids or not record_ids):
            continue
        # Same-name mismatch is a candidate for human review, never identity.
        score = 0.35 + (0.40 if shared else 0.0) + (0.20 if near_pairs else 0.0)
        if time_compatible is True:
            score += 0.05
        if time_compatible is False:
            score -= 0.25
        reasons = ["exact_event_type"]
        if shared:
            reasons.append("shared_entity_id")
        if near_pairs:
            reasons.append("near_name_only_requires_review")
        if delta is not None:
            reasons.append("event_time_compatible" if time_compatible else "event_time_separated")
        if not mention_ids or not record_ids:
            reasons.append("incomplete_identity")
        relation = "exact_identity" if shared and not near_pairs else "name_or_partial_candidate"
        matches.append(
            CandidateMatch(
                target=record,
                rank_score=max(0.0, min(1.0, round(score, 4))),
                exact_event_type=True,
                shared_entity_ids=shared,
                near_name_pairs=tuple(sorted(near_pairs)),
                time_delta_days=delta,
                time_compatible=time_compatible,
                relation=relation,
                reasons=tuple(reasons),
            )
        )

    matches.sort(key=lambda item: (-item.rank_score, item.target.ref.object_id, item.target.ref.revision))
    return matches[: policy.candidate_limit]


def _facts_are_exact(mention: Any, record: Any) -> bool:
    mention_signatures = {_statement_signature(item) for item in mention.statements}
    record_signatures = {_statement_signature(item) for item in record.statements}
    return bool(mention_signatures) and mention_signatures.issubset(record_signatures)


def _resolved_missing_paths(mention: Any, record: Any) -> set[str]:
    """Return only paths for which this mention supplies a semantically matching fact."""
    old_missing = {item.path for item in record.missing_data}
    resolved: set[str] = set()
    old_by_core: dict[str, list[Any]] = {}
    for statement in record.statements:
        old_by_core.setdefault(_statement_core(statement), []).append(statement)

    for statement in mention.statements:
        core = _statement_core(statement)
        for old in old_by_core.get(core, []):
            old_validity = _dict(old.validity)
            new_validity = _dict(statement.validity)
            for key in ("valid_from", "valid_to"):
                path = f"/event/{key}"
                if path in old_missing and not old_validity.get(key) and new_validity.get(key):
                    resolved.add(path)

    # A missing end date may also be represented as an unknown value in the
    # original assertion. Only the same predicate/subject changing to a time
    # value resolves that exact datum.
    if "/event/valid_to" in old_missing:
        old_unknown = {
            (
                _dict(item.predicate).get("namespace"),
                _dict(item.predicate).get("code"),
                _dict(item.subject).get("entity_id"),
            )
            for item in record.statements
            if _dict(item.value).get("kind") == "unknown"
        }
        for statement in mention.statements:
            key = (
                _dict(statement.predicate).get("namespace"),
                _dict(statement.predicate).get("code"),
                _dict(statement.subject).get("entity_id"),
            )
            if key in old_unknown and _dict(statement.value).get("kind") == "time":
                resolved.add("/event/valid_to")

    # Supplier completion requires a supplier-specific predicate and a new
    # entity target. Merely mentioning any new entity cannot resolve it.
    if "/event/successor_supplier" in old_missing:
        old_entities = _flatten_ids(_record_entities(record))
        known_event_versions = {
            str(raw["predicate"]["version"])
            for raw in (_dict(item) for item in record.statements)
            if raw["predicate"]["namespace"] == "alfalab.events"
        }
        for statement in mention.statements:
            raw = _dict(statement)
            value = raw["value"]
            predicate = raw["predicate"]
            if (
                predicate["namespace"] == "alfalab.events"
                and predicate["code"] == "identifies_supplier"
                and predicate["version"] in known_event_versions
                and value.get("kind") == "entity"
                and (value.get("value") or {}).get("kind", {}).get("id") == "entity.organization"
                and (value.get("value") or {}).get("entity_id") not in old_entities
            ):
                resolved.add("/event/successor_supplier")

    return resolved


def _fills_missing_detail(mention: Any, record: Any) -> bool:
    return bool(_resolved_missing_paths(mention, record))


def _facts_conflict(mention: Any, record: Any) -> bool:
    old_by_key: dict[tuple[str, str], set[str]] = {}
    for statement in record.statements:
        raw = _dict(statement)
        key = (str(raw["predicate"]["code"]), str(raw["subject"].get("entity_id", "")))
        old_by_key.setdefault(key, set()).add(canonical_json(_identity_payload(raw["value"])))
    for statement in mention.statements:
        raw = _dict(statement)
        key = (str(raw["predicate"]["code"]), str(raw["subject"].get("entity_id", "")))
        old_values = old_by_key.get(key)
        if old_values and canonical_json(_identity_payload(raw["value"])) not in old_values:
            # Validity refinement is compatible; changed asserted value is not.
            return True
    return False


def _uncertain(mention: Any) -> bool:
    if not mention.provenance.source_refs:
        return True
    if not (_mention_entities(mention)["actor"] or _mention_entities(mention)["object"]):
        return True
    return any(
        statement.epistemic_status in {"hypothetical", "disputed", "disproved", "unknown"}
        for statement in mention.statements
    )


def _has_identity_conflict(
    mention: Any,
    candidate: CandidateMatch,
    policy: ResolutionPolicy,
) -> bool:
    if candidate.near_name_pairs:
        return True
    mention_entities = _mention_entities(mention)
    record_entities = _record_entities(candidate.target)
    wrong_actor_roles = set(mention_entities["actor"]) & set(record_entities["object"])
    wrong_actor_roles -= set(record_entities["actor"])
    wrong_object_roles = set(mention_entities["object"]) & set(record_entities["actor"])
    wrong_object_roles -= set(record_entities["object"])
    if wrong_actor_roles or wrong_object_roles:
        return True
    for role in ("actor", "object"):
        left_ids = set(mention_entities[role])
        right_ids = set(record_entities[role])
        if left_ids and right_ids and not (left_ids & right_ids):
            # A lexical resemblance can retrieve, but cannot equate, legal or
            # facility identities. Non-similar disjoint objects usually signal
            # a separate event and are handled as a create below.
            if any(
                _name_similarity(mention_entities[role][a], record_entities[role][b])
                >= policy.near_name_candidate_threshold
                for a in left_ids
                for b in right_ids
            ):
                return True
    return False


def _record_payload(
    mention: Any,
    *,
    event_id: str,
    target_refs: Sequence[Any] = (),
    previous_records: Sequence[Any] = (),
    additional_mentions: Sequence[Any] = (),
    resolved_missing_paths: set[str] | None = None,
) -> dict[str, Any]:
    statements: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in previous_records:
        for statement in record.statements:
            raw = _dict(statement)
            signature = _merge_statement_signature(statement)
            if signature not in seen:
                seen.add(signature)
                statements.append(raw)
    all_mentions = [mention, *additional_mentions]
    for item in all_mentions:
        for statement in item.statements:
            raw = _dict(statement)
            signature = _merge_statement_signature(statement)
            if signature not in seen:
                seen.add(signature)
                statements.append(raw)
    statements.sort(key=lambda item: (item["statement_id"], item["revision"]))
    lineage = {_dict(ref)["object_id"]: _dict(ref) for ref in target_refs}
    for record in previous_records:
        lineage[record.ref.object_id] = _dict(record.ref)
    for ref in mention.provenance.source_refs:
        # Source refs are documents, not event lineage; do not put them here.
        _ = ref
    record_data: dict[str, Any] = {
        "event_type": _dict(mention.event_type),
        "lifecycle": "active",
        "statements": statements,
        "mention_ids": sorted({item.mention_id for item in all_mentions} | {mid for record in previous_records for mid in record.mention_ids}),
        "lineage_refs": [lineage[key] for key in sorted(lineage)],
        "missing_data": _missing_union(
            all_mentions,
            previous_records,
            resolved_missing_paths,
        ),
    }
    ref_data = {
        "owner": "Events",
        "object_id": event_id,
        "revision": 1,
        "hash": sha256_ref(record_data),
    }
    return {"ref": ref_data, **record_data}


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._:-]+", "-", value).strip("-.") or "unnamed"
    # EventRecord.ref.object_id has a 120-character contract maximum and the
    # caller prefixes the sanitized suffix with the 15-character event prefix.
    if cleaned == value and len(cleaned) <= 105:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    prefix = cleaned[:40].rstrip("-.") or "unnamed"
    return f"{prefix}-{digest}"


def _proposed_record(
    mention: Any,
    *,
    proposal_id: str,
    target_refs: Sequence[Any] = (),
    previous_records: Sequence[Any] = (),
    additional_mentions: Sequence[Any] = (),
    resolved_missing_paths: set[str] | None = None,
) -> Any:
    event_id = "event-proposal-" + _safe_id(proposal_id + "-" + mention.mention_id)
    return EventRecord.model_validate(
        _record_payload(
            mention,
            event_id=event_id,
            target_refs=target_refs,
            previous_records=previous_records,
            additional_mentions=additional_mentions,
            resolved_missing_paths=resolved_missing_paths,
        )
    )


def _proposal_provenance(input_data: Any, mentions: Sequence[Any]) -> dict[str, Any]:
    source_refs: dict[str, Any] = {}
    for mention in mentions:
        for ref in mention.provenance.source_refs:
            source_refs[ref.object_id] = _dict(ref)
    return {
        "origin": "derived",
        "source_refs": [source_refs[key] for key in sorted(source_refs)],
        "input_statement_refs": [],
        "producer_run_id": None,
        "derivation_method": {"id": METHOD_ID, "version": METHOD_VERSION, "hash": METHOD_HASH},
        "evidence_refs": _evidence_for_mentions(input_data, mentions),
        "origin_verified": False,
    }


def _decision(
    action: str,
    mentions: Sequence[Any],
    *,
    reason: str,
    target_refs: Sequence[Any] = (),
    proposed_events: Sequence[Any] = (),
    evidence_refs: Sequence[Any] = (),
) -> Any:
    if action == "defer":
        target_refs = ()
        proposed_events = ()
    return EventDecision.model_validate(
        {
            "action": action,
            "mention_ids": sorted({mention.mention_id for mention in mentions}),
            "target_refs": [_dict(ref) for ref in target_refs],
            "proposed_events": [_dict(event) for event in proposed_events],
            "reason": reason,
            "evidence_refs": [_dict(ref) for ref in evidence_refs],
        }
    )


def _merge_statement_signature(statement: Any) -> tuple[str, str, str]:
    raw = _dict(statement)
    return (
        _statement_signature(statement),
        str(raw["epistemic_status"]),
        canonical_json(raw["provenance"]),
    )


def _same_duplicate_group(records: Sequence[Any]) -> bool:
    if len(records) < 2:
        return False
    first = records[0]
    key = (
        _event_type(first.event_type),
        tuple(sorted(_flatten_ids(_record_entities(first)))),
        tuple(sorted(_merge_statement_signature(item) for item in first.statements)),
    )
    return all(
        (
            _event_type(record.event_type),
            tuple(sorted(_flatten_ids(_record_entities(record)))),
            tuple(sorted(_merge_statement_signature(item) for item in record.statements)),
        )
        == key
        for record in records[1:]
    )


def _has_distinct_facility_mentions(mentions: Sequence[Any]) -> bool:
    """Return true only when each same-source mention names disjoint facilities."""
    seen: set[str] = set()
    for mention in mentions:
        facilities = {
            entity_id
            for entity_id, entity in _mention_entities(mention)["object"].items()
            if _entity_kind(entity).rsplit(".", 1)[-1] == "facility"
        }
        if not facilities or seen.intersection(facilities):
            return False
        seen.update(facilities)
    return len(mentions) >= 2 and len(seen) >= 2


def _source_key(mention: Any) -> tuple[str, ...]:
    return tuple(sorted({ref.object_id for ref in mention.provenance.source_refs}))


def _mention_identity(mention: Any) -> tuple[Any, ...]:
    entities = _mention_entities(mention)
    return (
        _event_type(mention.event_type),
        tuple(sorted(entities["actor"])),
        tuple(sorted(entities["object"])),
        tuple(sorted(_statement_signature(item) for item in mention.statements)),
    )


def _missing_union(
    mentions: Sequence[Any],
    previous_records: Sequence[Any] = (),
    resolved_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    resolved = resolved_paths or set()
    for record in previous_records:
        for missing in record.missing_data:
            raw = _dict(missing)
            if raw["path"] not in resolved:
                values[canonical_json(raw)] = raw
    for mention in mentions:
        for missing in mention.missing_data:
            raw = _dict(missing)
            values[canonical_json(raw)] = raw
    return [values[key] for key in sorted(values)]


def propose_resolution(
    input_data: Any,
    policy: ResolutionPolicy = ResolutionPolicy(),
) -> Any:
    """Return an immutable proposal; caller/Events owner remains responsible for apply."""
    if not isinstance(input_data, ResolutionInput):
        input_data = ResolutionInput.model_validate(input_data)
    mentions = sorted(input_data.mentions, key=lambda item: item.mention_id)
    proposal_id = "t09-proposal-" + sha256_ref(
        {
            "snapshot": _dict(input_data.existing.slice),
            "mention_ids": [mention.mention_id for mention in mentions],
            "policy": _dict(input_data.policy),
            "runtime_policy": {
                "same_event_window_days": policy.same_event_window_days,
                "near_name_candidate_threshold": policy.near_name_candidate_threshold,
                "candidate_limit": policy.candidate_limit,
            },
        }
    )[7:27]
    decisions: list[Any] = []
    unresolved: set[str] = set()
    consumed: set[str] = set()

    # A split corrects one pre-existing aggregate containing several distinct
    # source mentions. Multiple events in a single article alone are separate
    # creates, not a split.
    by_source: dict[tuple[str, ...], list[Any]] = {}
    for mention in mentions:
        key = _source_key(mention)
        if key:
            by_source.setdefault(key, []).append(mention)
    for source_mentions in by_source.values():
        unique_types = {_event_type(item.event_type) for item in source_mentions}
        distinct_types = len(unique_types) > 1
        same_type_distinct_facilities = len(unique_types) == 1 and _has_distinct_facility_mentions(source_mentions)
        if len(source_mentions) < 2 or not (distinct_types or same_type_distinct_facilities):
            continue
        source_ids = {item.mention_id for item in source_mentions}
        split_targets = [
            record
            for record in input_data.existing.events
            if source_ids.issubset(set(record.mention_ids))
            and all(_facts_are_exact(item, record) for item in source_mentions)
            and {
                _statement_signature(statement)
                for statement in record.statements
            }
            == {
                _statement_signature(statement)
                for item in source_mentions
                for statement in item.statements
            }
        ]
        if len(split_targets) != 1:
            continue
        if any(_uncertain(item) for item in source_mentions):
            continue
        if len({_source_key(item) for item in source_mentions}) != 1:
            continue
        target = split_targets[0]
        proposed = [_proposed_record(item, proposal_id=proposal_id, target_refs=[target.ref]) for item in source_mentions]
        refs = _evidence_for_mentions(input_data, source_mentions)
        decisions.append(
            _decision(
                "split",
                source_mentions,
                reason="One source produced distinct event or facility mentions; preserve them as separate event records.",
                target_refs=[target.ref],
                proposed_events=proposed,
                evidence_refs=refs,
            )
        )
        consumed.update(item.mention_id for item in source_mentions)

    merge_groups: dict[tuple[str, ...], list[Any]] = {}
    merge_records: dict[tuple[str, ...], list[Any]] = {}
    for mention in mentions:
        if mention.mention_id in consumed or _uncertain(mention):
            continue
        candidates = retrieve_candidates(mention, input_data.existing, policy)
        exact_shared = [candidate for candidate in candidates if candidate.shared_entity_ids]
        records = [candidate.target for candidate in exact_shared]
        if len(records) < 2 or not _same_duplicate_group(records):
            continue
        if any(candidate.time_compatible is False for candidate in exact_shared):
            continue
        if not all(_facts_are_exact(mention, record) for record in records):
            continue
        key = tuple(sorted(f"{record.ref.object_id}@{record.ref.revision}" for record in records))
        merge_groups.setdefault(key, []).append(mention)
        merge_records[key] = records

    for key, grouped_mentions in sorted(merge_groups.items()):
        grouped_mentions.sort(key=lambda item: item.mention_id)
        records = merge_records[key]
        target_refs = [record.ref for record in records]
        successor = _proposed_record(
            grouped_mentions[0],
            proposal_id=proposal_id,
            target_refs=target_refs,
            previous_records=records,
            additional_mentions=grouped_mentions[1:],
        )
        decisions.append(
            _decision(
                "merge",
                grouped_mentions,
                reason="Equivalent event records share participant IDs and statement facts; preserve both predecessors.",
                target_refs=target_refs,
                proposed_events=[successor],
                evidence_refs=_evidence_for_mentions(input_data, grouped_mentions),
            )
        )
        consumed.update(item.mention_id for item in grouped_mentions)

    for mention in mentions:
        if mention.mention_id in consumed:
            continue
        candidates = retrieve_candidates(mention, input_data.existing, policy)

        exact_shared = [candidate for candidate in candidates if candidate.shared_entity_ids]
        if len(exact_shared) > 1:
            unresolved.add(mention.mention_id)
            decisions.append(
                _decision(
                    "defer",
                    [mention],
                    reason="Several candidate records are not proven duplicates; retain uncertainty.",
                    target_refs=[candidate.target.ref for candidate in candidates],
                    evidence_refs=_evidence_for_mentions(input_data, [mention]),
                )
            )
            consumed.add(mention.mention_id)
            continue

        candidate = candidates[0] if candidates else None
        if candidate is not None:
            # A similar name is candidate-retrieval evidence only. Never use it
            # to equate organizations, facilities, products, or canonical events.
            if candidate.near_name_pairs or _has_identity_conflict(mention, candidate, policy):
                unresolved.add(mention.mention_id)
                decisions.append(
                    _decision(
                        "defer",
                        [mention],
                        reason="Candidate identity depends on a similar or conflicting entity name; exact identity is not established.",
                        target_refs=[candidate.target.ref],
                        evidence_refs=_evidence_for_mentions(input_data, [mention]),
                    )
                )
                consumed.add(mention.mention_id)
                continue
            if candidate.time_compatible is False:
                # Recurring events at the same site are separate when the
                # supplied event times are outside this versioned window.
                candidate = None
            elif candidate.time_delta_days is None and mention.effective_at is None:
                unresolved.add(mention.mention_id)
                decisions.append(
                    _decision(
                        "defer",
                        [mention],
                        reason="Event time and identity are incomplete; the candidate cannot be resolved safely.",
                        target_refs=[candidate.target.ref],
                        evidence_refs=_evidence_for_mentions(input_data, [mention]),
                    )
                )
                consumed.add(mention.mention_id)
                continue
            elif _uncertain(mention):
                unresolved.add(mention.mention_id)
                decisions.append(
                    _decision(
                        "defer",
                        [mention],
                        reason="The mention is hypothetical, disputed, unknown, or lacks a usable source identity.",
                        target_refs=[candidate.target.ref],
                        evidence_refs=_evidence_for_mentions(input_data, [mention]),
                    )
                )
                consumed.add(mention.mention_id)
                continue
            elif candidate is not None:
                record = candidate.target
                if _fills_missing_detail(mention, record):
                    successor = _proposed_record(
                        mention,
                        proposal_id=proposal_id,
                        target_refs=[record.ref],
                        previous_records=[record],
                        resolved_missing_paths=_resolved_missing_paths(mention, record),
                    )
                    decisions.append(
                        _decision(
                            "correct",
                            [mention],
                            reason="The new mention supplies a previously missing event detail; predecessor history remains linked.",
                            target_refs=[record.ref],
                            proposed_events=[successor],
                            evidence_refs=_evidence_for_mentions(input_data, [mention]),
                        )
                    )
                elif _facts_conflict(mention, record):
                    unresolved.add(mention.mention_id)
                    decisions.append(
                        _decision(
                            "defer",
                            [mention],
                            reason="The candidate contains conflicting asserted values without an explicit correction authority.",
                            target_refs=[record.ref],
                            evidence_refs=_evidence_for_mentions(input_data, [mention]),
                        )
                    )
                elif _facts_are_exact(mention, record):
                    decisions.append(
                        _decision(
                            "attach",
                            [mention],
                            reason="Exact event type, participant IDs, compatible time, and statement facts support attachment.",
                            target_refs=[record.ref],
                            evidence_refs=_evidence_for_mentions(input_data, [mention]),
                        )
                    )
                else:
                    unresolved.add(mention.mention_id)
                    decisions.append(
                        _decision(
                            "defer",
                            [mention],
                            reason="The candidate shares identity but does not establish whether new facts extend or contradict it.",
                            target_refs=[record.ref],
                            evidence_refs=_evidence_for_mentions(input_data, [mention]),
                        )
                    )
                consumed.add(mention.mention_id)
                continue

        if _uncertain(mention):
            unresolved.add(mention.mention_id)
            decisions.append(
                _decision(
                    "defer",
                    [mention],
                    reason="The input lacks enough supported identity or certainty for a canonical event proposal.",
                    evidence_refs=_evidence_for_mentions(input_data, [mention]),
                )
            )
            consumed.add(mention.mention_id)
            continue

        # If no record remains a compatible candidate, create a separate event.
        # Event statements are copied as-is; evidence anchors do not upgrade status.
        proposed = _proposed_record(mention, proposal_id=proposal_id)
        decisions.append(
            _decision(
                "create",
                [mention],
                reason="No compatible existing event was retrieved; preserve the supplied mention as a new event.",
                proposed_events=[proposed],
                evidence_refs=_evidence_for_mentions(input_data, [mention]),
            )
        )
        consumed.add(mention.mention_id)

    decisions.sort(key=lambda item: (min(item.mention_ids, default=""), item.action.value))
    proposal = EventChangeProposal.model_validate(
        {
            "proposal_id": proposal_id,
            "source_snapshot": _dict(input_data.existing.slice),
            "decisions": [_dict(item) for item in decisions],
            "unresolved_mentions": [],
            "missing_data": _missing_union(mentions),
            "provenance": _proposal_provenance(input_data, mentions),
        }
    )
    logger.debug(
        "T09 resolution proposed: mentions=%d decisions=%d deferred=%d",
        len(mentions), len(decisions), len(unresolved),
    )
    return ResolutionOutput.model_validate({"proposal": _dict(proposal)})
