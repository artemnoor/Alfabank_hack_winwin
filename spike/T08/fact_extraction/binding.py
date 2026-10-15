"""Experimental, content-hashed code bindings for contract DTO projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alfalab_contracts import CodeRef, VersionedRef

from .errors import ExtractionValidationError
from .prompt import PROMPT_SHA256

DEFAULT_BINDING_PATH = Path(__file__).with_name("event-schema-spike-v1.json")
DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "taxonomy.json"


@dataclass(frozen=True)
class CandidateEvent:
    """A single event candidate selected upstream by T08/Policy v2.1."""

    code: str
    label: str
    definition: str
    include: str
    exclude: str


@dataclass(frozen=True)
class EventSchemaBinding:
    """Spike-local registry binding; it is not the registered T09 schema."""

    event_schema: VersionedRef
    event_namespace: str
    event_version: str
    event_codes: frozenset[str]
    predicate_refs: dict[str, CodeRef]
    entity_kind_refs: dict[str, VersionedRef]
    derivation_method: VersionedRef
    binding_status: str

    def event_code_ref(self, code: str) -> CodeRef:
        if code not in self.event_codes:
            raise ExtractionValidationError("event_code_not_in_schema_binding")
        return CodeRef(
            namespace=self.event_namespace,
            version=self.event_version,
            code=code,
        )


def load_experiment_binding(
    binding_path: Path = DEFAULT_BINDING_PATH,
    taxonomy_path: Path = DEFAULT_TAXONOMY_PATH,
) -> EventSchemaBinding:
    """Load pinned spike codes and refuse unregistered/mismatched categories."""
    try:
        raw = binding_path.read_bytes()
        spec = json.loads(raw)
        taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExtractionValidationError(
            "schema_binding_unavailable_or_invalid"
        ) from exc
    if not isinstance(spec, dict) or not isinstance(taxonomy, dict):
        raise ExtractionValidationError("schema_binding_unavailable_or_invalid")

    pinned_taxonomy_codes = {
        row.get("code") for row in taxonomy.get("events", []) if isinstance(row, dict)
    }
    bound_codes = spec.get("event_codes")
    if (
        not isinstance(bound_codes, list)
        or len(bound_codes) != len(set(bound_codes))
        or set(bound_codes) != pinned_taxonomy_codes
    ):
        raise ExtractionValidationError("schema_binding_event_codes_mismatch")

    schema_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    schema_ref = VersionedRef(id=spec["id"], version=spec["version"], hash=schema_hash)
    namespace = spec["event_namespace"]
    event_version = spec["event_version"]
    predicate_codes = spec.get("predicate_codes")
    if not isinstance(predicate_codes, dict) or set(predicate_codes) != {
        "event",
        "date",
        "location",
        "participant",
        "participant_role",
        "circumstance",
        "assertion_status",
    }:
        raise ExtractionValidationError("schema_binding_predicates_invalid")
    predicate_refs = {
        field: CodeRef(namespace=namespace, version=event_version, code=code)
        for field, code in predicate_codes.items()
    }
    entity_kinds = spec.get("entity_kinds")
    if not isinstance(entity_kinds, list) or set(entity_kinds) != {
        "organization",
        "person",
        "place",
        "government",
        "group",
        "unknown",
    }:
        raise ExtractionValidationError("schema_binding_entity_kinds_invalid")
    entity_kind_refs = {
        kind: VersionedRef(
            id=f"{spec['id']}/entity-kind/{kind}",
            version=spec["version"],
            hash=schema_hash,
        )
        for kind in entity_kinds
    }
    derivation_method = VersionedRef(
        id="t08-deepseek-fact-extraction-prompt",
        version="1.0.0",
        hash=PROMPT_SHA256,
    )
    return EventSchemaBinding(
        event_schema=schema_ref,
        event_namespace=namespace,
        event_version=event_version,
        event_codes=frozenset(bound_codes),
        predicate_refs=predicate_refs,
        entity_kind_refs=entity_kind_refs,
        derivation_method=derivation_method,
        binding_status=spec.get("status", "unknown"),
    )


def candidates_from_t08(
    codes: list[str], taxonomy: dict[str, Any], binding: EventSchemaBinding
) -> list[CandidateEvent]:
    """Resolve only T08-released candidate codes; abstains cannot be promoted."""
    rows = taxonomy.get("events")
    if not isinstance(rows, list):
        raise ExtractionValidationError("t08_taxonomy_invalid")
    by_code = {row.get("code"): row for row in rows if isinstance(row, dict)}
    candidates: list[CandidateEvent] = []
    for code in codes:
        if code not in binding.event_codes or code not in by_code:
            raise ExtractionValidationError("jev_candidate_not_in_pinned_schema")
        row = by_code[code]
        candidates.append(
            CandidateEvent(
                code=code,
                label=row["label"],
                definition=row["definition"],
                include=row["include"],
                exclude=row["exclude"],
            )
        )
    if len({candidate.code for candidate in candidates}) != len(candidates):
        raise ExtractionValidationError("duplicate_jev_candidates")
    return candidates
