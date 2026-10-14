"""Typed graph projection over explicit Framework v1 statements.

This module deliberately does not perform entity matching or read owner state.
An exact StatementRef index and aggregate references must be supplied by the
caller when direct edges are to be emitted.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from alfalab_contracts.models import (
    BuildGraphInput,
    BuildGraphOutput,
    CodeRef,
    EntityRef,
    EntityValue,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    KnowledgeSlice,
    MissingDatum,
    ObjectRef,
    ProjectionManifest,
    Provenance,
    Statement,
    StatementRef,
    UnknownValue,
    VersionedRef,
)
from alfalab_contracts.semantics import validate_dto

logger = logging.getLogger(__name__)

BUILDER_REF = VersionedRef(
    id="spike.t12.explicit-statement-projector",
    version="0.2.0",
    hash="sha256:bd27391f93eaccb57cc8473e4627da7446320de01314f40f7de2886790e2d76b",
)

DEFAULT_RELATION_CODES = (
    "purchases_from",
    "supplies",
    "uses_component",
    "uses_material",
    "located_in",
    "operates_at",
    "ships_via",
    "stores_at",
    "passes_through",
    "depends_on_country",
)

DEFAULT_NEGATIVE_PREDICATES = frozenset(
    {("alfalab.business", "1.0.1", "does_not_source_from_country")}
)


class GraphBuildError(ValueError):
    """An input cannot safely be projected under the declared ontology/rules."""


@dataclass(frozen=True)
class GraphRules:
    """Explicit predicate-to-relation map for one ontology version."""

    ref: VersionedRef
    ontology: VersionedRef
    predicate_map: Mapping[tuple[str, str, str], CodeRef]
    negative_predicates: frozenset[tuple[str, str, str]] = DEFAULT_NEGATIVE_PREDICATES


@dataclass(frozen=True)
class PreservedStatement:
    """Local sidecar record for a source assertion not encoded as a graph edge."""

    statement: Statement
    reason: str
    statement_ref: StatementRef | None


@dataclass(frozen=True)
class TemporalEdgeContext:
    """Spike sidecar for validity bounds omitted from the normative GraphEdge DTO."""

    edge_id: str
    statement_id: str
    statement_revision: int
    epistemic_status: str
    valid_from: str | None
    valid_to: str | None
    recorded_at: str
    statement_ref: StatementRef | None
    input_statement_refs: tuple[StatementRef, ...]


@dataclass(frozen=True)
class BuildArtifacts:
    """Contract output plus spike-only records that GraphSnapshot cannot express."""

    output: BuildGraphOutput
    preserved_statements: tuple[PreservedStatement, ...]
    temporal_edge_contexts: tuple[TemporalEdgeContext, ...]


def canonical_bytes(value: object) -> bytes:
    """Framework-local canonical-json-v1 subset: UTF-8, sorted keys, compact."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_statement_hash(statement: Statement) -> str:
    return canonical_hash(statement)


def default_graph_rules(
    ontology: VersionedRef,
    *,
    relation_codes: Sequence[str] = DEFAULT_RELATION_CODES,
    ref: VersionedRef | None = None,
) -> GraphRules:
    """Create an explicit identity-code mapping for the supplied ontology.

    Predicate names are copied only for the enumerated allowlist. No text,
    display-name, product, or industry similarity is consulted.
    """
    mappings = {
        ("alfalab.business", "1.0.1", code): CodeRef(
            namespace=ontology.id,
            version=ontology.version,
            code=code,
        )
        for code in relation_codes
    }
    return GraphRules(
        ref=ref
        or VersionedRef(
            id="spike.t12.rules.explicit-predicate-map",
            version="0.1.0",
            hash="sha256:9e58d4a0c69bff52ce9c266ab08d1323469c12179221b82e603e36a49f851f87",
        ),
        ontology=ontology,
        predicate_map=mappings,
    )


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise GraphBuildError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _statement_in_scope(statement: Statement, request: BuildGraphInput) -> tuple[bool, str | None]:
    known_as_of = _timestamp(request.knowledge.as_of.known_as_of)
    valid_as_of = _timestamp(request.knowledge.as_of.valid_as_of)
    recorded_at = _timestamp(statement.validity.recorded_at)
    if recorded_at > known_as_of:
        return False, "not_known_at_cut"
    valid_from = statement.validity.valid_from
    valid_to = statement.validity.valid_to
    if valid_from is None:
        return False, "valid_from_unknown"
    if _timestamp(valid_from) > valid_as_of:
        return False, "not_yet_valid"
    if valid_to is not None and _timestamp(valid_to) <= valid_as_of:
        return False, "expired_at_cut"
    return True, None


def _slice_key(item: KnowledgeSlice) -> tuple[str, str, str]:
    return (str(item.owner), item.partition_id, item.selection_key)


def _aggregate_ref_is_declared(
    ref: StatementRef,
    knowledge_slices: Sequence[KnowledgeSlice],
    aggregate_refs: Sequence[ObjectRef],
) -> bool:
    aggregate = ref.aggregate_ref
    slice_matches = any(
        str(slice_.owner) == str(aggregate.owner)
        and slice_.partition_id == aggregate.object_id
        and slice_.revision == aggregate.revision
        for slice_ in knowledge_slices
    )
    return slice_matches and any(aggregate == declared for declared in aggregate_refs)


def _checked_ref(
    statement: Statement,
    ref: StatementRef | None,
    request: BuildGraphInput,
    aggregate_refs: Sequence[ObjectRef],
) -> StatementRef | None:
    if ref is None:
        return None
    if ref.statement_id != statement.statement_id or ref.revision != statement.revision:
        raise GraphBuildError("statement reference identity does not match its inline statement")
    if ref.hash != canonical_statement_hash(statement):
        raise GraphBuildError("statement reference hash does not match canonical statement content")
    if not _aggregate_ref_is_declared(ref, request.knowledge.slices, aggregate_refs):
        raise GraphBuildError("statement aggregate reference is not among the explicitly supplied slices")
    return ref


def _ref_key(ref: StatementRef) -> tuple[str, int]:
    return (ref.statement_id, ref.revision)


def _missing(path: str, reason: str, detail: str) -> MissingDatum:
    return MissingDatum(path=path, reason=reason, detail=detail)


def _merge_refs(refs: Sequence[StatementRef]) -> list[StatementRef]:
    by_key: dict[tuple[str, int], StatementRef] = {}
    for ref in refs:
        by_key[_ref_key(ref)] = ref
    return [by_key[key] for key in sorted(by_key)]


def _merge_object_refs(refs: Sequence[ObjectRef]) -> list[ObjectRef]:
    by_key = {
        (str(ref.owner), ref.object_id, ref.revision, ref.hash): ref
        for ref in refs
    }
    return [by_key[key] for key in sorted(by_key)]


def _stable_graph_id(prefix: str, raw_id: str) -> str:
    candidate = f"{prefix}-{raw_id}"
    if len(candidate) <= 120:
        return candidate
    return f"{prefix}-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:32]}"


def _stable_edge_id(statement: Statement, source_refs: Sequence[StatementRef]) -> str:
    identity = {
        "statement_id": statement.statement_id,
        "revision": statement.revision,
        "source_refs": sorted(
            (reference.model_dump(mode="json") for reference in source_refs),
            key=canonical_bytes,
        ),
    }
    return _stable_graph_id("edge", hashlib.sha256(canonical_bytes(identity)).hexdigest())


def build_graph(
    request: BuildGraphInput,
    *,
    statement_ref_index: Mapping[tuple[str, int], StatementRef],
    aggregate_refs: Sequence[ObjectRef],
    rules: GraphRules,
) -> BuildArtifacts:
    """Build revision-zero candidate using only explicitly supplied statements.

    Direct graph edges are omitted unless an exact StatementRef and its source
    aggregate ObjectRef are supplied. Inferred edges may use only the exact
    input StatementRefs carried by the source statement's provenance.
    """
    if rules.ontology != request.ontology:
        raise GraphBuildError("rules ontology does not match BuildGraphInput ontology")
    if rules.ref != request.rules:
        raise GraphBuildError("rules reference does not match BuildGraphInput rules")
    if len({_slice_key(item) for item in request.knowledge.slices}) != len(request.knowledge.slices):
        raise GraphBuildError("knowledge slices must be unique")

    entities: dict[str, EntityRef] = {}
    for entity in request.knowledge.entities:
        prior = entities.get(entity.entity_id)
        if prior is not None and prior.kind != entity.kind:
            raise GraphBuildError("same explicit entity ID has conflicting entity kinds")
        if prior is not None and prior.display_name != entity.display_name:
            raise GraphBuildError("same explicit entity ID has conflicting supplied display names")
        entities[entity.entity_id] = entity

    statements: dict[tuple[str, int], Statement] = {}
    for statement in request.knowledge.statements:
        key = (statement.statement_id, statement.revision)
        if key in statements:
            raise GraphBuildError("duplicate statement ID/revision in KnowledgeSnapshot")
        statements[key] = statement
        if statement.subject.entity_id not in entities:
            raise GraphBuildError("statement subject is absent from the explicit entity catalog")
        if statement.value.kind == "entity" and statement.value.value.entity_id not in entities:
            raise GraphBuildError("statement target is absent from the explicit entity catalog")

    resolved_refs: dict[tuple[str, int], StatementRef] = {}
    for key, ref in statement_ref_index.items():
        statement = statements.get(key)
        if statement is None:
            raise GraphBuildError("StatementRef index contains a reference absent from KnowledgeSnapshot")
        checked = _checked_ref(statement, ref, request, aggregate_refs)
        if checked is not None:
            resolved_refs[key] = checked

    missing: dict[tuple[str, str, str], MissingDatum] = {}
    preserved: list[PreservedStatement] = []
    temporal_contexts: list[TemporalEdgeContext] = []
    node_statement_refs: dict[str, list[StatementRef]] = {entity_id: [] for entity_id in entities}
    edges: list[GraphEdge] = []

    in_scope: list[Statement] = []
    for statement in sorted(request.knowledge.statements, key=lambda s: (s.statement_id, s.revision)):
        in_scope_result, exclusion = _statement_in_scope(statement, request)
        ref = resolved_refs.get((statement.statement_id, statement.revision))
        if not in_scope_result:
            preserved.append(PreservedStatement(statement, exclusion or "out_of_scope", ref))
            if statement.epistemic_status == "unknown" or statement.value.kind == "unknown":
                reason_text = statement.value.reason if statement.value.kind == "unknown" else "Statement epistemic status is unknown."
                path = f"/statements/{statement.statement_id}"
                missing[(path, "not_provided", reason_text)] = _missing(path, "not_provided", reason_text)
            elif exclusion == "valid_from_unknown":
                path = f"/statements/{statement.statement_id}"
                detail = "The statement has no valid_from bound; current graph membership is unknown."
                missing[(path, "unavailable", detail)] = _missing(path, "unavailable", detail)
            continue
        in_scope.append(statement)
        if ref is not None:
            node_statement_refs[statement.subject.entity_id].append(ref)
            if statement.value.kind == "entity":
                node_statement_refs[statement.value.value.entity_id].append(ref)

    for statement in in_scope:
        key = (statement.statement_id, statement.revision)
        ref = resolved_refs.get(key)
        predicate_key = (
            statement.predicate.namespace,
            statement.predicate.version,
            statement.predicate.code,
        )
        path = f"/statements/{statement.statement_id}"

        if predicate_key in rules.negative_predicates:
            preserved.append(PreservedStatement(statement, "explicit_negative_not_graph_edge", ref))
            missing[(path, "unsupported", "negative assertion remains in T12 sidecar; GraphEdge has no polarity field")] = _missing(
                path,
                "unsupported",
                "Negative assertion remains in the spike sidecar because GraphEdge has no explicit polarity field.",
            )
            continue

        if statement.epistemic_status == "disproved":
            preserved.append(PreservedStatement(statement, "disproved_not_projected", ref))
            missing[(path, "unsupported", "disproved relationship cannot be represented as a positive graph edge")] = _missing(
                path,
                "unsupported",
                "Disproved relationship is preserved in the sidecar and is not projected as a graph edge.",
            )
            continue

        if statement.epistemic_status == "hypothetical":
            preserved.append(PreservedStatement(statement, "hypothetical_not_projected_as_fact", ref))
            missing[(path, "unsupported", "hypothetical candidate is not a factual graph edge")] = _missing(
                path,
                "unsupported",
                "Hypothetical assertion is preserved in the spike sidecar and is not projected as a factual edge.",
            )
            continue

        if statement.epistemic_status == "unknown" or statement.value.kind == "unknown":
            reason_text = statement.value.reason if statement.value.kind == "unknown" else "Statement epistemic status is unknown."
            preserved.append(PreservedStatement(statement, "unknown_not_projected", ref))
            missing[(path, "not_provided", reason_text)] = _missing(path, "not_provided", reason_text)
            continue

        relation = rules.predicate_map.get(predicate_key)
        if relation is None:
            if statement.value.kind == "entity":
                preserved.append(PreservedStatement(statement, "relation_not_allowlisted", ref))
                missing[(path, "unsupported", "predicate is not mapped by the declared ontology rules")] = _missing(
                    path,
                    "unsupported",
                    "Entity-valued predicate is not mapped by the declared ontology rules.",
                )
            else:
                preserved.append(PreservedStatement(statement, "non_graph_statement", ref))
            continue

        if (relation.namespace, relation.version) != (rules.ontology.id, rules.ontology.version):
            raise GraphBuildError("mapped relation namespace/version differs from the declared ontology")
        if statement.value.kind != "entity":
            preserved.append(PreservedStatement(statement, "relation_target_not_entity", ref))
            missing[(path, "unsupported", "mapped graph relation requires an EntityValue target")] = _missing(
                path,
                "unsupported",
                "Mapped graph relation requires an EntityValue target.",
            )
            continue

        if statement.epistemic_status == "inferred":
            provenance = statement.provenance
            if provenance.derivation_method is None or not provenance.input_statement_refs:
                raise GraphBuildError("inferred statement must carry derivation method and input StatementRefs")
            grounded_inputs: list[StatementRef] = []
            all_inputs_resolve = True
            for input_ref in provenance.input_statement_refs:
                input_key = _ref_key(input_ref)
                input_statement = statements.get(input_key)
                if input_statement is None:
                    all_inputs_resolve = False
                    break
                _checked_ref(input_statement, input_ref, request, aggregate_refs)
                grounded_inputs.append(input_ref)
            if not all_inputs_resolve:
                preserved.append(PreservedStatement(statement, "inferred_input_reference_unresolved", None))
                missing[(path, "unavailable", "one or more inferred input references are absent from the materialized snapshot")] = _missing(
                    path,
                    "unavailable",
                    "Inferred candidate is not projected because an input StatementRef cannot be resolved in the supplied snapshot.",
                )
                continue
            edge_statement_refs: list[StatementRef] = []
        else:
            if ref is None:
                preserved.append(PreservedStatement(statement, "direct_statement_reference_missing", None))
                missing[(path, "unavailable", "exact direct StatementRef was not supplied")] = _missing(
                    path,
                    "unavailable",
                    "No graph edge was emitted because the exact direct StatementRef was not supplied.",
                )
                continue
            grounded_inputs = []
            edge_statement_refs = [ref]

        subject = entities[statement.subject.entity_id]
        target = entities[statement.value.value.entity_id]
        edge_provenance = statement.provenance
        edge = GraphEdge(
            edge_id=_stable_edge_id(statement, [*edge_statement_refs, *grounded_inputs]),
            source_node_id=_stable_graph_id("node", subject.entity_id),
            target_node_id=_stable_graph_id("node", target.entity_id),
            relation=relation,
            epistemic_status=statement.epistemic_status,
            statement_refs=edge_statement_refs,
            evidence_refs=list(edge_provenance.evidence_refs),
            provenance=edge_provenance,
        )
        validate_dto(edge)
        edges.append(edge)
        temporal_contexts.append(
            TemporalEdgeContext(
                edge_id=edge.edge_id,
                statement_id=statement.statement_id,
                statement_revision=statement.revision,
                epistemic_status=statement.epistemic_status.value,
                valid_from=statement.validity.valid_from,
                valid_to=statement.validity.valid_to,
                recorded_at=statement.validity.recorded_at,
                statement_ref=ref,
                input_statement_refs=tuple(grounded_inputs),
            )
        )

    nodes = [
        GraphNode(
            node_id=_stable_graph_id("node", entity_id),
            entity=entity,
            statement_refs=_merge_refs(node_statement_refs[entity_id]),
            provenance=Provenance(
                origin="unknown",
                source_refs=[],
                input_statement_refs=[],
                producer_run_id=None,
                derivation_method=None,
                evidence_refs=[],
                origin_verified=False,
            ),
        )
        for entity_id, entity in sorted(entities.items())
    ]

    config_hash = canonical_hash(
        {
            "builder": BUILDER_REF.model_dump(mode="json"),
            "ontology": rules.ontology.model_dump(mode="json"),
            "rules": rules.ref.model_dump(mode="json"),
            "predicate_map": [
                {
                    "source": list(source),
                    "target": target.model_dump(mode="json"),
                }
                for source, target in sorted(rules.predicate_map.items())
            ],
            "negative_predicates": sorted(rules.negative_predicates),
        }
    )
    manifest = ProjectionManifest(
        ontology=rules.ontology,
        rules=rules.ref,
        input_slices=sorted(request.knowledge.slices, key=_slice_key),
        as_of=request.knowledge.as_of,
        builder=BUILDER_REF,
        config_hash=config_hash,
    )
    completeness = "unknown" if not request.knowledge.statements and not request.knowledge.slices else "partial"
    candidate = GraphSnapshot(
        graph_id=request.graph_id,
        revision=0,
        nodes=nodes,
        edges=sorted(edges, key=lambda edge: edge.edge_id),
        manifest=manifest,
        completeness=completeness,
        missing_data=[missing[key] for key in sorted(missing)],
    )
    validate_dto(candidate)
    output = BuildGraphOutput(candidate=candidate)
    logger.debug(
        "T12 projection built: graph_id=%s statements=%d nodes=%d edges=%d sidecar=%d",
        request.graph_id,
        len(request.knowledge.statements),
        len(nodes),
        len(edges),
        len(preserved),
    )
    return BuildArtifacts(
        output=output,
        preserved_statements=tuple(preserved),
        temporal_edge_contexts=tuple(sorted(temporal_contexts, key=lambda item: item.edge_id)),
    )
