from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from alfalab_contracts.models import (
    ImpactInput,
    ImpactOutput,
    ObjectRef,
    VersionedRef,
)
from alfalab_contracts._generated import Direction, Exposure, Level, Likelihood
from alfalab_contracts.semantics import validate_impact_pair

from .common import (
    AssessmentResult,
    ImpactContext,
    build_assessment,
    context_from_contract,
    deduplicate_refs,
    follow_edge_path,
    object_key,
    path_evidence,
    graph_context_is_time_compatible,
    statement_refs_for_paths,
)

logger = logging.getLogger(__name__)
APPROACH_C_METHOD = VersionedRef(id="spike.t13.impact-approach-c", version="0.1.0", hash="sha256:f467898bb8cf07ed2a0747cc198c20cd5fd4fc410f0b4c01c0022889c04ea842")
SUPPORTED_HAZARDS = {
    "export_restriction": "restricted_input_supply",
    "sanctions": "supplier_sanctions",
    "port_closure": "route_disruption",
    "raw_material_price_increase": "input_cost_pressure",
    "supplier_default": "supplier_continuity",
}


class UnsupportedClaim(ValueError):
    """A controlled model-shaped response references facts absent from its input."""


@dataclass(frozen=True)
class ValidatedClaim:
    target_entity_id: str
    mechanism_code: str
    edge_path: tuple[str, ...]
    evidence_refs: tuple[ObjectRef, ...]
    quantity: Mapping[str, str] | None = None


def controlled_model_response(context: ImpactContext) -> dict[str, Any]:
    """Create a model-shaped offline fixture from actual paths; this is not model output."""
    mechanism = SUPPORTED_HAZARDS.get(context.event.event_type)
    if (
        not context.event.current
        or context.event.factual_status != "confirmed"
        or context.event.trust_claim_status in {"not_confirmed", "disputed"}
        or not mechanism
        or context.graph.freshness.value != "current"
    ):
        return {"claims": []}
    claims = []
    nodes = {node.node_id: node for node in context.graph.snapshot.nodes}
    for path in context.match.edge_paths:
        entity_path = follow_edge_path(context.graph, context.company_id, path)
        if not entity_path or entity_path[-1] not in set(context.event.target_entity_ids):
            continue
        evidence = path_evidence(context, path)
        claims.append({
            "target_entity_id": entity_path[-1],
            "mechanism_code": mechanism,
            "edge_path": list(path),
            "evidence_refs": [ref.model_dump(mode="json") for ref in evidence],
            "quantity": None,
        })
    return {"claims": claims}


def _validate_claim(context: ImpactContext, item: Mapping[str, Any]) -> ValidatedClaim:
    if set(item) != {"target_entity_id", "mechanism_code", "edge_path", "evidence_refs", "quantity"}:
        raise UnsupportedClaim("claim fields are not in the controlled response schema")
    target_id = item["target_entity_id"]
    if not isinstance(target_id, str) or target_id not in set(context.event.target_entity_ids):
        raise UnsupportedClaim("claim target is not a target entity in the supplied event")
    node_entity_ids = {node.entity.entity_id for node in context.graph.snapshot.nodes}
    if target_id not in node_entity_ids:
        raise UnsupportedClaim("claim target is absent from the supplied graph")
    edge_path = item["edge_path"]
    if not isinstance(edge_path, list) or not edge_path or len(edge_path) > 5 or any(not isinstance(edge_id, str) for edge_id in edge_path):
        raise UnsupportedClaim("claim must use a non-empty graph path of at most five edges")
    entity_path = follow_edge_path(context.graph, context.company_id, edge_path)
    if not entity_path or entity_path[0] != context.company_id or entity_path[-1] != target_id:
        raise UnsupportedClaim("claim path does not connect the supplied company to its target")
    graph_edges = {edge.edge_id: edge for edge in context.graph.snapshot.edges}
    if any(graph_edges[edge_id].epistemic_status.value in {"disputed", "disproved", "unknown"} for edge_id in edge_path):
        raise UnsupportedClaim("claim path contains a disputed, disproved, or unknown edge")
    if item["mechanism_code"] != SUPPORTED_HAZARDS.get(context.event.event_type):
        raise UnsupportedClaim("claim mechanism is not allowed for this event type")
    supplied = {object_key(record.ref) for record in context.evidence}
    allowed = {object_key(ref) for ref in context.event.evidence_refs}
    allowed.update(object_key(ref) for ref in path_evidence(context, edge_path))
    raw_refs = item["evidence_refs"]
    if not isinstance(raw_refs, list) or not raw_refs:
        raise UnsupportedClaim("claim needs evidence references")
    refs = []
    cited_keys: set[tuple[str, str, int, str]] = set()
    for raw in raw_refs:
        try:
            ref = ObjectRef.model_validate(raw)
        except Exception as exc:
            raise UnsupportedClaim("malformed evidence reference") from exc
        key = object_key(ref)
        record = context.evidence_by_ref.get(key)
        if key not in supplied or key not in allowed or record is None:
            raise UnsupportedClaim("claim evidence is absent from the exact supplied event/path inputs")
        if record.verification.value != "verified_anchor":
            raise UnsupportedClaim("claim evidence anchor is not verified")
        if record.source_reliability.value == "disputed":
            raise UnsupportedClaim("claim cites disputed source reliability")
        refs.append(ref)
        cited_keys.add(key)
    required_path_keys = {
        object_key(ref)
        for edge_id in edge_path
        for ref in graph_edges[edge_id].evidence_refs
    }
    if not required_path_keys <= cited_keys:
        raise UnsupportedClaim("claim omits graph path evidence")
    quantity = item["quantity"]
    if quantity is not None:
        expected = context.numeric_inputs.get("expected_calculation") if context.numeric_inputs else None
        if not isinstance(quantity, dict) or expected is None:
            raise UnsupportedClaim("numeric claim has no explicitly supplied scenario inputs")
        if str(quantity.get("value")) != str(expected.get("value")) or str(quantity.get("unit")) != str(expected.get("unit")):
            raise UnsupportedClaim("numeric claim differs from the explicit scenario value or unit")
    return ValidatedClaim(
        target_entity_id=target_id,
        mechanism_code=item["mechanism_code"],
        edge_path=tuple(edge_path),
        evidence_refs=tuple(deduplicate_refs(refs)),
        quantity=quantity,
    )


def validate_controlled_response(context: ImpactContext, response: Mapping[str, Any]) -> tuple[ValidatedClaim, ...]:
    if set(response) != {"claims"} or not isinstance(response["claims"], list):
        raise UnsupportedClaim("controlled response must contain only a claims array")
    if len(response["claims"]) > 100:
        raise UnsupportedClaim("too many claims")
    if response["claims"] and (not context.event.current or context.event.factual_status != "confirmed"):
        raise UnsupportedClaim("current impact claims are blocked for stale, uncertain, or non-confirmed events")
    if response["claims"] and context.event.trust_claim_status in {"not_confirmed", "disputed"}:
        raise UnsupportedClaim("current impact claims are blocked by upstream trust status")
    if response["claims"] and context.graph.freshness.value != "current":
        raise UnsupportedClaim("current impact claims are blocked by a stale or historical graph")
    if response["claims"] and not graph_context_is_time_compatible(context):
        raise UnsupportedClaim("current impact claims are blocked by a future graph cut or mismatched profile slice")
    claims = tuple(_validate_claim(context, item) for item in response["claims"])
    logger.debug("validated controlled impact claims=%d scenario=%s", len(claims), context.scenario_id)
    return claims


def assess_c(context: ImpactContext, controlled_response: Mapping[str, Any]) -> AssessmentResult:
    claims = validate_controlled_response(context, controlled_response)
    if claims:
        path_refs = [ref for claim in claims for ref in claim.evidence_refs]
        exposure = (
            context.match.exposure
            if context.event.owner_confirmed and context.match.exposure in {Exposure.confirmed, Exposure.potential}
            else Exposure.potential
        )
        return build_assessment(
            context,
            exposure=exposure,
            likelihood=Likelihood.possible,
            direction=Direction.negative,
            mechanism_codes=(claim.mechanism_code for claim in claims),
            confidence=Level.low,
            missing_data=context.match.missing_data,
            evidence_refs=path_refs,
            trace=("controlled response accepted", "each claim cites supplied graph edges and evidence refs", "model quality not measured"),
            accepted_claim_count=len(claims),
            method=APPROACH_C_METHOD,
            input_statement_refs=statement_refs_for_paths(context, (claim.edge_path for claim in claims)),
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
        trace=("no validated model-shaped claim", "unknown is preserved"),
        method=APPROACH_C_METHOD,
        input_statement_refs=statement_refs_for_paths(context, ()),
    )


def assess_c_contract(request: ImpactInput, controlled_response: Mapping[str, Any]) -> ImpactOutput:
    context = context_from_contract(request)
    result = assess_c(context, controlled_response)
    response = ImpactOutput(assessment=result.assessment)
    validate_impact_pair(request, response)
    return response
