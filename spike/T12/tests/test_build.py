from __future__ import annotations

import json

import pytest

from alfalab_contracts.models import BuildGraphInput, CodeRef, EntityRef, Statement, StatementRef, TimeSlice

from t12_graph_spike import (
    GraphBuildError,
    GraphRules,
    build_graph,
    canonical_hash,
    canonical_statement_hash,
    default_graph_rules,
)

from helpers import (
    build_shared_request,
    build_t12_input,
    shared_data,
    validate_json,
)


def build_shared():
    request, refs, aggregate_refs = build_shared_request()
    artifacts = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    return request, refs, aggregate_refs, artifacts


def edge_for(candidate, statement_id: str):
    return next(
        edge for edge in candidate.edges
        if any(ref.statement_id == statement_id for ref in edge.statement_refs)
    )


def test_shared_dataset_is_pinned_provisional_and_contains_all_graph_cases():
    manifest, data = shared_data()
    assert manifest["version"] == "1.0.1"
    assert manifest["manual_approval"] == "provisional"
    assert manifest["status"] == "provisional_not_gold_not_approved"
    case_ids = {row["case_id"] for row in data["t12_graph_cases"]}
    assert len(case_ids) == 15
    assert case_ids == {
        "direct-country-supplier-company-path",
        "direct-company-to-port",
        "indirect-company-c-route",
        "no-supplier-path-for-a",
        "unknown-is-not-negative",
        "stock-conflict",
        "current-projection",
        "relevant-update-stales-projection",
        "unrelated-partition-update",
        "historical-supplier-edge",
        "alias-does-not-merge-legal-entities",
        "alternate-ontology",
        "hypothetical-only",
        "inferred-relation-grounding",
        "explicit-negative-not-positive-dependency",
    }


def test_build_emits_only_explicit_direct_relations_and_exact_refs():
    request, refs, _aggregate_refs, artifacts = build_shared()
    candidate = artifacts.output.candidate
    assert candidate.revision == 0
    assert candidate.completeness == "partial"
    assert len(candidate.edges) == 15
    assert len(artifacts.temporal_edge_contexts) == 15
    assert candidate.graph_id == "graph-shared-companies-current"
    assert all(edge.relation.namespace == candidate.manifest.ontology.id for edge in candidate.edges)
    assert all(edge.relation.version == candidate.manifest.ontology.version for edge in candidate.edges)
    context_by_edge = {item.edge_id: item for item in artifacts.temporal_edge_contexts}
    assert all(len(edge.statement_refs) == 1 for edge in candidate.edges)
    for edge in candidate.edges:
        statement_ref = edge.statement_refs[0]
        statement = next(
            item
            for item in request.knowledge.statements
            if (item.statement_id, item.revision) == (statement_ref.statement_id, statement_ref.revision)
        )
        assert statement_ref == refs[(statement.statement_id, statement.revision)]
        assert statement_ref.hash == canonical_statement_hash(statement)
        context = context_by_edge[edge.edge_id]
        assert context.statement_ref == statement_ref
        assert context.valid_from == statement.validity.valid_from
        assert context.valid_to == statement.validity.valid_to
    assert {ref.statement_id for edge in candidate.edges for ref in edge.statement_refs} == {
        "b-buys-microkaskad",
        "b-supplier-supplies-mk7",
        "b-uses-mk7",
        "b-supplier-country",
        "b-site",
        "b-route-vega",
        "b-secondary-supplier",
        "b-secondary-component",
        "c-current-supplier",
        "c-supplier-supplies-nickel",
        "c-supplier-route",
        "c-uses-nickel",
        "c-warehouse",
        "c-route-vega",
        "c-route-port",
    }


def test_missing_direct_statement_ref_does_not_create_edge_or_fake_hash():
    request, refs, aggregate_refs = build_shared_request()
    refs.pop(("b-buys-microkaskad", 1))
    candidate = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    ).output.candidate
    assert not any(ref.statement_id == "b-buys-microkaskad" for edge in candidate.edges for ref in edge.statement_refs)
    missing = {datum.path: datum for datum in candidate.missing_data}
    assert missing["/statements/b-buys-microkaskad"].reason == "unavailable"
    assert "exact direct StatementRef was not supplied" in missing["/statements/b-buys-microkaskad"].detail


def test_hash_and_aggregate_identity_tampering_are_rejected():
    request, refs, aggregate_refs = build_shared_request()
    ref = refs[("b-buys-microkaskad", 1)].model_copy(update={"hash": "sha256:" + "0" * 64})
    refs[("b-buys-microkaskad", 1)] = ref
    with pytest.raises(GraphBuildError, match="canonical statement content"):
        build_graph(request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=default_graph_rules(request.ontology))

    request, refs, aggregate_refs = build_shared_request()
    wrong_aggregate = aggregate_refs[0]
    wrong_ref = refs[("b-buys-microkaskad", 1)].model_copy(
        update={"aggregate_ref": wrong_aggregate}
    )
    refs[("b-buys-microkaskad", 1)] = wrong_ref
    unprovided_aggregate_refs = [item for item in aggregate_refs if item != wrong_aggregate]
    with pytest.raises(GraphBuildError, match="not among the explicitly supplied slices"):
        build_graph(request, statement_ref_index=refs, aggregate_refs=unprovided_aggregate_refs, rules=default_graph_rules(request.ontology))


def test_untrusted_near_names_do_not_create_or_merge_edges():
    _request, _refs, _aggregate_refs, artifacts = build_shared()
    candidate = artifacts.output.candidate
    node_ids_by_entity = {node.entity.entity_id: node.node_id for node in candidate.nodes}
    assert "company-a-near" not in node_ids_by_entity
    assert node_ids_by_entity["company-b"] != node_ids_by_entity["supplier-b-x"]
    assert all(
        "company-a-near" not in (edge.source_node_id, edge.target_node_id)
        for edge in candidate.edges
    )
    # The catalog has near-name parent/subsidiary IDs, but no explicit alias
    # authorization or ownership statement links them to company-b.
    parent_ids = {
        node.node_id
        for node in candidate.nodes
        if node.entity.entity_id in {"company-b-parent", "company-b-subsidiary"}
    }
    assert not any(
        {edge.source_node_id, edge.target_node_id} & parent_ids
        for edge in candidate.edges
    )


def test_parent_subsidiary_and_near_name_ids_remain_distinct_without_asserted_link():
    _manifest, data = shared_data()
    request, refs, aggregate_refs = build_shared_request()
    extra_entities = [
        validate_json(EntityRef, item)
        for item in data["entities"]
        if item["entity_id"] in {"company-b-parent", "company-b-subsidiary", "company-a-near"}
    ]
    expanded = request.knowledge.model_copy(
        update={"entities": [*request.knowledge.entities, *extra_entities]}
    )
    expanded_request = BuildGraphInput(
        graph_id=request.graph_id,
        knowledge=expanded,
        ontology=request.ontology,
        rules=request.rules,
    )
    candidate = build_graph(
        expanded_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    ).output.candidate
    ids = {node.entity.entity_id: node.node_id for node in candidate.nodes}
    assert ids["company-b-parent"] != ids["company-b-subsidiary"]
    assert ids["company-a-near"] != ids["company-b"]
    assert not any(
        {edge.source_node_id, edge.target_node_id}
        & {ids["company-b-parent"], ids["company-b-subsidiary"], ids["company-a-near"]}
        for edge in candidate.edges
    )


def test_explicit_unknown_is_missing_not_negative_and_expired_link_is_not_current():
    _request, _refs, _aggregate_refs, artifacts = build_shared()
    candidate = artifacts.output.candidate
    missing = {datum.path: datum for datum in candidate.missing_data}
    assert "/statements/a-supplier-unknown" in missing
    assert missing["/statements/a-supplier-unknown"].reason == "not_provided"
    assert not any(edge.source_node_id == "node-company-a" for edge in candidate.edges)
    assert not any(ref.statement_id == "c-old-supplier" for edge in candidate.edges for ref in edge.statement_refs)
    assert any(
        item.statement.statement_id == "c-old-supplier" and item.reason == "expired_at_cut"
        for item in artifacts.preserved_statements
    )


def test_disputed_non_graph_claims_are_preserved_without_collapsing_values():
    _request, _refs, _aggregate_refs, artifacts = build_shared()
    candidate = artifacts.output.candidate
    disputed = {
        item.statement.statement_id: item.statement
        for item in artifacts.preserved_statements
        if item.statement.epistemic_status == "disputed"
    }
    assert set(disputed) == {"c-stock-8-days", "c-stock-12-days"}
    assert disputed["c-stock-8-days"].value.value == "8"
    assert disputed["c-stock-12-days"].value.value == "12"
    assert not any(edge.relation.code == "inventory_cover" for edge in candidate.edges)


def test_hypothetical_and_explicit_negative_statements_remain_in_sidecar_only():
    for input_id, expected_reason in (
        ("hypothetical-only", "hypothetical_not_projected_as_fact"),
        ("explicit-negative-country-x", "explicit_negative_not_graph_edge"),
    ):
        request, refs, aggregate_refs, _row = build_t12_input(input_id)
        before = [item.model_dump(mode="json") for item in request.knowledge.statements]
        artifacts = build_graph(
            request,
            statement_ref_index=refs,
            aggregate_refs=aggregate_refs,
            rules=default_graph_rules(request.ontology),
        )
        preserved = {
            item.statement.statement_id: item
            for item in artifacts.preserved_statements
        }
        target = "a-hypothetical-source-country-x" if input_id == "hypothetical-only" else "a-explicit-not-source-country-x"
        assert preserved[target].reason == expected_reason
        assert preserved[target].statement_ref is not None
        assert all(edge.target_node_id != "node-country-x" for edge in artifacts.output.candidate.edges)
        assert [item.model_dump(mode="json") for item in request.knowledge.statements] == before
    negative, _ = build_t12_input("explicit-negative-country-x")[:2]
    assert next(s for s in negative.knowledge.statements if s.statement_id == "a-explicit-not-source-country-x").epistemic_status == "user_declared"


def test_inferred_edge_requires_resolvable_inputs_and_keeps_method_and_status():
    request, refs, aggregate_refs, _ = build_t12_input("inferred-company-country-x", include_candidate_as_of=True)
    before = [item.model_dump(mode="json") for item in request.knowledge.statements]
    artifacts = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    edge = next(edge for edge in artifacts.output.candidate.edges if edge.relation.code == "depends_on_country")
    assert edge.epistemic_status == "inferred"
    inferred_context = next(item for item in artifacts.temporal_edge_contexts if item.edge_id == edge.edge_id)
    assert inferred_context.statement_ref is None
    assert inferred_context.statement_id == "b-inferred-country-x-dependency"
    assert {ref.statement_id for ref in inferred_context.input_statement_refs} == {
        "b-buys-microkaskad",
        "b-supplier-country",
    }
    assert edge.statement_refs == []
    assert edge.provenance.derivation_method.id == "spike.graph.rule.company-supplier-location"
    assert {ref.statement_id for ref in edge.provenance.input_statement_refs} == {
        "b-buys-microkaskad",
        "b-supplier-country",
    }
    assert all(ref.statement_id in {s.statement_id for s in request.knowledge.statements} for ref in edge.provenance.input_statement_refs)
    assert [item.model_dump(mode="json") for item in request.knowledge.statements] == before


def test_inferred_candidate_recorded_after_known_cut_is_not_leaked_into_history():
    request, refs, aggregate_refs, _ = build_t12_input("inferred-company-country-x")
    artifacts = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    assert not any(edge.relation.code == "depends_on_country" for edge in artifacts.output.candidate.edges)
    assert any(item.statement.statement_id == "b-inferred-country-x-dependency" and item.reason == "not_known_at_cut" for item in artifacts.preserved_statements)


def test_alternate_ontology_build_is_explicit_and_does_not_mutate_statements():
    request, refs, aggregate_refs = build_shared_request()
    before = [item.model_dump(mode="json") for item in request.knowledge.statements]
    alt_ontology = request.ontology.model_copy(
        update={
            "id": "spike.supply-chain-ontology-alt",
            "version": "2.0.0",
            "hash": "sha256:" + "a" * 64,
        }
    )
    alt_ref = request.rules.model_copy(
        update={"id": "spike.graph.rules-alt", "version": "2.0.0", "hash": "sha256:" + "b" * 64}
    )
    mappings = {
        ("alfalab.business", "1.0.1", "purchases_from"): CodeRef(
            namespace=alt_ontology.id,
            version=alt_ontology.version,
            code="buyer-supplies-from",
        )
    }
    alternate_rules = GraphRules(
        ref=alt_ref,
        ontology=alt_ontology,
        predicate_map=mappings,
    )
    alternate_request = BuildGraphInput(
        graph_id=request.graph_id,
        knowledge=request.knowledge,
        ontology=alt_ontology,
        rules=alt_ref,
    )
    candidate = build_graph(
        alternate_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=alternate_rules,
    ).output.candidate
    assert candidate.manifest.ontology == alt_ontology
    assert all(edge.relation.namespace == alt_ontology.id and edge.relation.version == "2.0.0" for edge in candidate.edges)
    assert all(edge.relation.code == "buyer-supplies-from" for edge in candidate.edges)
    assert [item.model_dump(mode="json") for item in request.knowledge.statements] == before


def test_unmapped_relations_are_not_inferred_and_invalid_entity_catalog_is_rejected():
    request, refs, aggregate_refs = build_shared_request()
    limited_rules = default_graph_rules(request.ontology, relation_codes=("purchases_from",))
    limited_request = BuildGraphInput(
        graph_id=request.graph_id,
        knowledge=request.knowledge,
        ontology=request.ontology,
        rules=limited_rules.ref,
    )
    candidate = build_graph(
        limited_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=limited_rules,
    ).output.candidate
    assert {edge.relation.code for edge in candidate.edges} == {"purchases_from"}
    assert any(datum.reason == "unsupported" for datum in candidate.missing_data)

    request, refs, aggregate_refs = build_shared_request()
    duplicate_entities = [*request.knowledge.entities, request.knowledge.entities[0].model_copy(update={"kind": request.knowledge.entities[-1].kind})]
    broken_knowledge = request.knowledge.model_copy(update={"entities": duplicate_entities})
    broken_request = BuildGraphInput(
        graph_id=request.graph_id,
        knowledge=broken_knowledge,
        ontology=request.ontology,
        rules=request.rules,
    )
    with pytest.raises(GraphBuildError, match="conflicting entity kinds"):
        build_graph(broken_request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=default_graph_rules(request.ontology))


def test_statement_and_entity_order_metamorphism_is_deterministic():
    request, refs, aggregate_refs = build_shared_request()
    rules = default_graph_rules(request.ontology)
    first = build_graph(request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=rules).output.candidate
    shuffled_knowledge = request.knowledge.model_copy(
        update={
            "statements": list(reversed(request.knowledge.statements)),
            "entities": list(reversed(request.knowledge.entities)),
            "slices": list(reversed(request.knowledge.slices)),
        }
    )
    shuffled = BuildGraphInput(
        graph_id=request.graph_id,
        knowledge=shuffled_knowledge,
        ontology=request.ontology,
        rules=request.rules,
    )
    second = build_graph(shuffled, statement_ref_index=dict(reversed(list(refs.items()))), aggregate_refs=list(reversed(aggregate_refs)), rules=rules).output.candidate
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert canonical_hash(first) == canonical_hash(second)


def test_debug_logging_does_not_include_statement_or_entity_payload(caplog):
    request, refs, aggregate_refs = build_shared_request()
    sentinel = "PRIVATE-COMPANY-PAYLOAD-DO-NOT-LOG"
    changed_entity = next(entity for entity in request.knowledge.entities if entity.entity_id == "company-a").model_copy(
        update={"display_name": sentinel}
    )
    entities = [changed_entity if entity.entity_id == "company-a" else entity for entity in request.knowledge.entities]
    safe_request = BuildGraphInput(
        graph_id=request.graph_id,
        knowledge=request.knowledge.model_copy(update={"entities": entities}),
        ontology=request.ontology,
        rules=request.rules,
    )
    caplog.set_level("DEBUG", logger="t12_graph_spike.core")
    build_graph(
        safe_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    assert sentinel not in caplog.text
    assert "PRIVATE-COMPANY-PAYLOAD" not in caplog.text


def test_irrelevant_text_and_display_name_changes_do_not_change_edges():
    request, refs, aggregate_refs = build_shared_request()
    rules = default_graph_rules(request.ontology)
    baseline = build_graph(request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=rules).output.candidate
    activity = next(s for s in request.knowledge.statements if s.statement_id == "a-activity-v2")
    changed_activity = activity.model_copy(update={"value": activity.value.model_copy(update={"value": "unrelated extra paragraph"})})
    statements = [changed_activity if s.statement_id == activity.statement_id else s for s in request.knowledge.statements]
    changed_knowledge = request.knowledge.model_copy(update={"statements": statements})
    changed_refs = {key: value for key, value in refs.items() if key != (activity.statement_id, activity.revision)}
    text_change = BuildGraphInput(graph_id=request.graph_id, knowledge=changed_knowledge, ontology=request.ontology, rules=request.rules)
    after_text = build_graph(text_change, statement_ref_index=changed_refs, aggregate_refs=aggregate_refs, rules=rules).output.candidate
    assert [(e.source_node_id, e.target_node_id, e.relation.code) for e in baseline.edges] == [(e.source_node_id, e.target_node_id, e.relation.code) for e in after_text.edges]

    company_a = next(e for e in request.knowledge.entities if e.entity_id == "company-a")
    renamed = company_a.model_copy(update={"display_name": "РадиоКомплект Северный филиал"})
    renamed_entities = [renamed if e.entity_id == company_a.entity_id else e for e in request.knowledge.entities]
    rename_request = BuildGraphInput(
        graph_id=request.graph_id,
        knowledge=request.knowledge.model_copy(update={"entities": renamed_entities}),
        ontology=request.ontology,
        rules=request.rules,
    )
    after_name = build_graph(rename_request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=rules).output.candidate
    assert [(e.source_node_id, e.target_node_id, e.relation.code) for e in baseline.edges] == [(e.source_node_id, e.target_node_id, e.relation.code) for e in after_name.edges]


def test_meaningful_valid_time_change_changes_edge_membership():
    request, refs, aggregate_refs = build_shared_request()
    rules = default_graph_rules(request.ontology)
    current = build_graph(request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=rules).output.candidate
    b_country = next(s for s in request.knowledge.statements if s.statement_id == "b-supplier-country")
    earlier_cut = request.knowledge.model_copy(
        update={
            "as_of": TimeSlice(
                known_as_of="2026-10-14T00:00:00Z",
                valid_as_of="2025-06-01T00:00:00Z",
            )
        }
    )
    historical_request = BuildGraphInput(
        graph_id="graph-b-2025-cut",
        knowledge=earlier_cut,
        ontology=request.ontology,
        rules=request.rules,
    )
    historical = build_graph(historical_request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=rules).output.candidate
    assert any(ref.statement_id == "b-supplier-country" for edge in current.edges for ref in edge.statement_refs)
    assert not any(ref.statement_id == "b-supplier-country" for edge in historical.edges for ref in edge.statement_refs)
    assert any(item.statement.statement_id == b_country.statement_id and item.reason == "not_yet_valid" for item in build_graph(historical_request, statement_ref_index=refs, aggregate_refs=aggregate_refs, rules=rules).preserved_statements)


def test_historical_cut_restores_expired_supplier_edge_from_exact_materialized_ref():
    request, refs, aggregate_refs = build_shared_request()
    old_statement = next(
        item for item in request.knowledge.statements if item.statement_id == "c-old-supplier"
    )
    company_c_aggregate = next(item for item in aggregate_refs if item.object_id == "company-c")
    refs[(old_statement.statement_id, old_statement.revision)] = StatementRef(
        aggregate_ref=company_c_aggregate,
        statement_id=old_statement.statement_id,
        revision=old_statement.revision,
        hash=canonical_statement_hash(old_statement),
    )
    historical_knowledge = request.knowledge.model_copy(
        update={
            "as_of": TimeSlice(
                known_as_of="2026-10-14T00:00:00Z",
                valid_as_of="2025-06-01T00:00:00Z",
            )
        }
    )
    historical_request = BuildGraphInput(
        graph_id="graph-company-c-historical",
        knowledge=historical_knowledge,
        ontology=request.ontology,
        rules=request.rules,
    )
    candidate = build_graph(
        historical_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    ).output.candidate
    edge_statement_ids = {ref.statement_id for edge in candidate.edges for ref in edge.statement_refs}
    assert "c-old-supplier" in edge_statement_ids
    assert "c-current-supplier" not in edge_statement_ids
    old_edge = edge_for(candidate, "c-old-supplier")
    assert old_edge.statement_refs[0].hash == canonical_statement_hash(old_statement)
    old_context = next(item for item in build_graph(
        historical_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    ).temporal_edge_contexts if item.edge_id == old_edge.edge_id)
    assert old_context.valid_to == old_statement.validity.valid_to


def test_multiple_revisions_of_one_statement_get_distinct_edge_ids():
    request, refs, aggregate_refs = build_shared_request()
    original = next(
        item for item in request.knowledge.statements
        if item.statement_id == "b-buys-microkaskad"
    )
    wire = original.model_dump(mode="json")
    wire["revision"] = 2
    revised = Statement.model_validate_json(
        json.dumps(wire, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )
    knowledge = request.knowledge.model_copy(update={
        "statements": [*request.knowledge.statements, revised]
    })
    request = request.model_copy(update={"knowledge": knowledge})
    refs = dict(refs)
    refs[(revised.statement_id, revised.revision)] = refs[
        (original.statement_id, original.revision)
    ].model_copy(update={
        "revision": revised.revision,
        "hash": canonical_statement_hash(revised),
    })

    candidate = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    ).output.candidate
    matching_edges = [
        edge for edge in candidate.edges
        if any(ref.statement_id == original.statement_id for ref in edge.statement_refs)
    ]
    assert len(matching_edges) == 2
    assert {
        ref.revision for edge in matching_edges for ref in edge.statement_refs
    } == {1, 2}
    assert len({edge.edge_id for edge in matching_edges}) == 2
