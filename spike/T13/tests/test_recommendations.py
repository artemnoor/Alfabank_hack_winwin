from __future__ import annotations

from alfalab_contracts._generated import ActionDefinition, Audience, CodeRef, Priority
from alfalab_contracts.models import RecommendationInput
from alfalab_contracts.semantics import validate_recommendation_pair
import pytest

from impact.approach_d import assess_d
from recommendations.propose import default_information_actions, propose


def request_for(ctx, actions=None, audience=Audience.bank_manager):
    assessment = assess_d(ctx).assessment
    return RecommendationInput(
        assessment=assessment,
        audience=audience,
        allowed_actions=actions if actions is not None else default_information_actions(),
        constraints=["Informational only."],
    )


def test_unknown_supplier_gets_targeted_evidence_linked_information_action(contexts):
    request = request_for(contexts["export-a-unknown-supplier"])
    response = propose(request)
    assert any(item.action_type.code == "ask_supplier_geography" for item in response.recommendations)
    for item in response.recommendations:
        assert item.evidence_refs
        assert item.provenance.derivation_method.id == "spike.t13.recommendations"
        assert item.assessment_id == request.assessment.assessment_id
        assert item.requires_approval in (True, False)
        assert "does not execute" in item.conditions[0]
    validate_recommendation_pair(request, response)


def test_empty_allowlist_returns_empty_recommendations(contexts):
    request = request_for(contexts["export-b-direct"], actions=[])
    response = propose(request)
    assert response.recommendations == []
    validate_recommendation_pair(request, response)


def test_no_evidence_means_no_recommendation(contexts):
    request = request_for(contexts["export-a-unknown-supplier"])
    assessment = request.assessment.model_copy(update={"evidence_refs": [], "provenance": request.assessment.provenance.model_copy(update={"evidence_refs": []})})
    request = request.model_copy(update={"assessment": assessment})
    response = propose(request)
    assert response.recommendations == []
    assert response.missing_data


def test_action_for_wrong_audience_is_not_proposed(contexts):
    actions = [ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="ask_supplier_geography"), title="Ask supplier geography", audiences=[Audience.entrepreneur], requires_approval=False)]
    request = request_for(contexts["export-a-unknown-supplier"], actions=actions, audience=Audience.bank_manager)
    response = propose(request)
    assert response.recommendations == []


def test_non_informational_allowlisted_action_is_never_selected(contexts):
    risky = ActionDefinition(code=CodeRef(namespace="bank", version="1.0.0", code="transfer_funds"), title="Transfer funds", audiences=[Audience.bank_manager], requires_approval=True)
    request = request_for(contexts["export-b-direct"], actions=[risky])
    assert propose(request).recommendations == []


def test_requires_approval_is_preserved(contexts):
    action = ActionDefinition(code=CodeRef(namespace="spike.t13.informational-action", version="0.1.0", code="ask_supplier_geography"), title="Ask supplier geography", audiences=[Audience.bank_manager], requires_approval=True)
    request = request_for(contexts["export-a-unknown-supplier"], actions=[action])
    response = propose(request)
    assert response.recommendations
    assert all(item.requires_approval is True for item in response.recommendations)


def test_recommendation_with_fabricated_evidence_is_rejected(contexts):
    request = request_for(contexts["export-a-unknown-supplier"])
    response = propose(request)
    assert response.recommendations
    bad = response.recommendations[0].model_copy(update={"evidence_refs": [response.recommendations[0].evidence_refs[0].model_copy(update={"object_id": "ev-fake"})]})
    with pytest.raises(ValueError, match="evidence_refs"):
        validate_recommendation_pair(request, response.model_copy(update={"recommendations": [bad]}))



def test_known_supplier_missing_volume_gets_volume_question_not_geography(contexts):
    request = request_for(contexts["export-b-known-supplier-no-volume"], audience=Audience.analyst)
    response = propose(request)
    codes = {item.action_type.code for item in response.recommendations}
    assert "clarify_procurement_volume" in codes
    assert "ask_supplier_geography" not in codes


def test_industry_only_and_historical_events_do_not_trigger_generic_actions(contexts):
    for case_id in ("industry-only-a", "stale-port-closure-c", "supplier-default-rumor-b"):
        response = propose(request_for(contexts[case_id]))
        assert response.recommendations == []


def test_route_mechanism_recommends_route_or_inventory_information(contexts):
    response = propose(request_for(contexts["port-b-known-route"], audience=Audience.analyst))
    codes = {item.action_type.code for item in response.recommendations}
    assert "verify_alternative_route" in codes or "check_inventory" in codes


def test_safe_code_with_wrong_catalog_namespace_is_not_allowed(contexts):
    forged = ActionDefinition(code=CodeRef(namespace="bank", version="1.0.0", code="ask_supplier_geography"), title="Ask supplier geography", audiences=[Audience.bank_manager], requires_approval=False)
    request = request_for(contexts["export-a-unknown-supplier"], actions=[forged])
    assert propose(request).recommendations == []
