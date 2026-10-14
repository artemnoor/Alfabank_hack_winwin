from __future__ import annotations

from typing import Sequence

from alfalab_contracts.models import (
    ImpactInput,
    ImpactOutput,
    Match,
    VersionedRef,
)
from alfalab_contracts._generated import Direction, Exposure, Level, Likelihood
from alfalab_contracts.semantics import validate_impact_pair

from matching.core import EventContext

from .common import AssessmentResult, ImpactContext, build_assessment, context_from_contract, follow_edge_path, object_key, path_evidence, graph_context_is_time_compatible, statement_refs_for_paths


APPROACH_D_METHOD = VersionedRef(id="spike.t13.impact-approach-d", version="0.1.0", hash="sha256:3715ca68cd519c514dbd04828644d2ef5059599ee2df6a909bbcd5a68604c72d")

RULE_MECHANISMS = {
    "export_restriction": "restricted_input_supply",
    "sanctions": "supplier_sanctions",
    "port_closure": "route_disruption",
    "raw_material_price_increase": "input_cost_pressure",
    "supplier_default": "supplier_continuity",
}


def _path_edges_confirmed(context: ImpactContext, path: Sequence[str]) -> bool:
    edges = {edge.edge_id: edge for edge in context.graph.snapshot.edges}
    return bool(path) and all(edge_id in edges and edges[edge_id].epistemic_status.value == "confirmed" for edge_id in path)


def assess_d(context: ImpactContext) -> AssessmentResult:
    """Apply explicit graph, event, evidence, freshness, and contradiction gates."""
    trace: list[str] = ["ruleset=0.1.0"]
    event_state_ok = (
        context.event.factual_status == "confirmed"
        and context.event.current
        and context.event.trust_claim_status not in {"not_confirmed", "disputed"}
    )
    graph_current = context.graph.freshness.value == "current" and graph_context_is_time_compatible(context)
    evidence_by_ref = context.evidence_by_ref
    event_evidence_present = bool(context.event.evidence_refs) and all(
        object_key(ref) in evidence_by_ref
        and evidence_by_ref[object_key(ref)].verification.value == "verified_anchor"
        and evidence_by_ref[object_key(ref)].source_reliability.value != "disputed"
        for ref in context.event.evidence_refs
    )
    if not event_state_ok:
        trace.append("event state is not current and confirmed")
    if not graph_current:
        trace.append("graph is stale, future-dated, or does not contain the exact profile slice")
    if not event_evidence_present:
        trace.append("event evidence refs are missing from the supplied Evidence.read snapshot")

    mechanism = RULE_MECHANISMS.get(context.event.event_type)
    eligible_paths: list[tuple[str, ...]] = []
    path_refs = []
    for path in context.match.edge_paths:
        entities = follow_edge_path(context.graph, context.company_id, path)
        if not entities or entities[-1] not in set(context.event.target_entity_ids):
            continue
        if not _path_edges_confirmed(context, path):
            trace.append("path has a non-confirmed edge; mechanism stays conditional")
            continue
        edge_refs = path_evidence(context, path)
        if not edge_refs or not all(
            object_key(ref) in evidence_by_ref
            and evidence_by_ref[object_key(ref)].verification.value == "verified_anchor"
            and evidence_by_ref[object_key(ref)].source_reliability.value != "disputed"
            for ref in edge_refs
        ):
            trace.append("path evidence ref is missing, hash-mismatched, unverified, or disputed in Evidence.read")
            continue
        eligible_paths.append(tuple(path))
        path_refs.extend(edge_refs)
    profile_conflict = bool(context.profile.contradictions) or any(
        statement.epistemic_status.value in {"disputed", "disproved"}
        for statement in context.profile.statements
    )
    if profile_conflict:
        trace.append("profile has conflicting/disputed statements")
    if any(evidence_by_ref[object_key(ref)].source_reliability.value == "disputed" for ref in context.event.evidence_refs if object_key(ref) in evidence_by_ref):
        profile_conflict = True
        trace.append("source reliability is explicitly disputed; consequence confidence is lowered")
    if any(evidence_by_ref[object_key(ref)].source_reliability.value == "unassessed" for ref in context.event.evidence_refs if object_key(ref) in evidence_by_ref):
        trace.append("source reliability is unassessed; no reliability score is inferred")

    can_assess = bool(mechanism and eligible_paths and event_state_ok and graph_current and event_evidence_present)
    if can_assess:
        # Conflicts lower confidence; the route/event exposure remains visible with caveats.
        confidence = Level.low if profile_conflict or context.graph.snapshot.completeness.value != "complete_for_declared_slice" else Level.medium
        exposure = Exposure.confirmed if context.event.owner_confirmed and not profile_conflict else Exposure.potential
        return build_assessment(
            context,
            exposure=exposure,
            likelihood=Likelihood.possible,
            direction=Direction.negative,
            mechanism_codes=(mechanism,),
            confidence=confidence,
            missing_data=context.match.missing_data,
            evidence_refs=path_refs,
            trace=tuple(trace + ["every mechanism path is an actual supplied graph path", "no financial loss calculated"]),
            method=APPROACH_D_METHOD,
            input_statement_refs=statement_refs_for_paths(context, eligible_paths),
        )
    return build_assessment(
        context,
        exposure=Exposure.unknown,
        likelihood=Likelihood.unknown,
        direction=Direction.unknown,
        mechanism_codes=(),
        confidence=Level.unknown,
        missing_data=context.match.missing_data,
        evidence_refs=context.event.evidence_refs,
        trace=tuple(trace + ["insufficient evidence for a current impact mechanism"]),
        method=APPROACH_D_METHOD,
        input_statement_refs=statement_refs_for_paths(context, ()),
    )


def assess_d_contract(request: ImpactInput) -> ImpactOutput:
    context = context_from_contract(request)
    response = ImpactOutput(assessment=assess_d(context).assessment)
    validate_impact_pair(request, response)
    return response
