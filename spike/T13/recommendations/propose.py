from __future__ import annotations

import logging
from alfalab_contracts._generated import Audience, Priority
from alfalab_contracts.models import (
    ActionDefinition,
    CodeRef,
    ImpactAssessment,
    MissingDatum,
    Provenance,
    Recommendation,
    RecommendationInput,
    RecommendationOutput,
    VersionedRef,
)
from alfalab_contracts.semantics import validate_recommendation_pair

logger = logging.getLogger(__name__)
METHOD = VersionedRef(
    id="spike.t13.recommendations",
    version="0.1.0",
    hash="sha256:dd06d0502c35a3cfc610b0ee15bcbc8d428e34f197c72e16653bcdae15ed1ac5",
)
ACTION_NAMESPACE = "spike.t13.informational-action"
ACTION_VERSION = "0.1.0"
SAFE_INFORMATION_ACTIONS = {
    "ask_supplier_geography",
    "clarify_procurement_volume",
    "clarify_import_share",
    "check_inventory",
    "verify_alternative_route",
    "request_supporting_document",
    "review_with_analyst",
}
WHY = {
    "ask_supplier_geography": "The event could matter only if the company sources from the affected geography; the supplied profile leaves that dependency unknown.",
    "clarify_procurement_volume": "A documented procurement volume could change the scale of a possible input disruption; no financial loss is inferred.",
    "clarify_import_share": "Import share could clarify exposure, but it is currently unknown and is not inferred from sector or product type.",
    "check_inventory": "A current inventory answer could change the duration of a possible supply interruption.",
    "verify_alternative_route": "The graph shows a route relationship, but it does not show whether an alternative route is available.",
    "request_supporting_document": "Additional company or supplier documentation could resolve the missing or conflicting input.",
    "review_with_analyst": "A human review can check the supplied evidence and unresolved conditions before anyone acts on the assessment.",
}


def _missing_for_response(path: str, reason: str, detail: str) -> MissingDatum:
    return MissingDatum(path=path, reason=reason, detail=detail)


def _candidate_codes(assessment: ImpactAssessment) -> list[str]:
    paths = {item.path.lower() for item in assessment.missing_data}
    if "/event/targets" in paths or "/event/evidential_status" in paths:
        return []
    codes: list[str] = []
    if "/dependencies/suppliers" in paths or "/sourcing/countries" in paths:
        codes.append("ask_supplier_geography")
    has_mechanism = bool(assessment.mechanisms)
    if has_mechanism and "/procurement/volume" in paths:
        codes.append("clarify_procurement_volume")
    if has_mechanism and "/procurement/import_share" in paths:
        codes.append("clarify_import_share")
    if has_mechanism and ("/inventory" in " ".join(paths) or "/stock" in " ".join(paths) or any(item.code == "route_disruption" for item in assessment.mechanisms)):
        codes.append("check_inventory")
    if has_mechanism and (any("route" in path or "logistic" in path for path in paths) or any(item.code == "route_disruption" for item in assessment.mechanisms)):
        codes.append("verify_alternative_route")
    if not has_mechanism and not codes and assessment.exposure.value in {"potential", "confirmed"}:
        codes.append("request_supporting_document")
    if has_mechanism:
        codes.append("review_with_analyst")
    return list(dict.fromkeys(codes))


def propose(request: RecommendationInput) -> RecommendationOutput:
    """Propose informational, evidence-linked actions from the supplied catalog."""
    if not request.allowed_actions:
        result = RecommendationOutput(recommendations=[], missing_data=[])
        validate_recommendation_pair(request, result)
        return result
    assessment = request.assessment
    if not assessment.evidence_refs:
        result = RecommendationOutput(
            recommendations=[],
            missing_data=[_missing_for_response("/assessment/evidence_refs", "not_provided", "No recommendation is emitted without evidence references in the supplied assessment.")],
        )
        validate_recommendation_pair(request, result)
        return result

    candidates: list[Recommendation] = []
    for code in _candidate_codes(assessment):
        if code not in SAFE_INFORMATION_ACTIONS:
            continue
        action = next((item for item in request.allowed_actions if item.code.code == code), None)
        if (
            action is None
            or action.code.namespace != ACTION_NAMESPACE
            or action.code.version != ACTION_VERSION
            or request.audience not in action.audiences
        ):
            continue
        if not action.title or len(action.title) > 300:
            continue
        evidence_refs = list(assessment.evidence_refs)
        candidates.append(Recommendation(
            recommendation_id=f"recommend-{assessment.assessment_id}-{code}",
            assessment_id=assessment.assessment_id,
            action_type=action.code,
            title=action.title,
            why=WHY[code],
            priority=Priority.high if assessment.exposure.value == "confirmed" and assessment.likelihood.value == "likely" else Priority.medium,
            conditions=["Informational only; this proposal does not execute an action."],
            requires_approval=bool(action.requires_approval),
            evidence_refs=evidence_refs,
            provenance=Provenance(
                origin="synthetic",
                source_refs=assessment.provenance.source_refs,
                input_statement_refs=assessment.provenance.input_statement_refs,
                producer_run_id=None,
                derivation_method=METHOD,
                evidence_refs=evidence_refs,
                origin_verified=False,
            ),
        ))
    result = RecommendationOutput(recommendations=candidates[:3], missing_data=[])
    validate_recommendation_pair(request, result)
    logger.debug("proposed informational recommendations=%d audience=%s", len(result.recommendations), request.audience.value)
    return result


def default_information_actions() -> list[ActionDefinition]:
    """Small local experiment catalog; callers still pass the allowed definitions."""
    return [
        ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="ask_supplier_geography"), title="Уточнить географию поставок", audiences=[Audience.entrepreneur, Audience.bank_manager, Audience.analyst], requires_approval=False),
        ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="clarify_procurement_volume"), title="Уточнить объём закупок", audiences=[Audience.entrepreneur, Audience.analyst], requires_approval=False),
        ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="clarify_import_share"), title="Уточнить долю импорта", audiences=[Audience.entrepreneur, Audience.analyst], requires_approval=False),
        ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="check_inventory"), title="Проверить доступные запасы", audiences=[Audience.entrepreneur, Audience.analyst], requires_approval=False),
        ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="verify_alternative_route"), title="Уточнить альтернативные маршруты", audiences=[Audience.entrepreneur, Audience.analyst], requires_approval=False),
        ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="request_supporting_document"), title="Запросить подтверждающий документ", audiences=[Audience.entrepreneur, Audience.bank_manager, Audience.analyst], requires_approval=True),
        ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="review_with_analyst"), title="Проверить основание с аналитиком", audiences=[Audience.bank_manager, Audience.analyst], requires_approval=True),
    ]


def propose_contract_pair(request: RecommendationInput, response: RecommendationOutput) -> RecommendationOutput:
    validate_recommendation_pair(request, response)
    return response
