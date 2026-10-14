from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime
from dataclasses import replace
from typing import Any, Iterable, Mapping, Sequence

from alfalab_contracts.models import (
    AnalyticalConfidence,
    CodeRef,
    EventRecord,
    FinancialScenario,
    GraphSubgraph,
    ImpactAssessment,
    ImpactInput,
    ImpactOutput,
    Match,
    MissingDatum,
    NumberValue,
    ObjectRef,
    Provenance,
    StatementRef,
    TimeSlice,
    VersionedRef,
)
from alfalab_contracts._generated import Direction, Exposure, Level, Likelihood, Materiality
from alfalab_contracts.semantics import validate_impact_pair

ANALYSIS_METHOD = VersionedRef(
    id="spike.t13.impact",
    version="0.1.0",
    hash="sha256:127645e726d81850509f6d596657e647571dc6b8cf12c3692b150f78956ea949",
)
CALCULATION_METHOD = VersionedRef(
    id="spike.t13.financial-scenario",
    version="0.1.0",
    hash="sha256:6da090cc6b2f0d7da9706dfe11cc49f1823ccf2edae7fcecaaf785b1300c414f",
)
HAZARD_MECHANISMS = {
    "export_restriction": "restricted_input_supply",
    "sanctions": "supplier_sanctions",
    "port_closure": "route_disruption",
    "raw_material_price_increase": "input_cost_pressure",
    "supplier_default": "supplier_continuity",
}


@dataclass(frozen=True)
class ImpactContext:
    event: Any
    profile: Any
    match: Match
    graph: GraphSubgraph
    evidence: Sequence[Any]
    as_of: TimeSlice
    scenario_id: str
    numeric_inputs: Mapping[str, str] | None = None

    @property
    def company_id(self) -> str:
        return self.profile.company.entity_id

    @property
    def evidence_by_ref(self) -> dict[tuple[str, str, int, str], Any]:
        return {object_key(record.ref): record for record in self.evidence}


@dataclass(frozen=True)
class AssessmentResult:
    assessment: ImpactAssessment
    trace: tuple[str, ...]
    accepted_claim_count: int = 0


def object_key(ref: ObjectRef) -> tuple[str, str, int, str]:
    return ref.owner.value, ref.object_id, ref.revision, ref.hash


def deduplicate_refs(refs: Iterable[ObjectRef]) -> list[ObjectRef]:
    by_key = {object_key(ref): ref for ref in refs}
    return [by_key[key] for key in sorted(by_key)]


def missing(path: str, reason: str, detail: str) -> MissingDatum:
    return MissingDatum(path=path, reason=reason, detail=detail)


def graph_nodes_by_entity(graph: GraphSubgraph) -> dict[str, str]:
    return {node.entity.entity_id: node.node_id for node in graph.snapshot.nodes}


def follow_edge_path(graph: GraphSubgraph, company_id: str, path: Sequence[str]) -> tuple[str, ...] | None:
    """Resolve a path through supplied graph edges; no edge is inferred here."""
    nodes = {node.node_id: node for node in graph.snapshot.nodes}
    edges = {edge.edge_id: edge for edge in graph.snapshot.edges}
    starts = sorted(node_id for node_id, node in nodes.items() if node.entity.entity_id == company_id)
    for start in starts:
        current = start
        visited_entities = [nodes[current].entity.entity_id]
        valid = True
        for edge_id in path:
            edge = edges.get(edge_id)
            if edge is None:
                valid = False
                break
            if edge.source_node_id == current:
                current = edge.target_node_id
            else:
                valid = False
                break
            if current not in nodes:
                valid = False
                break
            visited_entities.append(nodes[current].entity.entity_id)
        if valid:
            return tuple(visited_entities)
    return None


def path_evidence(context: ImpactContext, path: Sequence[str]) -> list[ObjectRef]:
    edge_by_id = {edge.edge_id: edge for edge in context.graph.snapshot.edges}
    refs: list[ObjectRef] = list(context.event.evidence_refs)
    for edge_id in path:
        edge = edge_by_id.get(edge_id)
        if edge is not None:
            refs.extend(edge.evidence_refs)
    return deduplicate_refs(refs)


def statement_refs_for_paths(
    context: ImpactContext,
    paths: Iterable[Sequence[str]],
) -> list[StatementRef]:
    """Return only supplied event/path StatementRefs, without synthesizing hashes."""
    refs = list(getattr(context.event, "statement_refs", ()))
    edge_by_id = {edge.edge_id: edge for edge in context.graph.snapshot.edges}
    for path in paths:
        for edge_id in path:
            edge = edge_by_id.get(edge_id)
            if edge is not None:
                refs.extend(edge.statement_refs)
    return _deduplicate_statement_refs(refs)


def _deduplicate_statement_refs(refs: Iterable[StatementRef]) -> list[StatementRef]:
    by_key = {
        (
            *object_key(ref.aggregate_ref),
            ref.statement_id,
            ref.revision,
            ref.hash,
        ): ref
        for ref in refs
    }
    return [by_key[key] for key in sorted(by_key)]


def evidence_ids_available(context: ImpactContext) -> set[tuple[str, str, int, str]]:
    return {object_key(record.ref) for record in context.evidence}


def graph_context_is_time_compatible(context: ImpactContext) -> bool:
    manifest_time = context.graph.snapshot.manifest.as_of
    try:
        graph_known = datetime.fromisoformat(manifest_time.known_as_of.replace("Z", "+00:00"))
        graph_valid = datetime.fromisoformat(manifest_time.valid_as_of.replace("Z", "+00:00"))
        request_known = datetime.fromisoformat(context.as_of.known_as_of.replace("Z", "+00:00"))
        request_valid = datetime.fromisoformat(context.as_of.valid_as_of.replace("Z", "+00:00"))
    except ValueError:
        return False
    if graph_known > request_known or graph_valid > request_valid:
        return False
    profile_slice = context.profile.slice
    wanted = (profile_slice.owner.value, profile_slice.partition_id, profile_slice.revision, profile_slice.selection_key)
    return any(
        (item.owner.value, item.partition_id, item.revision, item.selection_key) == wanted
        for item in context.graph.snapshot.manifest.input_slices
    )


def scenario_financial_output(scenario_id: str) -> FinancialScenario:
    # ImpactInput has no field for separate scenario assumptions; quantity stays null here.
    return FinancialScenario(
        scenario_id=f"{scenario_id}-financial-quantity-unavailable",
        quantity=None,
        assumptions=[],
        calculation_method=CALCULATION_METHOD,
        input_refs=[],
    )


def build_assessment(
    context: ImpactContext,
    *,
    exposure: Exposure,
    likelihood: Likelihood,
    direction: Direction,
    mechanism_codes: Iterable[str],
    confidence: Level,
    missing_data: Iterable[MissingDatum],
    evidence_refs: Iterable[ObjectRef],
    trace: Sequence[str] = (),
    accepted_claim_count: int = 0,
    method: VersionedRef = ANALYSIS_METHOD,
    input_statement_refs: Iterable[StatementRef] = (),
) -> AssessmentResult:
    refs = deduplicate_refs(evidence_refs)
    records_by_ref = context.evidence_by_ref
    statement_refs = _deduplicate_statement_refs(
        [*getattr(context.event, "statement_refs", ()), *input_statement_refs]
    )
    source_refs = deduplicate_refs(
        records_by_ref[object_key(ref)].source_ref
        for ref in refs
        if object_key(ref) in records_by_ref
    )
    mechanisms = [
        CodeRef(namespace="spike.t13.mechanism", version="0.1.0", code=code)
        for code in sorted(set(mechanism_codes))
    ]
    all_missing = list(missing_data)
    if context.graph.snapshot.completeness.value != "complete_for_declared_slice":
        all_missing.append(missing("/graph/completeness", "not_observed", "The input graph is partial; a missing path cannot prove no dependency."))
    if context.graph.freshness.value != "current":
        all_missing.append(missing("/graph/freshness", "unavailable", "The supplied graph is not current for this assessment."))
    if not graph_context_is_time_compatible(context):
        all_missing.append(missing("/graph/as_of", "unavailable", "The graph time cut is future-dated or omits the exact Business profile slice."))
    if context.graph.traversal_truncated:
        all_missing.append(missing("/graph/traversal", "not_observed", "The supplied graph traversal was truncated."))
    if context.profile.contradictions:
        all_missing.append(missing("/profile/contradictions", "contradictory", "The company profile contains unresolved conflicting statements."))
    if context.event.factual_status in {"rumor", "disputed", "historical", "forecast", "unknown", "sector_only"}:
        all_missing.append(missing("/event/evidential_status", "unavailable", f"Event state {context.event.factual_status!r} does not support a current impact conclusion."))
    if not context.event.owner_confirmed:
        all_missing.append(missing("/event/trusted_confirmation", "unavailable", "No pinned explicit owner confirmation was supplied; a verified anchor or review-eligible policy is insufficient."))
    unique_missing = {(item.path, item.reason.value, item.detail): item for item in all_missing}
    # Reliability is not projected into analytical confidence; this synthetic harness keeps it conservative.
    analytical_confidence = confidence
    assessment = ImpactAssessment(
        assessment_id=f"assessment-{context.scenario_id}",
        event_ref=context.event.event_ref,
        company=context.profile.company,
        graph_manifest=context.graph.snapshot.manifest,
        exposure=exposure,
        likelihood=likelihood,
        direction=direction,
        materiality=Materiality.unknown,
        mechanisms=mechanisms,
        assumptions=[],
        scenarios=[scenario_financial_output(context.scenario_id)],
        missing_data=[unique_missing[key] for key in sorted(unique_missing)][:1000],
        evidence_refs=refs[:100],
        confidence=AnalyticalConfidence(
            level=analytical_confidence,
            method=method,
            limitations=[
                "Synthetic provisional inputs; offline logic only.",
                "Exposure, likelihood, materiality, analytical confidence, and source reliability are distinct fields.",
                "No numeric financial quantity is emitted by this contract-shaped result without input StatementRefs.",
            ],
        ),
        provenance=Provenance(
            origin="synthetic",
            source_refs=source_refs[:100],
            input_statement_refs=statement_refs,
            producer_run_id=None,
            derivation_method=method,
            evidence_refs=refs[:100],
            origin_verified=False,
        ),
    )
    return AssessmentResult(assessment=assessment, trace=tuple(trace), accepted_claim_count=accepted_claim_count)


def _event_targets_are_valid_at(event: EventRecord, as_of: TimeSlice) -> bool:
    try:
        cutoff = datetime.fromisoformat(as_of.valid_as_of.replace("Z", "+00:00"))
        for statement in event.statements:
            if statement.value.kind != "entity":
                continue
            if statement.validity.valid_from is not None:
                starts = datetime.fromisoformat(statement.validity.valid_from.replace("Z", "+00:00"))
                if starts > cutoff:
                    return False
            if statement.validity.valid_to is not None:
                ends = datetime.fromisoformat(statement.validity.valid_to.replace("Z", "+00:00"))
                if cutoff > ends:
                    return False
        return True
    except ValueError:
        return False


def context_from_contract(request: ImpactInput, scenario_id: str = "contract-case") -> ImpactContext:
    from matching.core import EventContext

    event = EventContext.from_record(request.event)
    event = replace(event, current=event.current and _event_targets_are_valid_at(request.event, request.as_of))
    return ImpactContext(
        event=event,
        profile=request.profile,
        match=request.match,
        graph=request.graph,
        evidence=request.evidence,
        as_of=request.as_of,
        scenario_id=scenario_id,
    )


def assess_contract_pair(request: ImpactInput, response: ImpactOutput) -> ImpactOutput:
    validate_impact_pair(request, response)
    return response


def calculate_explicit_gross_exposure(inputs: Mapping[str, Any]) -> tuple[str, str]:
    """Calculate an explicitly supplied gross procurement scenario, never a loss estimate."""
    required = {row["name"]: row for row in inputs.get("inputs", [])}
    names = ("monthly_quantity", "unit_price", "affected_share")
    if set(names) - set(required):
        raise ValueError("numeric scenario requires quantity, price, and affected share")
    try:
        value = Decimal(required[names[0]]["value"]) * Decimal(required[names[1]]["value"]) * Decimal(required[names[2]]["value"])
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("invalid decimal in explicit numeric scenario") from exc
    if value < 0 or Decimal(required[names[2]]["value"]) > 1:
        raise ValueError("out-of-bound scenario input")
    return format(value.normalize(), "f"), "RUB/month"
