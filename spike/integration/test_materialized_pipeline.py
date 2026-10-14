from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "packages/contracts/src",
    "spike/T09/src",
    "spike/T10/src",
    "spike/T11/src",
    "spike/T12/src",
    "spike/T12/tests",
    "spike/T13",
):
    entry = str(ROOT / relative)
    if entry not in sys.path:
        sys.path.insert(0, entry)

from alfalab_contracts.models import ProfileInput, QuestionsInput, RecommendationInput, TimeSlice
from alfalab_contracts.semantics import validate_resolution_pair
from evidence_trust import SourceAssertion, assess_claim, check_anchor, project_catalog_record
from impact.approach_c import assess_c, controlled_model_response
from impact.approach_d import assess_d
from recommendations.propose import default_information_actions, propose
from t09_events.resolution import propose_resolution
from t09_events.scenarios import input_from_fixture, load_cases
from t10_business import propose_profile, propose_questions
from t12_graph_spike import build_graph, default_graph_rules
from experiments.run_offline import (
    DATASET,
    LOCAL_MATRIX,
    load_materialized_inputs,
    make_context,
)
from helpers import build_shared_request


DATA_HASH = "sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725"
AS_OF = TimeSlice(valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z")


@pytest.fixture(scope="session")
def materialized():
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.1"
    assert manifest["data_hash"] == DATA_HASH
    assert manifest["manual_approval"] == "provisional"
    return load_materialized_inputs()


@pytest.fixture(scope="session")
def scenario_rows():
    return json.loads(LOCAL_MATRIX.read_text(encoding="utf-8"))["scenarios"]


def _scenario(case_id: str, materialized, scenario_rows: list[dict]) -> ImpactContext:
    row = next(item for item in scenario_rows if item["case_id"] == case_id)
    return make_context(row, materialized)


def _profile_and_event(materialized, company_id: str, event_id: str):
    _data, profiles, _graph, _evidence, events = materialized
    return profiles[company_id], events[event_id]


def _t11_exact_anchor_result():
    data = json.loads((DATASET / "data.json").read_text(encoding="utf-8"))
    fixture = json.loads((ROOT / "spike/T11/fixtures/trust-cases-v1.0.0.json").read_text(encoding="utf-8"))
    case = next(item for item in fixture["cases"] if item["case_id"] == "exact-anchor")
    assertions = [
        SourceAssertion.from_mapping(row)
        for row in fixture["source_assertions"]
        if row["evidence_ref"] in set(case["evidence_refs"])
    ]
    catalog = {row["ref"]["object_id"]: row for row in data["evidence_catalog"]}
    sources = {row["document_id"]: row for row in data["source_documents"]}
    records = {key: project_catalog_record(catalog[key]) for key in case["evidence_refs"]}
    source_by_id = {
        record["source_ref"]["object_id"]: copy.deepcopy(sources[record["source_ref"]["object_id"]])
        for record in records.values()
    }
    return assess_claim(
        case["claim_id"], assertions, records, source_by_id,
        valid_as_of="2026-10-14T00:00:00Z",
        known_as_of="2026-10-14T00:00:00Z",
    ), records, source_by_id


def test_scenario_a_unknown_supplier_stays_unknown_and_gets_targeted_question(materialized, scenario_rows):
    context = _scenario("export-a-unknown-supplier", materialized, scenario_rows)
    c_result = assess_c(context, controlled_model_response(context))
    d_result = assess_d(context)

    profile, event = _profile_and_event(materialized, "company-a", "event-export-x-mk7")
    generated = propose_profile(ProfileInput(
        company=profile.company,
        description="Торговая компания продаёт радиодетали.",
        documents=[],
        answers=[],
        existing=None,
        as_of=AS_OF,
    ))
    generated_predicates = {item.predicate.code for item in generated.proposal.add_statements}
    assert generated_predicates == {"trades_in"}
    assert {"/dependencies/suppliers", "/sourcing/countries"} <= {
        item.path for item in generated.proposal.missing_data
    }

    # Model an unanswered profile from the materialized Business.read snapshot.
    question_profile = profile.model_copy(update={"answers": []})
    questions = propose_questions(
        QuestionsInput(profile=question_profile, event=event, question_history=[], budget=3)
    )
    recommendations = propose(RecommendationInput(
        assessment=d_result.assessment,
        audience="bank_manager",
        allowed_actions=default_information_actions(),
        constraints=["Informational only."],
    ))

    assert context.profile.company.entity_id == "company-a"
    assert context.match.edge_paths == []
    assert c_result.assessment.exposure.value == "unknown"
    assert d_result.assessment.exposure.value == "unknown"
    assert d_result.assessment.mechanisms == []
    assert all(item.quantity is None for item in d_result.assessment.scenarios)
    assert "supplier_countries" in {item.question_id for item in questions.questions}
    assert "ask_supplier_geography" in {item.action_type.code for item in recommendations.recommendations}


def test_scenario_b_uses_only_materialized_paths_and_does_not_invent_financial_loss(materialized, scenario_rows):
    context = _scenario("export-b-direct", materialized, scenario_rows)
    c_response = controlled_model_response(context)
    c_result = assess_c(context, c_response)
    d_result = assess_d(context)

    supplied_edge_ids = {edge.edge_id for edge in context.graph.snapshot.edges}
    assert context.match.edge_paths
    assert all(set(path) <= supplied_edge_ids for path in context.match.edge_paths)
    assert c_result.assessment.mechanisms or d_result.assessment.mechanisms
    assert all(item.quantity is None for item in c_result.assessment.scenarios)
    assert all(item.quantity is None for item in d_result.assessment.scenarios)
    assert any(item.code == "restricted_input_supply" for item in d_result.assessment.mechanisms)
    assert d_result.assessment.likelihood.value == "possible"
    assert d_result.assessment.materiality.value == "unknown"


def test_scenario_b_materializes_t11_result_before_t13_conditional_impact(materialized, scenario_rows):
    context = _scenario("export-b-direct", materialized, scenario_rows)
    trust, _records, _sources = _t11_exact_anchor_result()
    context = replace(context, event=replace(
        context.event,
        trust_claim_status=trust.status.value,
        trust_final_status=trust.final_status,
        owner_policy_ref=None,
        owner_policy_decision=None,
    ))

    c_result = assess_c(context, controlled_model_response(context))
    d_result = assess_d(context)

    assert trust.status.value == "supported_unconfirmed"
    assert trust.final_status == "not_confirmed"
    for result in (c_result, d_result):
        assert result.assessment.exposure.value == "potential"
        assert any(item.code == "restricted_input_supply" for item in result.assessment.mechanisms)
        assert all(item.quantity is None for item in result.assessment.scenarios)
        assert "/event/trusted_confirmation" in {item.path for item in result.assessment.missing_data}


def test_scenario_c_duplicate_publications_resolve_once_without_applying_to_a_database():
    case = next(
        item for item in load_cases()
        if item["fixture_id"].endswith("merge-duplicate-export-records")
    )
    request = input_from_fixture(case)
    response = propose_resolution(request)
    validate_resolution_pair(request, response)

    assert len(response.proposal.decisions) == 1
    decision = response.proposal.decisions[0]
    assert decision.action.value == "merge"
    assert len(decision.target_refs) == 2
    assert len(decision.proposed_events) == 1
    assert set(decision.mention_ids) == {item.mention_id for item in request.mentions}


def test_scenario_d_stale_and_conflicted_inputs_keep_uncertainty(materialized, scenario_rows):
    stale = _scenario("stale-port-closure-c", materialized, scenario_rows)
    stale_result = assess_d(stale)
    assert stale_result.assessment.exposure.value == "unknown"
    assert stale_result.assessment.mechanisms == []
    assert all(item.quantity is None for item in stale_result.assessment.scenarios)

    conflicted = _scenario("port-c-known-route-stock-conflict", materialized, scenario_rows)
    conflict_result = assess_d(conflicted)
    assert conflict_result.assessment.exposure.value == "potential"
    assert any(item.reason.value == "contradictory" for item in conflict_result.assessment.missing_data)
    assert all(item.quantity is None for item in conflict_result.assessment.scenarios)


def test_scenario_e_industry_similarity_alone_does_not_create_impact_or_action(materialized, scenario_rows):
    context = _scenario("industry-only-a", materialized, scenario_rows)
    c_result = assess_c(context, controlled_model_response(context))
    d_result = assess_d(context)
    recommendations = propose(RecommendationInput(
        assessment=d_result.assessment,
        audience="bank_manager",
        allowed_actions=default_information_actions(),
        constraints=["Informational only."],
    ))

    assert context.match.edge_paths == []
    assert c_result.assessment.exposure.value == "unknown"
    assert d_result.assessment.exposure.value == "unknown"
    assert c_result.assessment.mechanisms == []
    assert d_result.assessment.mechanisms == []
    assert recommendations.recommendations == []


def test_materialized_evidence_anchor_is_not_promoted_to_confirmed_fact(materialized):
    result, records, source_by_id = _t11_exact_anchor_result()
    anchor = check_anchor(records["ev-export-official"], source_by_id["doc-export-official"])
    assert anchor.integrity.value == "verified"
    assert result.status.value == "supported_unconfirmed"
    assert result.final_status == "not_confirmed"


def test_t12_graph_builder_and_t13_paths_share_real_explicit_edge_ids(materialized):
    request, statement_refs, aggregate_refs = build_shared_request()
    artifacts = build_graph(
        request,
        statement_ref_index=statement_refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    built_edges = artifacts.output.candidate.edges
    context = _scenario("export-b-direct", materialized, json.loads(LOCAL_MATRIX.read_text(encoding="utf-8"))["scenarios"])
    query_edge_ids = {edge.edge_id for edge in context.graph.snapshot.edges}

    def statement_ref_signatures(edges):
        return {
            json.dumps(ref.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            for edge in edges
            for ref in edge.statement_refs
        }

    built_business_b_refs = {
        json.dumps(ref.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for edge in built_edges
        for ref in edge.statement_refs
        if ref.statement_id.startswith("b-")
    }
    query_refs = statement_ref_signatures(context.graph.snapshot.edges)

    assert built_business_b_refs
    assert built_business_b_refs <= query_refs
    assert all(set(path) <= query_edge_ids for path in context.match.edge_paths)
    path_edges = [edge for edge in context.graph.snapshot.edges if edge.edge_id in set(context.match.edge_paths[0])]
    assert statement_ref_signatures(path_edges) <= built_business_b_refs
