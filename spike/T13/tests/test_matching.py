from __future__ import annotations

from alfalab_contracts.models import MatchingInput, MatchingOutput
from alfalab_contracts._generated import Exposure, Mode
from alfalab_contracts.semantics import validate_matching_pair
from pydantic import ValidationError
import pytest

from matching.core import EventContext, match_context, match_contract
from experiments.run_offline import load_materialized_inputs


def test_materialized_event_graph_profile_match_is_strict_contract_compatible():
    data, profiles, graph, evidence, events = load_materialized_inputs()
    request = MatchingInput(
        event=events["event-export-x-mk7"],
        graph=graph,
        profiles=[profiles["company-b"]],
        mode=Mode.strict,
        limit=10,
    )
    response = match_contract(request)
    assert response.candidate_scope == ["company-b"]
    assert response.matches[0].exposure == Exposure.potential
    assert response.matches[0].edge_paths
    assert response.matches[0].provenance.derivation_method.id == "spike.t13.matching"
    assert all(edge_id in {edge.edge_id for edge in graph.snapshot.edges} for path in response.matches[0].edge_paths for edge_id in path)
    validate_matching_pair(request, response)
    MatchingOutput.model_validate(response.model_dump(mode="json"))


def test_matching_candidate_scope_is_exact(contexts):
    ctx = contexts["export-b-direct"]
    output = match_context(ctx.event, ctx.graph, [ctx.profile], "balanced")
    assert output.candidate_scope == [ctx.profile.company.entity_id]
    assert output.search_complete_for_scope is False


def test_matching_unknown_is_not_no_risk(contexts):
    ctx = contexts["no-path-not-no-risk"]
    output = match_context(ctx.event, ctx.graph, [ctx.profile], "balanced")
    match = output.matches[0]
    assert match.exposure == Exposure.unknown
    assert not match.edge_paths
    assert output.search_complete_for_scope is False
    assert any(item.path == "/graph/completeness" for item in output.missing_data)


def test_sector_similarity_never_creates_match_path(contexts):
    ctx = contexts["industry-only-a"]
    output = match_context(ctx.event, ctx.graph, [ctx.profile], "broad")
    assert not any(match.edge_paths for match in output.matches)
    assert all(match.exposure == Exposure.unknown for match in output.matches)


def test_policy_modes_expand_only_explicit_edge_statuses(materialized):
    from alfalab_contracts.models import GraphSubgraph
    from alfalab_contracts._generated import EpistemicStatus
    data, profiles, graph, evidence, events = materialized
    event = EventContext(
        event_ref=events["event-export-x-mk7"].ref,
        event_type="export_restriction",
        target_entity_ids=("component-p12",),
        evidence_refs=tuple(record.ref for record in evidence.values()),
        factual_status="confirmed",
    )
    changed_edges = [
        edge.model_copy(update={"epistemic_status": EpistemicStatus.hypothetical})
        if edge.edge_id == "edge-b-secondary-uses" else edge
        for edge in graph.snapshot.edges
    ]
    changed = graph.model_copy(update={"snapshot": graph.snapshot.model_copy(update={"edges": changed_edges})})
    strict = match_context(event, changed, [profiles["company-b"]], "strict").matches[0]
    balanced = match_context(event, changed, [profiles["company-b"]], "balanced").matches[0]
    broad = match_context(event, changed, [profiles["company-b"]], "broad").matches[0]
    assert strict.exposure == Exposure.unknown and not strict.edge_paths
    assert balanced.exposure == Exposure.unknown and not balanced.edge_paths
    assert broad.exposure == Exposure.potential and broad.edge_paths == [["edge-b-secondary-uses"]]


def test_strict_depth_boundary_excludes_three_edge_route(materialized):
    data, profiles, graph, evidence, events = materialized
    event = EventContext(
        event_ref=events["event-export-x-mk7"].ref,
        event_type="port_closure",
        target_entity_ids=("port-vega",),
        evidence_refs=tuple(record.ref for record in evidence.values()),
        factual_status="confirmed",
    )
    chain_graph = graph.model_copy(update={"snapshot": graph.snapshot.model_copy(update={"edges": [edge for edge in graph.snapshot.edges if edge.edge_id != "edge-c-ships-route"]})})
    strict = match_context(event, chain_graph, [profiles["company-c"]], "strict").matches[0]
    balanced = match_context(event, chain_graph, [profiles["company-c"]], "balanced").matches[0]
    assert strict.exposure == Exposure.unknown and strict.edge_paths == []
    assert balanced.edge_paths and len(balanced.edge_paths[0]) == 3


def test_broad_can_report_stale_path_only_as_potential(materialized):
    from alfalab_contracts._generated import Freshness
    data, profiles, graph, evidence, events = materialized
    stale_graph = graph.model_copy(update={"freshness": Freshness.stale})
    event = EventContext.from_record(events["event-export-x-mk7"])
    strict = match_context(event, stale_graph, [profiles["company-b"]], "strict").matches[0]
    broad = match_context(event, stale_graph, [profiles["company-b"]], "broad").matches[0]
    assert strict.exposure == Exposure.unknown and not strict.edge_paths
    assert broad.exposure == Exposure.potential and broad.edge_paths
    assert any(item.path == "/graph/freshness" for item in broad.missing_data)


def test_reordering_edges_preserves_matching_result(contexts):
    ctx = contexts["export-b-direct"]
    reversed_graph = ctx.graph.model_copy(update={"snapshot": ctx.graph.snapshot.model_copy(update={"edges": list(reversed(ctx.graph.snapshot.edges))})})
    before = match_context(ctx.event, ctx.graph, [ctx.profile], "balanced").model_dump(mode="json")
    after = match_context(ctx.event, reversed_graph, [ctx.profile], "balanced").model_dump(mode="json")
    assert before == after


def test_relevant_semantic_change_confirmed_to_hypothetical_changes_result(contexts):
    from alfalab_contracts._generated import EpistemicStatus
    from dataclasses import replace
    ctx = contexts["export-b-direct"]
    ctx = replace(ctx, event=replace(ctx.event, target_entity_ids=("component-mk7",)))
    changed_edges = [
        edge.model_copy(update={"epistemic_status": EpistemicStatus.hypothetical})
        if edge.edge_id in {"edge-b-uses-mk7", "edge-b-purchases-microkaskad", "edge-microkaskad-supplies-mk7"} else edge
        for edge in ctx.graph.snapshot.edges
    ]
    changed_graph = ctx.graph.model_copy(update={"snapshot": ctx.graph.snapshot.model_copy(update={"edges": changed_edges})})
    strict_before = match_context(ctx.event, ctx.graph, [ctx.profile], "strict").matches[0]
    strict_after = match_context(ctx.event, changed_graph, [ctx.profile], "strict").matches[0]
    assert strict_before.exposure == Exposure.potential
    assert strict_after.exposure == Exposure.unknown


def test_fake_edge_path_is_rejected_by_semantic_contract(materialized):
    data, profiles, graph, evidence, events = materialized
    request = MatchingInput(event=events["event-export-x-mk7"], graph=graph, profiles=[profiles["company-b"]], mode=Mode.strict, limit=5)
    valid = match_contract(request)
    bad_match = valid.matches[0].model_copy(update={"edge_paths": [["not-in-graph"]]})
    bad = valid.model_copy(update={"matches": [bad_match]})
    with pytest.raises(ValueError):
        validate_matching_pair(request, bad)


def test_duplicate_profile_scope_rejected(contexts):
    ctx = contexts["export-b-direct"]
    with pytest.raises(ValueError, match="duplicate company IDs"):
        match_context(ctx.event, ctx.graph, [ctx.profile, ctx.profile], "balanced")



def test_reversing_edge_orientation_does_not_create_dependency(contexts):
    ctx = contexts["export-b-direct"]
    reversed_edges = [edge.model_copy(update={"source_node_id": edge.target_node_id, "target_node_id": edge.source_node_id}) for edge in ctx.graph.snapshot.edges]
    reversed_graph = ctx.graph.model_copy(update={"snapshot": ctx.graph.snapshot.model_copy(update={"edges": reversed_edges})})
    result = match_context(ctx.event, reversed_graph, [ctx.profile], "balanced").matches[0]
    assert result.exposure == Exposure.unknown
    assert result.edge_paths == []


def test_irrelevant_profile_edge_does_not_change_company_match(contexts):
    ctx = contexts["export-b-direct"]
    company_edges = [edge for edge in ctx.graph.snapshot.edges if edge.edge_id.startswith("edge-b-") or edge.edge_id.startswith("edge-microkaskad-") or edge.edge_id.startswith("edge-supplier-x-")]
    reduced = ctx.graph.model_copy(update={"snapshot": ctx.graph.snapshot.model_copy(update={"edges": company_edges})})
    before = match_context(ctx.event, ctx.graph, [ctx.profile], "balanced").matches[0]
    after = match_context(ctx.event, reduced, [ctx.profile], "balanced").matches[0]
    assert before.model_dump(mode="json") == after.model_dump(mode="json")


def test_mismatched_profile_slice_cannot_use_current_graph(contexts):
    ctx = contexts["export-b-direct"]
    profile = ctx.profile.model_copy(update={"slice": ctx.profile.slice.model_copy(update={"revision": 99})})
    response = match_context(ctx.event, ctx.graph, [profile], "broad")
    assert response.matches[0].exposure == Exposure.unknown
    assert response.matches[0].edge_paths == []
    assert any(item.path == "/graph/input_slices" for item in response.matches[0].missing_data)


def test_mismatched_slice_reason_survives_empty_none_found_filter(materialized):
    from alfalab_contracts._generated import Completeness
    data, profiles, graph, evidence, events = materialized
    complete_graph = graph.model_copy(update={
        "snapshot": graph.snapshot.model_copy(update={
            "completeness": Completeness.complete_for_declared_slice,
            "missing_data": [],
        }),
        "missing_slices": [],
        "traversal_truncated": False,
    })
    profile = profiles["company-b"].model_copy(update={
        "slice": profiles["company-b"].slice.model_copy(update={"revision": 99}),
        "missing_data": [],
        "contradictions": [],
    })
    event = EventContext.from_record(events["event-fire-east-plant"])
    response = match_context(event, complete_graph, [profile], "strict")
    assert response.matches
    assert response.matches[0].exposure == Exposure.unknown
    assert any(item.path == "/graph/input_slices" for item in response.missing_data)
    assert response.search_complete_for_scope is False


def test_inactive_confirmed_event_never_produces_confirmed_match(contexts):
    from dataclasses import replace
    ctx = contexts["export-b-direct"]
    inactive = replace(ctx.event, current=False)
    match = match_context(inactive, ctx.graph, [ctx.profile], "balanced").matches[0]
    assert match.exposure != Exposure.confirmed
    assert any(item.path == "/event/currentness" for item in match.missing_data)


def test_unconfirmed_trust_or_review_eligibility_never_confirms_matching(contexts):
    from dataclasses import replace
    from matching.core import TEST_OWNER_POLICY_REF
    ctx = contexts["export-b-direct"]
    for claim_status in ("supported_unconfirmed", "not_confirmed"):
        event = replace(
            ctx.event,
            trust_claim_status=claim_status,
            trust_final_status="not_confirmed",
            owner_policy_ref=TEST_OWNER_POLICY_REF,
            owner_policy_decision="eligible_for_explicit_owner_review",
        )
        match = match_context(event, ctx.graph, [ctx.profile], "balanced").matches[0]
        assert match.exposure != Exposure.confirmed


def test_complete_declared_scope_can_return_none_found_without_a_match(materialized):
    from alfalab_contracts._generated import Completeness
    data, profiles, graph, evidence, events = materialized
    event = EventContext(
        event_ref=events["event-fire-east-plant"].ref,
        event_type="facility_fire",
        target_entity_ids=("plant-east",),
        evidence_refs=tuple(record.ref for record in evidence.values()),
        factual_status="reported",
    )
    complete_snapshot = graph.snapshot.model_copy(update={"completeness": Completeness.complete_for_declared_slice, "missing_data": []})
    complete_graph = graph.model_copy(update={"snapshot": complete_snapshot, "missing_slices": [], "traversal_truncated": False})
    profile = profiles["company-b"].model_copy(update={"missing_data": [], "contradictions": []})
    response = match_context(event, complete_graph, [profile], "strict")
    assert response.matches == []
    assert response.search_complete_for_scope is True


def test_multiple_profile_scope_is_exact_and_has_no_cross_company_match(materialized):
    data, profiles, graph, evidence, events = materialized
    event = EventContext.from_record(events["event-export-x-mk7"])
    response = match_context(event, graph, [profiles["company-a"], profiles["company-b"], profiles["company-c"]], "balanced")
    assert response.candidate_scope == ["company-a", "company-b", "company-c"]
    assert {match.company.entity_id for match in response.matches} == {"company-a", "company-b", "company-c"}
    for match in response.matches:
        assert match.company.entity_id in response.candidate_scope



def test_complete_graph_does_not_turn_explicit_unknown_profile_into_none_found(materialized):
    from alfalab_contracts._generated import Completeness
    data, profiles, graph, evidence, events = materialized
    event = EventContext.from_record(events["event-export-x-mk7"])
    complete_graph = graph.model_copy(update={"snapshot": graph.snapshot.model_copy(update={"completeness": Completeness.complete_for_declared_slice, "missing_data": []}), "missing_slices": [], "traversal_truncated": False})
    profile = profiles["company-a"]
    response = match_context(event, complete_graph, [profile], "strict")
    assert response.matches[0].exposure == Exposure.unknown
    assert response.search_complete_for_scope is False


def test_limit_boundary_marks_output_incomplete(materialized):
    data, profiles, graph, evidence, events = materialized
    event = EventContext.from_record(events["event-export-x-mk7"])
    event = EventContext(event_ref=event.event_ref, event_type=event.event_type, target_entity_ids=("component-mk7", "port-vega"), evidence_refs=event.evidence_refs, factual_status="confirmed")
    response = match_context(event, graph, [profiles["company-b"], profiles["company-c"]], "balanced", limit=1)
    assert len(response.matches) == 1
    assert response.search_complete_for_scope is False
    assert any(item.path == "/matches" for item in response.missing_data)


def test_limit_outside_contract_bounds_fails_fast(contexts):
    ctx = contexts["export-b-direct"]
    with pytest.raises(ValueError, match="limit"):
        match_context(ctx.event, ctx.graph, [ctx.profile], "balanced", limit=0)
