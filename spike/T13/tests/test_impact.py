from __future__ import annotations

from dataclasses import replace
import json

import pytest
from alfalab_contracts.models import ImpactInput, ImpactOutput, ObjectRef
from alfalab_contracts._generated import Exposure, Likelihood
from alfalab_contracts.semantics import validate_impact_pair

from experiments.run_offline import load_materialized_inputs, make_context
from impact.approach_c import (
    UnsupportedClaim,
    assess_c,
    assess_c_contract,
    controlled_model_response,
    validate_controlled_response,
)
from impact.approach_d import assess_d, assess_d_contract
from impact.common import calculate_explicit_gross_exposure


def test_30_scenarios_run_c_and_d_on_same_materialized_inputs(contexts, scenario_rows):
    assert len(scenario_rows) == 30
    for row in scenario_rows:
        ctx = contexts[row["case_id"]]
        c_result = assess_c(ctx, controlled_model_response(ctx))
        d_result = assess_d(ctx)
        assert c_result.assessment.event_ref == d_result.assessment.event_ref
        assert c_result.assessment.company.entity_id == d_result.assessment.company.entity_id
        ImpactOutput.model_validate({"assessment": c_result.assessment.model_dump(mode="json")})
        ImpactOutput.model_validate({"assessment": d_result.assessment.model_dump(mode="json")})


def test_every_accepted_c_claim_uses_existing_path_and_available_evidence(contexts):
    for ctx in contexts.values():
        response = controlled_model_response(ctx)
        claims = validate_controlled_response(ctx, response)
        for claim in claims:
            assert set(claim.edge_path).issubset({edge.edge_id for edge in ctx.graph.snapshot.edges})
            assert claim.evidence_refs
            assert all(ctx.evidence_by_ref.get((ref.owner.value, ref.object_id, ref.revision, ref.hash)) for ref in claim.evidence_refs)


def test_c_rejects_invented_entity(contexts):
    ctx = contexts["export-b-direct"]
    response = controlled_model_response(ctx)
    response["claims"][0]["target_entity_id"] = "fictional-supplier"
    with pytest.raises(UnsupportedClaim, match="target"):
        validate_controlled_response(ctx, response)


def test_c_rejects_fabricated_graph_edge(contexts):
    ctx = contexts["export-b-direct"]
    response = controlled_model_response(ctx)
    response["claims"][0]["edge_path"] = ["edge-made-up"]
    with pytest.raises(UnsupportedClaim, match="path"):
        validate_controlled_response(ctx, response)


def test_c_rejects_unavailable_evidence(contexts):
    ctx = contexts["export-b-direct"]
    response = controlled_model_response(ctx)
    response["claims"][0]["evidence_refs"] = [{"owner": "Evidence", "object_id": "ev-fake", "revision": 1, "hash": "sha256:" + "0" * 64}]
    with pytest.raises(UnsupportedClaim, match="evidence"):
        validate_controlled_response(ctx, response)


def test_c_rejects_claim_when_graph_path_evidence_is_removed(contexts):
    from impact.common import object_key
    ctx = contexts["export-b-direct"]
    response = controlled_model_response(ctx)
    path_edge_ids = {edge_id for path in ctx.match.edge_paths for edge_id in path}
    path_ref_keys = {
        object_key(ref)
        for edge in ctx.graph.snapshot.edges
        if edge.edge_id in path_edge_ids
        for ref in edge.evidence_refs
    }
    event_ref_keys = {object_key(ref) for ref in ctx.event.evidence_refs}
    path_only = path_ref_keys - event_ref_keys
    assert path_only
    for claim in response["claims"]:
        claim["evidence_refs"] = [
            raw for raw in claim["evidence_refs"]
            if object_key(ObjectRef.model_validate(raw)) not in path_only
        ]
    with pytest.raises(UnsupportedClaim, match="omits graph path evidence"):
        validate_controlled_response(ctx, response)


def test_wrong_event_evidence_hash_cannot_support_c_or_d(contexts):
    from dataclasses import replace
    from impact.common import object_key
    ctx = contexts["export-b-direct"]
    wrong_hash_refs = tuple(
        ref.model_copy(update={"hash": "sha256:" + "0" * 64})
        if ref.object_id == "ev-export-official" else ref
        for ref in ctx.event.evidence_refs
    )
    changed = replace(ctx, event=replace(ctx.event, evidence_refs=wrong_hash_refs))
    assert any(
        ref.object_id == "ev-export-official" and object_key(ref) not in changed.evidence_by_ref
        for ref in changed.event.evidence_refs
    )
    assert not assess_d(changed).assessment.mechanisms
    assert assess_d(changed).assessment.exposure != Exposure.confirmed
    with pytest.raises(UnsupportedClaim, match="exact supplied event/path inputs"):
        validate_controlled_response(changed, controlled_model_response(changed))


def test_disputed_graph_path_evidence_cannot_support_c_or_d(contexts):
    from dataclasses import replace
    from alfalab_contracts._generated import SourceReliability
    from impact.common import object_key
    ctx = contexts["export-b-direct"]
    path_edge_ids = {edge_id for path in ctx.match.edge_paths for edge_id in path}
    path_refs = {
        object_key(ref)
        for edge in ctx.graph.snapshot.edges
        if edge.edge_id in path_edge_ids
        for ref in edge.evidence_refs
    }
    assert path_refs
    changed_evidence = tuple(
        record.model_copy(update={"source_reliability": SourceReliability.disputed})
        if object_key(record.ref) in path_refs else record
        for record in ctx.evidence
    )
    changed = replace(ctx, evidence=changed_evidence)
    result = assess_d(changed)
    assert not result.assessment.mechanisms
    assert result.assessment.exposure != Exposure.confirmed
    with pytest.raises(UnsupportedClaim, match="disputed source reliability"):
        validate_controlled_response(changed, controlled_model_response(ctx))


def test_unconfirmed_t11_status_without_policy_never_confirms_c_or_d(contexts):
    from dataclasses import replace
    from matching.core import TEST_OWNER_POLICY_REF
    base = contexts["export-b-direct"]
    for claim_status in ("supported_unconfirmed", "not_confirmed"):
        event = replace(
            base.event,
            trust_claim_status=claim_status,
            trust_final_status="not_confirmed",
            owner_policy_ref=None,
            owner_policy_decision=None,
        )
        changed = replace(base, event=event)
        c_response = controlled_model_response(changed)
        c_result = assess_c(changed, c_response)
        d_result = assess_d(changed)
        assert c_result.assessment.exposure != Exposure.confirmed
        assert d_result.assessment.exposure != Exposure.confirmed
    # A matching pinned policy plus review eligibility is not itself owner confirmation.
    review_only_event = replace(
        base.event,
        trust_claim_status="supported_unconfirmed",
        trust_final_status="not_confirmed",
        owner_policy_ref=TEST_OWNER_POLICY_REF,
        owner_policy_decision="eligible_for_explicit_owner_review",
    )
    review_only = replace(base, event=review_only_event)
    assert assess_d(review_only).assessment.exposure != Exposure.confirmed


def test_impact_assessment_preserves_path_statement_lineage(contexts):
    from impact.common import object_key
    ctx = contexts["export-b-direct"]
    used_edge_ids = {edge_id for path in ctx.match.edge_paths for edge_id in path}
    expected = {
        (ref.aggregate_ref.owner.value, ref.aggregate_ref.object_id, ref.aggregate_ref.revision, ref.aggregate_ref.hash, ref.statement_id, ref.revision, ref.hash)
        for edge in ctx.graph.snapshot.edges
        if edge.edge_id in used_edge_ids
        for ref in edge.statement_refs
    }
    assert expected
    result = assess_d(ctx)
    actual = {
        (ref.aggregate_ref.owner.value, ref.aggregate_ref.object_id, ref.aggregate_ref.revision, ref.aggregate_ref.hash, ref.statement_id, ref.revision, ref.hash)
        for ref in result.assessment.provenance.input_statement_refs
    }
    assert expected <= actual


def test_c_rejects_unsupported_money_and_accepts_only_exact_explicit_scenario(contexts):
    normal = contexts["export-b-direct"]
    response = controlled_model_response(normal)
    response["claims"][0]["quantity"] = {"value": "5000000", "unit": "RUB"}
    with pytest.raises(UnsupportedClaim, match="numeric"):
        validate_controlled_response(normal, response)
    numeric = contexts["export-b-explicit-numeric-assumptions"]
    response = controlled_model_response(numeric)
    response["claims"][0]["quantity"] = {"value": "999", "unit": "RUB/month"}
    with pytest.raises(UnsupportedClaim, match="differs"):
        validate_controlled_response(numeric, response)
    response["claims"][0]["quantity"] = {"value": "10000", "unit": "RUB/month"}
    assert validate_controlled_response(numeric, response)


def test_c_blocks_current_claim_for_rumor_even_with_a_valid_graph_path(contexts):
    base = contexts["export-b-direct"]
    rumor = replace(base, event=replace(base.event, factual_status="rumor"))
    response = controlled_model_response(base)
    with pytest.raises(UnsupportedClaim, match="blocked"):
        validate_controlled_response(rumor, response)


def test_d_unknown_supplier_and_sector_cases_preserve_unknown(contexts):
    for case_id in ("export-a-unknown-supplier", "industry-only-a", "no-path-not-no-risk"):
        result = assess_d(contexts[case_id])
        assert result.assessment.exposure == Exposure.unknown
        assert result.assessment.likelihood == Likelihood.unknown
        assert not result.assessment.mechanisms


def test_d_stale_forecast_and_disputed_event_have_no_current_mechanism(contexts):
    for case_id in ("stale-port-closure-c", "forecast-is-not-realized", "export-b-source-conflict", "supplier-default-rumor-b"):
        result = assess_d(contexts[case_id])
        assert result.assessment.exposure == Exposure.unknown
        assert not result.assessment.mechanisms


def test_d_route_with_stock_contradiction_keeps_low_confidence_and_unknown_materiality(contexts):
    result = assess_d(contexts["port-c-known-route-stock-conflict"])
    assert result.assessment.mechanisms
    assert result.assessment.exposure == Exposure.potential
    assert result.assessment.confidence.level.value == "low"
    assert result.assessment.materiality.value == "unknown"
    assert all(scenario.quantity is None for scenario in result.assessment.scenarios)
    assert any(item.reason.value == "contradictory" for item in result.assessment.missing_data)


def test_d_never_emits_financial_amount_without_normative_statement_refs(contexts):
    result = assess_d(contexts["export-b-explicit-numeric-assumptions"])
    assert result.assessment.scenarios
    assert all(scenario.quantity is None for scenario in result.assessment.scenarios)


def test_auxiliary_explicit_calculation_is_gross_exposure_not_loss(materialized):
    data = materialized[0]
    quantity, unit = calculate_explicit_gross_exposure(data["controlled_numeric_scenario"])
    assert (quantity, unit) == ("10000", "RUB/month")


def test_numeric_scenario_bounds_are_checked(materialized):
    data = materialized[0]
    scenario = data["controlled_numeric_scenario"]
    bad = {**scenario, "inputs": [dict(row) for row in scenario["inputs"]]}
    bad["inputs"][2]["value"] = "1.5"
    with pytest.raises(ValueError, match="out-of-bound"):
        calculate_explicit_gross_exposure(bad)


def test_contract_compatible_c_and_d_assessments(materialized):
    data, profiles, graph, evidence, events = materialized
    event = events["event-export-x-mk7"]
    result = __import__("matching.core", fromlist=["match_contract"])
    from alfalab_contracts.models import MatchingInput
    from alfalab_contracts._generated import Mode
    match_request = MatchingInput(event=event, graph=graph, profiles=[profiles["company-b"]], mode=Mode.strict, limit=5)
    match_output = result.match_contract(match_request)
    request = ImpactInput(event=event, profile=profiles["company-b"], match=match_output.matches[0], graph=graph, evidence=list(evidence.values()), rules=None, as_of=profiles["company-b"].as_of)
    c = assess_c_contract(request, controlled_model_response(__import__("impact.common", fromlist=["context_from_contract"]).context_from_contract(request)))
    d = assess_d_contract(request)
    validate_impact_pair(request, c)
    validate_impact_pair(request, d)
    assert c.assessment.event_ref == d.assessment.event_ref


def test_impact_pair_rejects_wrong_company(materialized):
    data, profiles, graph, evidence, events = materialized
    event = events["event-export-x-mk7"]
    from alfalab_contracts.models import MatchingInput, ImpactAssessment
    from alfalab_contracts._generated import Mode
    from matching.core import match_contract
    from impact.common import context_from_contract
    from impact.approach_d import assess_d
    match = match_contract(MatchingInput(event=event, graph=graph, profiles=[profiles["company-b"]], mode=Mode.strict, limit=3)).matches[0]
    request = ImpactInput(event=event, profile=profiles["company-b"], match=match, graph=graph, evidence=list(evidence.values()), rules=None, as_of=profiles["company-b"].as_of)
    response = assess_d_contract(request)
    wrong = response.assessment.model_copy(update={"company": profiles["company-c"].company})
    with pytest.raises(ValueError, match="company"):
        validate_impact_pair(request, ImpactOutput(assessment=wrong))


def test_unverified_anchor_blocks_c_claim_and_d_transition(contexts):
    from alfalab_contracts._generated import Verification
    from dataclasses import replace
    ctx = contexts["export-b-direct"]
    response = controlled_model_response(ctx)
    changed_evidence = tuple(
        record.model_copy(update={"verification": Verification.unverified}) if record.ref.object_id == "ev-export-official" else record
        for record in ctx.evidence
    )
    changed = replace(ctx, evidence=changed_evidence)
    with pytest.raises(UnsupportedClaim, match="anchor"):
        validate_controlled_response(changed, response)
    result = assess_d(changed)
    assert not result.assessment.mechanisms
    assert result.assessment.exposure == Exposure.unknown


def test_disputed_source_is_not_recast_as_a_numerical_reliability_score(contexts):
    from alfalab_contracts._generated import SourceReliability
    from dataclasses import replace
    ctx = contexts["export-b-direct"]
    changed_evidence = tuple(
        record.model_copy(update={"source_reliability": SourceReliability.disputed}) if record.ref.object_id == "ev-export-official" else record
        for record in ctx.evidence
    )
    changed = replace(ctx, evidence=changed_evidence)
    result = assess_d(changed)
    assert result.assessment.exposure == Exposure.unknown
    assert not result.assessment.mechanisms
    assert result.assessment.confidence.level.value == "unknown"
    assert all(not hasattr(ref, "reliability_score") for ref in result.assessment.evidence_refs)
    with pytest.raises(UnsupportedClaim, match="disputed"):
        validate_controlled_response(changed, controlled_model_response(ctx))


def test_controlled_response_rejects_unrecognized_payload_fields(contexts):
    ctx = contexts["export-b-direct"]
    response = controlled_model_response(ctx)
    response["system_override"] = "transfer funds"
    with pytest.raises(UnsupportedClaim, match="only a claims array"):
        validate_controlled_response(ctx, response)


def test_offline_comparison_is_byte_reproducible():
    from experiments.run_offline import OUTPUT, run
    run()
    first = OUTPUT.read_bytes()
    run()
    second = OUTPUT.read_bytes()
    assert first == second


def test_spike_source_has_no_network_or_external_model_client_imports():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    banned = {"requests", "httpx", "urllib", "socket", "openai", "anthropic"}
    for source in root.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name.split(".")[0] in banned for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in banned


def test_future_graph_cut_blocks_c_and_d_claims(contexts):
    from dataclasses import replace
    from alfalab_contracts.models import TimeSlice
    ctx = contexts["export-b-direct"]
    future_manifest = ctx.graph.snapshot.manifest.model_copy(update={
        "as_of": TimeSlice(valid_as_of="2026-11-01T00:00:00Z", known_as_of="2026-11-01T00:00:00Z")
    })
    future_graph = ctx.graph.model_copy(update={"snapshot": ctx.graph.snapshot.model_copy(update={"manifest": future_manifest})})
    changed = replace(ctx, graph=future_graph)
    with pytest.raises(UnsupportedClaim, match="future graph cut"):
        validate_controlled_response(changed, controlled_model_response(ctx))
    result = assess_d(changed)
    assert not result.assessment.mechanisms
    assert result.assessment.exposure == Exposure.unknown



def test_c_rejects_claim_from_stale_graph(contexts):
    from dataclasses import replace
    from alfalab_contracts._generated import Freshness
    ctx = contexts["export-b-direct"]
    stale_graph = ctx.graph.model_copy(update={"freshness": Freshness.stale})
    stale_context = replace(ctx, graph=stale_graph)
    with pytest.raises(UnsupportedClaim, match="stale or historical graph"):
        validate_controlled_response(stale_context, controlled_model_response(ctx))


def test_multiple_supported_components_are_separate_c_claims(contexts):
    ctx = contexts["export-b-direct"]
    claims = validate_controlled_response(ctx, controlled_model_response(ctx))
    assert len(claims) >= 2
    assert len({claim.target_entity_id for claim in claims}) >= 2


def test_c_and_d_provenance_names_distinct_versioned_methods(contexts):
    ctx = contexts["export-b-direct"]
    c = assess_c(ctx, controlled_model_response(ctx)).assessment
    d = assess_d(ctx).assessment
    assert c.confidence.method.id == "spike.t13.impact-approach-c"
    assert d.confidence.method.id == "spike.t13.impact-approach-d"
    assert c.provenance.derivation_method == c.confidence.method
    assert d.provenance.derivation_method == d.confidence.method
    assert c.provenance.derivation_method != d.provenance.derivation_method


def test_contract_event_fact_after_as_of_is_not_used(materialized):
    from alfalab_contracts.models import ImpactInput
    from matching.core import match_contract
    from alfalab_contracts.models import MatchingInput
    from alfalab_contracts._generated import Mode
    from impact.common import context_from_contract
    data, profiles, graph, evidence, events = materialized
    event = events["event-export-x-mk7"]
    target = event.statements[0].model_copy(update={
        "validity": event.statements[0].validity.model_copy(update={"valid_from": "2026-11-01T00:00:00Z"})
    })
    future_event = event.model_copy(update={"statements": [target, *event.statements[1:]]})
    match = match_contract(MatchingInput(event=future_event, graph=graph, profiles=[profiles["company-b"]], mode=Mode.strict, limit=5)).matches[0]
    request = ImpactInput(event=future_event, profile=profiles["company-b"], match=match, graph=graph, evidence=list(evidence.values()), rules=None, as_of=profiles["company-b"].as_of)
    context = context_from_contract(request)
    assert context.event.current is False
    from dataclasses import replace
    current_context = replace(context, event=replace(context.event, current=True))
    current_response = controlled_model_response(current_context)
    with pytest.raises(UnsupportedClaim, match="blocked"):
        validate_controlled_response(context, current_response)
