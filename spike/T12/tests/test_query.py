from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from alfalab_contracts.models import Graph_publishRequest, QueryGraphInput, Statement, TimeSlice
from alfalab_contracts.registry import load_operation_registry, validate_operation_exchange

from t12_graph_spike import GraphQueryError, build_graph, canonical_statement_hash, default_graph_rules, query_graph
from t12_graph_spike.store import IsolatedGraphStore
from helpers import build_shared_request, graph_query_snapshot


ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "docs/specs/framework-v1/contracts/examples.json"


def _example(operation_id: str) -> dict:
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))["examples"]
    return deepcopy(next(row for row in examples if row["operation_id"] == operation_id))


def _published_graph():
    build_request, refs, aggregate_refs = build_shared_request()
    candidate = build_graph(
        build_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(build_request.ontology),
    ).output.candidate
    store = IsolatedGraphStore()
    example = _example("Graph.publish")
    example["request"]["payload"] = {"candidate": candidate.model_dump(mode="json"), "expected_revision": 0}
    request = Graph_publishRequest.model_validate_json(
        json.dumps(example["request"], ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )
    output = store.publish(request, source_statement_refs=refs)
    snapshot = store.snapshot(candidate.graph_id, 1)
    assert snapshot is not None
    return store, request, output, snapshot


def _query(snapshot, *, policy="allow_stale", seed_ids=None, max_depth=5, max_nodes=100, relations=None, as_of=None):
    payload = {
        "query": {
            "kind": "subgraph",
            "graph_id": snapshot.graph_id,
            "revision": snapshot.revision,
            "seed_ids": [] if seed_ids is None else seed_ids,
            "relations": [
                {
                    "namespace": snapshot.manifest.ontology.id,
                    "version": snapshot.manifest.ontology.version,
                    "code": code,
                }
                for code in (relations or [])
            ],
            "max_depth": max_depth,
            "max_nodes": max_nodes,
            "required_slices": [item.model_dump(mode="json") for item in snapshot.manifest.input_slices],
            "freshness_policy": policy,
            "as_of": (as_of or snapshot.manifest.as_of).model_dump(mode="json"),
        }
    }
    return QueryGraphInput.model_validate_json(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), strict=True
    )


def _scoped_query(snapshot, company_id, *, policy="allow_stale", seed_ids=None, **kwargs):
    query = _query(snapshot, policy=policy, seed_ids=seed_ids, **kwargs)
    required = [
        item
        for item in snapshot.manifest.input_slices
        if item.owner == "Business" and item.partition_id == company_id
    ]
    return QueryGraphInput(query=query.query.model_copy(update={"required_slices": required}))


def test_direct_and_indirect_paths_are_bounded_and_preserve_edge_direction():
    store, _request, _output, snapshot = _published_graph()
    query = _query(snapshot, seed_ids=["node-company-b"], max_depth=2)
    result = query_graph(query, snapshots=store.snapshots(), current_slices=snapshot.manifest.input_slices)
    assert result.subgraph.freshness == "current"
    assert "node-country-x" in {node.node_id for node in result.subgraph.snapshot.nodes}
    path_edges = {
        ref.statement_id: (edge.source_node_id, edge.target_node_id)
        for edge in result.subgraph.snapshot.edges
        for ref in edge.statement_refs
    }
    assert path_edges["b-buys-microkaskad"] == ("node-company-b", "node-supplier-b-x")
    assert path_edges["b-supplier-country"] == ("node-supplier-b-x", "node-country-x")

    company_c = query_graph(
        _query(snapshot, seed_ids=["node-company-c"], max_depth=2),
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert "node-port-vega" in {node.node_id for node in company_c.subgraph.snapshot.nodes}
    assert {"c-route-vega", "c-route-port"}.issubset(
        {
            ref.statement_id
            for edge in company_c.subgraph.snapshot.edges
            for ref in edge.statement_refs
        }
    )

    depth_one = query_graph(
        _query(snapshot, seed_ids=["node-company-b"], max_depth=1),
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert "node-country-x" not in {node.node_id for node in depth_one.subgraph.snapshot.nodes}
    assert depth_one.subgraph.traversal_truncated is True


def test_missing_path_is_not_interpreted_as_negative_and_unknown_seed_is_rejected():
    store, _request, _output, snapshot = _published_graph()
    no_path = query_graph(
        _query(snapshot, seed_ids=["node-company-a"]),
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert "node-company-a" in {node.node_id for node in no_path.subgraph.snapshot.nodes}
    assert not no_path.subgraph.snapshot.edges
    assert any(item.reason == "not_provided" for item in snapshot.missing_data)
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            _query(snapshot, seed_ids=["node-does-not-exist"]),
            snapshots=store.snapshots(),
            current_slices=snapshot.manifest.input_slices,
        )
    assert exc.value.code == "NOT_FOUND"


def test_bfs_node_boundary_and_deterministic_order():
    store, _request, _output, snapshot = _published_graph()
    one = query_graph(
        _query(snapshot, seed_ids=["node-company-b"], max_depth=5, max_nodes=2),
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    two = query_graph(
        _query(snapshot, seed_ids=["node-company-b"], max_depth=5, max_nodes=2),
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert len(one.subgraph.snapshot.nodes) == 2
    assert one.subgraph.traversal_truncated is True
    assert one.model_dump(mode="json") == two.model_dump(mode="json")
    assert [node.node_id for node in one.subgraph.snapshot.nodes] == sorted(node.node_id for node in one.subgraph.snapshot.nodes)
    assert [edge.edge_id for edge in one.subgraph.snapshot.edges] == sorted(edge.edge_id for edge in one.subgraph.snapshot.edges)


def test_relation_filter_limits_traversal_and_returned_edges():
    store, _request, _output, snapshot = _published_graph()
    result = query_graph(
        _query(snapshot, seed_ids=["node-company-b"], max_depth=3, relations=["purchases_from"]),
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert result.subgraph.snapshot.edges
    assert {edge.relation.code for edge in result.subgraph.snapshot.edges} == {"purchases_from"}
    assert "node-country-x" not in {node.node_id for node in result.subgraph.snapshot.nodes}


def test_relevant_slice_change_is_stale_but_unrelated_slice_does_not_invalidate_scope():
    store, _request, _output, snapshot = _published_graph()
    changed = snapshot.manifest.input_slices[0].model_copy(update={"revision": snapshot.manifest.input_slices[0].revision + 1})
    stale = query_graph(
        _query(snapshot, policy="allow_stale"),
        snapshots=store.snapshots(),
        current_slices=[changed, *snapshot.manifest.input_slices[1:]],
    )
    assert stale.subgraph.freshness == "stale"
    assert stale.subgraph.missing_slices == [changed]
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            _query(snapshot, policy="current_required"),
            snapshots=store.snapshots(),
            current_slices=[changed, *snapshot.manifest.input_slices[1:]],
        )
    assert exc.value.code == "VERSION_CONFLICT"

    unrelated = snapshot.manifest.input_slices[0].model_copy(
        update={"partition_id": "unrelated-company", "selection_key": "profile@99"}
    )
    fresh = query_graph(
        _query(snapshot, policy="current_required"),
        snapshots=store.snapshots(),
        current_slices=[*snapshot.manifest.input_slices, unrelated],
    )
    assert fresh.subgraph.freshness == "current"


def test_scoped_company_b_currentness_ignores_unrelated_company_c_revision():
    store, _request, _output, snapshot = _published_graph()
    b_query = _scoped_query(
        snapshot,
        "company-b",
        policy="current_required",
        seed_ids=["node-company-b"],
        max_depth=0,
    )
    current_with_changed_c = [
        item.model_copy(update={"revision": item.revision + 1})
        if item.partition_id == "company-c"
        else item
        for item in snapshot.manifest.input_slices
    ]

    result = query_graph(
        b_query,
        snapshots=store.snapshots(),
        current_slices=current_with_changed_c,
    )

    assert result.subgraph.freshness == "current"
    assert result.subgraph.missing_slices == []
    assert result.subgraph.query_scope == ["company-b"]
    assert [node.node_id for node in result.subgraph.snapshot.nodes] == ["node-company-b"]
    assert result.subgraph.snapshot.edges == []
    assert all(
        ref.aggregate_ref.object_id == "company-b"
        for edge in result.subgraph.snapshot.edges
        for ref in [*edge.statement_refs, *edge.provenance.input_statement_refs]
    )


def test_scoped_company_b_changed_or_missing_current_slice_is_not_current():
    store, _request, _output, snapshot = _published_graph()
    b_query = _scoped_query(
        snapshot,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=0,
    )
    changed_b = [
        item.model_copy(update={"revision": item.revision + 1})
        if item.partition_id == "company-b"
        else item
        for item in snapshot.manifest.input_slices
    ]

    changed = query_graph(b_query, snapshots=store.snapshots(), current_slices=changed_b)
    assert changed.subgraph.freshness == "stale"
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=b_query.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=store.snapshots(),
            current_slices=changed_b,
        )
    assert exc.value.code == "VERSION_CONFLICT"

    missing_b = [item for item in snapshot.manifest.input_slices if item.partition_id != "company-b"]
    missing = query_graph(b_query, snapshots=store.snapshots(), current_slices=missing_b)
    assert missing.subgraph.freshness == "unknown"
    assert any(item.partition_id == "company-b" for item in missing.subgraph.missing_slices)
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=b_query.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=store.snapshots(),
            current_slices=missing_b,
        )
    assert exc.value.code == "VERSION_CONFLICT"


def test_empty_or_unresolvable_required_scope_cannot_be_current():
    store, _request, _output, snapshot = _published_graph()
    base = _scoped_query(snapshot, "company-b", seed_ids=["node-company-b"])
    empty = QueryGraphInput(query=base.query.model_copy(update={"required_slices": []}))
    empty_result = query_graph(
        empty,
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert empty_result.subgraph.freshness == "unknown"
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=empty.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=store.snapshots(),
            current_slices=snapshot.manifest.input_slices,
        )
    assert exc.value.code == "VERSION_CONFLICT"

    b_slice = next(item for item in snapshot.manifest.input_slices if item.partition_id == "company-b")
    unresolvable = b_slice.model_copy(update={"partition_id": "not-in-manifest"})
    unknown_scope = QueryGraphInput(
        query=base.query.model_copy(update={"required_slices": [unresolvable]})
    )
    result = query_graph(
        unknown_scope,
        snapshots=store.snapshots(),
        current_slices=[*snapshot.manifest.input_slices, unresolvable],
    )
    assert result.subgraph.freshness == "unknown"
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=unknown_scope.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=store.snapshots(),
            current_slices=[*snapshot.manifest.input_slices, unresolvable],
        )
    assert exc.value.code == "VERSION_CONFLICT"


def test_missing_or_unresolvable_edge_statement_ref_lineage_fails_closed():
    store, _request, _output, snapshot = _published_graph()
    selected = _scoped_query(
        snapshot,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=1,
        relations=["purchases_from"],
    )
    target = next(
        edge for edge in snapshot.edges
        if edge.source_node_id == "node-company-b"
        and any(ref.statement_id == "b-buys-microkaskad" for ref in edge.statement_refs)
    )
    ref = target.statement_refs[0]
    bad_ref = ref.model_copy(
        update={
            "aggregate_ref": ref.aggregate_ref.model_copy(update={"object_id": "unknown-company"})
        }
    )
    bad_edge = target.model_copy(
        update={
            "statement_refs": [bad_ref if item == ref else item for item in target.statement_refs],
            "provenance": target.provenance.model_copy(
                update={
                    "input_statement_refs": [
                        bad_ref if item == ref else item
                        for item in target.provenance.input_statement_refs
                    ]
                }
            ),
        }
    )
    unsafe_snapshot = snapshot.model_copy(
        update={
            "edges": [bad_edge if edge.edge_id == target.edge_id else edge for edge in snapshot.edges]
        }
    )
    snapshots = {(unsafe_snapshot.graph_id, unsafe_snapshot.revision): unsafe_snapshot}

    baseline = query_graph(
        selected,
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert baseline.subgraph.freshness == "current"

    result = query_graph(
        selected,
        snapshots=snapshots,
        current_slices=unsafe_snapshot.manifest.input_slices,
    )
    assert result.subgraph.freshness == "unknown"
    assert target.edge_id not in {edge.edge_id for edge in result.subgraph.snapshot.edges}
    assert target.target_node_id not in {
        node.node_id for node in result.subgraph.snapshot.nodes
    }
    assert any(
        item.reason == "not_observed"
        and item.path == f"/edges/{target.edge_id}/statement_refs"
        for item in result.subgraph.snapshot.missing_data
    )
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=selected.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=snapshots,
            current_slices=unsafe_snapshot.manifest.input_slices,
        )
    assert exc.value.code == "VERSION_CONFLICT"

    missing_lineage_edge = target.model_copy(
        update={
            "statement_refs": [],
            "provenance": target.provenance.model_copy(update={"input_statement_refs": []}),
        }
    )
    missing_lineage_snapshot = snapshot.model_copy(
        update={
            "edges": [
                missing_lineage_edge if edge.edge_id == target.edge_id else edge
                for edge in snapshot.edges
            ]
        }
    )
    missing_lineage_snapshots = {
        (missing_lineage_snapshot.graph_id, missing_lineage_snapshot.revision): missing_lineage_snapshot
    }
    missing_lineage = query_graph(
        selected,
        snapshots=missing_lineage_snapshots,
        current_slices=missing_lineage_snapshot.manifest.input_slices,
    )
    assert missing_lineage.subgraph.freshness == "unknown"
    assert target.edge_id not in {
        edge.edge_id for edge in missing_lineage.subgraph.snapshot.edges
    }
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=selected.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=missing_lineage_snapshots,
            current_slices=missing_lineage_snapshot.manifest.input_slices,
        )
    assert exc.value.code == "VERSION_CONFLICT"

    b_slice = next(item for item in snapshot.manifest.input_slices if item.partition_id == "company-b")
    ambiguous_snapshot = snapshot.model_copy(
        update={
            "manifest": snapshot.manifest.model_copy(
                update={
                    "input_slices": [
                        *snapshot.manifest.input_slices,
                        b_slice.model_copy(update={"selection_key": "alternate-selection"}),
                    ]
                }
            )
        }
    )
    ambiguous = query_graph(
        selected,
        snapshots={(ambiguous_snapshot.graph_id, ambiguous_snapshot.revision): ambiguous_snapshot},
        current_slices=ambiguous_snapshot.manifest.input_slices,
    )
    assert ambiguous.subgraph.freshness == "unknown"
    assert target.edge_id not in {
        edge.edge_id for edge in ambiguous.subgraph.snapshot.edges
    }


@pytest.mark.parametrize(
    "lineage_case",
    [
        "unknown_aggregate",
        "ambiguous_slice",
        "conflicting_statement_hash",
        "conflicting_aggregate_hash",
        "ref_less",
    ],
)
@pytest.mark.parametrize("policy", ["allow_stale", "historical"])
def test_invalid_edge_lineage_is_never_returned_or_traversed(lineage_case, policy):
    store, _request, _output, snapshot = _published_graph()
    target = next(
        edge
        for edge in snapshot.edges
        if edge.source_node_id == "node-company-b"
        and any(ref.statement_id == "b-buys-microkaskad" for ref in edge.statement_refs)
    )
    altered = target
    competing_edge = None
    manifest = snapshot.manifest

    if lineage_case == "unknown_aggregate":
        def invalidate(ref):
            if ref.statement_id != "b-buys-microkaskad":
                return ref
            return ref.model_copy(
                update={
                    "aggregate_ref": ref.aggregate_ref.model_copy(
                        update={"object_id": "unknown-owner"}
                    )
                }
            )

        altered = target.model_copy(
            update={
                "statement_refs": [invalidate(ref) for ref in target.statement_refs],
                "provenance": target.provenance.model_copy(
                    update={
                        "input_statement_refs": [
                            invalidate(ref) for ref in target.provenance.input_statement_refs
                        ]
                    }
                ),
            }
        )
    elif lineage_case == "ambiguous_slice":
        b_slice = next(item for item in manifest.input_slices if item.partition_id == "company-b")
        manifest = manifest.model_copy(
            update={
                "input_slices": [
                    *manifest.input_slices,
                    b_slice.model_copy(update={"selection_key": "alternate-selection"}),
                ]
            }
        )
    elif lineage_case in {"conflicting_statement_hash", "conflicting_aggregate_hash"}:
        competing_edge = next(
            edge
            for edge in snapshot.edges
            if edge.source_node_id == "node-company-c" and edge.statement_refs
        )
        target_ref = target.statement_refs[0]
        if lineage_case == "conflicting_statement_hash":
            competing_ref = target_ref.model_copy(
                update={"hash": "sha256:" + "f" * 64}
            )
        else:
            competing_ref = target_ref.model_copy(
                update={
                    "aggregate_ref": target_ref.aggregate_ref.model_copy(
                        update={"hash": "sha256:" + "e" * 64}
                    )
                }
            )
        competing_edge = competing_edge.model_copy(
            update={
                "statement_refs": [competing_ref for _ref in competing_edge.statement_refs],
                "provenance": competing_edge.provenance.model_copy(
                    update={
                        "input_statement_refs": [
                            competing_ref
                            for _ref in competing_edge.provenance.input_statement_refs
                        ]
                    }
                ),
            }
        )
    else:
        altered = target.model_copy(
            update={
                "statement_refs": [],
                "provenance": target.provenance.model_copy(update={"input_statement_refs": []}),
            }
        )

    unsafe_snapshot = snapshot.model_copy(
        update={
            "manifest": manifest,
            "edges": [
                altered
                if edge.edge_id == target.edge_id
                else competing_edge
                if competing_edge is not None and edge.edge_id == competing_edge.edge_id
                else edge
                for edge in snapshot.edges
            ],
        }
    )
    snapshots = {(unsafe_snapshot.graph_id, unsafe_snapshot.revision): unsafe_snapshot}
    query = _scoped_query(
        unsafe_snapshot,
        "company-b",
        policy=policy,
        seed_ids=["node-company-b"],
        max_depth=1,
        relations=["purchases_from"],
    )

    result = query_graph(
        query,
        snapshots=snapshots,
        current_slices=unsafe_snapshot.manifest.input_slices,
    )

    assert result.subgraph.freshness == "unknown"
    assert target.edge_id not in {edge.edge_id for edge in result.subgraph.snapshot.edges}
    assert target.target_node_id not in {
        node.node_id for node in result.subgraph.snapshot.nodes
    }
    assert any(
        item.reason == "not_observed"
        and item.path == f"/edges/{target.edge_id}/statement_refs"
        for item in result.subgraph.snapshot.missing_data
    )

    current_required = QueryGraphInput(
        query=query.query.model_copy(update={"freshness_policy": "current_required"})
    )
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            current_required,
            snapshots=snapshots,
            current_slices=unsafe_snapshot.manifest.input_slices,
        )
    assert exc.value.code == "VERSION_CONFLICT"


def test_same_local_statement_identity_in_distinct_aggregates_does_not_quarantine_edges():
    store, _request, _output, snapshot = _published_graph()
    b_edge = next(
        edge for edge in snapshot.edges
        if any(ref.statement_id == "b-buys-microkaskad" for ref in edge.statement_refs)
    )
    c_edge = next(
        edge for edge in snapshot.edges
        if any(ref.statement_id == "c-route-port" for ref in edge.statement_refs)
    )
    b_ref = next(ref for ref in b_edge.statement_refs if ref.statement_id == "b-buys-microkaskad")
    c_ref = next(ref for ref in c_edge.statement_refs if ref.statement_id == "c-route-port")
    c_local_ref = b_ref.model_copy(update={"aggregate_ref": c_ref.aggregate_ref})
    c_edge_with_local_identity = c_edge.model_copy(
        update={
            "statement_refs": [c_local_ref],
            "provenance": c_edge.provenance.model_copy(update={"input_statement_refs": []}),
        }
    )
    snapshot_with_distinct_aggregates = snapshot.model_copy(
        update={
            "edges": [
                c_edge_with_local_identity if edge.edge_id == c_edge.edge_id else edge
                for edge in snapshot.edges
            ]
        }
    )
    snapshots = {
        (snapshot_with_distinct_aggregates.graph_id, snapshot_with_distinct_aggregates.revision):
            snapshot_with_distinct_aggregates
    }
    query = _scoped_query(
        snapshot_with_distinct_aggregates,
        "company-b",
        seed_ids=["node-company-b", "node-supplier-b-x"],
        max_depth=0,
        relations=["purchases_from"],
    )

    baseline = query_graph(
        query,
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    result = query_graph(
        query,
        snapshots=snapshots,
        current_slices=snapshot.manifest.input_slices,
    )

    assert baseline.subgraph.freshness == "current"
    assert b_edge in baseline.subgraph.snapshot.edges
    assert result.subgraph.freshness == "current"
    assert b_edge in result.subgraph.snapshot.edges
    assert not any(
        item.path in {
            f"/edges/{b_edge.edge_id}/statement_refs",
            f"/edges/{c_edge.edge_id}/statement_refs",
        }
        for item in result.subgraph.snapshot.missing_data
    )

    # A single edge may carry statement and input refs from different
    # aggregates with the same local identity; query-local freshness must
    # also keep those references in their respective aggregate namespaces.
    c_edge_with_cross_aggregate_input = c_edge_with_local_identity.model_copy(
        update={
            "provenance": c_edge_with_local_identity.provenance.model_copy(
                update={"input_statement_refs": [b_ref]}
            )
        }
    )
    snapshot_with_two_aggregate_refs = snapshot.model_copy(
        update={
            "edges": [
                c_edge_with_cross_aggregate_input
                if edge.edge_id == c_edge.edge_id
                else edge
                for edge in snapshot.edges
            ]
        }
    )
    full_query = _query(
        snapshot_with_two_aggregate_refs,
        seed_ids=[
            "node-company-b",
            "node-supplier-b-x",
            "node-route-c-vega",
            "node-port-vega",
        ],
        max_depth=0,
    )
    full_result = query_graph(
        full_query,
        snapshots={
            (snapshot_with_two_aggregate_refs.graph_id, snapshot_with_two_aggregate_refs.revision):
                snapshot_with_two_aggregate_refs
        },
        current_slices=snapshot.manifest.input_slices,
    )
    full_edge_ids = {edge.edge_id for edge in full_result.subgraph.snapshot.edges}
    assert full_result.subgraph.freshness == "current"
    assert b_edge.edge_id in full_edge_ids
    assert c_edge.edge_id in full_edge_ids


def test_invalid_edge_outside_selected_boundary_does_not_change_scoped_freshness():
    _store, _request, _output, snapshot = _published_graph()
    target = next(
        edge for edge in snapshot.edges
        if any(ref.statement_id == "c-route-vega" for ref in edge.statement_refs)
    )
    invalid = target.model_copy(
        update={
            "statement_refs": [],
            "provenance": target.provenance.model_copy(update={"input_statement_refs": []}),
        }
    )
    unsafe = snapshot.model_copy(
        update={"edges": [invalid if edge.edge_id == target.edge_id else edge for edge in snapshot.edges]}
    )
    query = _scoped_query(
        unsafe,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=0,
    )

    result = query_graph(
        query,
        snapshots={(unsafe.graph_id, unsafe.revision): unsafe},
        current_slices=unsafe.manifest.input_slices,
    )

    assert result.subgraph.freshness == "current"
    assert not any(
        item.path == f"/edges/{target.edge_id}/statement_refs"
        for item in result.subgraph.snapshot.missing_data
    )


def test_invalid_edge_excluded_by_relation_filter_does_not_change_scoped_freshness():
    _store, _request, _output, snapshot = _published_graph()
    target = next(
        edge for edge in snapshot.edges
        if any(ref.statement_id == "b-site" for ref in edge.statement_refs)
    )
    invalid = target.model_copy(
        update={
            "statement_refs": [],
            "provenance": target.provenance.model_copy(update={"input_statement_refs": []}),
        }
    )
    unsafe = snapshot.model_copy(
        update={"edges": [invalid if edge.edge_id == target.edge_id else edge for edge in snapshot.edges]}
    )
    query = _scoped_query(
        unsafe,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=1,
        relations=["purchases_from"],
    )

    result = query_graph(
        query,
        snapshots={(unsafe.graph_id, unsafe.revision): unsafe},
        current_slices=unsafe.manifest.input_slices,
    )

    assert result.subgraph.freshness == "current"
    assert not any(
        item.path == f"/edges/{target.edge_id}/statement_refs"
        for item in result.subgraph.snapshot.missing_data
    )
    assert {edge.relation.code for edge in result.subgraph.snapshot.edges} == {"purchases_from"}


def test_selected_out_of_scope_edge_is_kept_with_full_provenance_but_freshness_unknown():
    store, _request, _output, snapshot = _published_graph()
    selected_c_edge = next(
        edge for edge in snapshot.edges
        if any(ref.statement_id == "c-route-port" for ref in edge.statement_refs)
    )
    query = _scoped_query(
        snapshot,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=2,
    )

    result = query_graph(
        query,
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )

    returned = {edge.edge_id: edge for edge in result.subgraph.snapshot.edges}
    assert selected_c_edge.edge_id in returned
    assert returned[selected_c_edge.edge_id] == selected_c_edge
    assert result.subgraph.freshness == "unknown"
    assert any(item.partition_id == "company-c" for item in result.subgraph.missing_slices)
    port = next(node for node in result.subgraph.snapshot.nodes if node.node_id == "node-port-vega")
    assert any(ref.statement_id == "c-route-port" for ref in port.statement_refs)

    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=query.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=store.snapshots(),
            current_slices=snapshot.manifest.input_slices,
        )
    assert exc.value.code == "VERSION_CONFLICT"


def test_selected_node_statement_refs_are_freshness_dependencies_without_filtering_provenance():
    store, _request, _output, snapshot = _published_graph()
    b_query = _scoped_query(
        snapshot,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=1,
    )

    result = query_graph(
        b_query,
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )

    port = next(node for node in result.subgraph.snapshot.nodes if node.node_id == "node-port-vega")
    assert any(ref.statement_id == "c-route-port" for ref in port.statement_refs)
    assert result.subgraph.freshness == "unknown"
    assert any(item.partition_id == "company-c" for item in result.subgraph.missing_slices)

    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            QueryGraphInput(query=b_query.query.model_copy(update={"freshness_policy": "current_required"})),
            snapshots=store.snapshots(),
            current_slices=snapshot.manifest.input_slices,
        )
    assert exc.value.code == "VERSION_CONFLICT"


def test_node_business_source_ref_outside_required_scope_makes_freshness_unknown():
    store, _request, _output, snapshot = _published_graph()
    port = next(node for node in snapshot.nodes if node.node_id == "node-port-vega")
    b_ref = next(ref for ref in port.statement_refs if ref.statement_id == "b-route-vega")
    c_ref = next(
        edge.statement_refs[0]
        for edge in snapshot.edges
        if any(ref.statement_id == "c-route-port" for ref in edge.statement_refs)
    )
    updated_port = port.model_copy(
        update={
            "statement_refs": [b_ref],
            "provenance": port.provenance.model_copy(
                update={
                    "source_refs": [*port.provenance.source_refs, c_ref.aggregate_ref]
                }
            ),
        }
    )
    unsafe_snapshot = snapshot.model_copy(
        update={
            "nodes": [updated_port if node.node_id == port.node_id else node for node in snapshot.nodes]
        }
    )
    query = _scoped_query(
        unsafe_snapshot,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=1,
    )

    result = query_graph(
        query,
        snapshots={(unsafe_snapshot.graph_id, unsafe_snapshot.revision): unsafe_snapshot},
        current_slices=unsafe_snapshot.manifest.input_slices,
    )

    returned_port = next(
        node for node in result.subgraph.snapshot.nodes if node.node_id == "node-port-vega"
    )
    assert c_ref.aggregate_ref in returned_port.provenance.source_refs
    assert result.subgraph.freshness == "unknown"
    assert any(item.partition_id == "company-c" for item in result.subgraph.missing_slices)


def test_non_materialized_source_and_evidence_refs_remain_provenance_without_hidden_owner_reads():
    store, _request, _output, snapshot = _published_graph()
    port = next(node for node in snapshot.nodes if node.node_id == "node-port-vega")
    materialized_port = next(
        node for node in graph_query_snapshot().nodes if node.node_id == "node-port-vega"
    )
    # The projection manifest identifies graph-building KnowledgeSlices.
    # These document/evidence refs are retained source pointers, not extra
    # graph-query owner reads or implicit required slices.
    b_ref = next(ref for ref in port.statement_refs if ref.statement_id == "b-route-vega")
    updated_port = port.model_copy(
        update={"statement_refs": [b_ref], "provenance": materialized_port.provenance}
    )
    scoped_snapshot = snapshot.model_copy(
        update={
            "nodes": [updated_port if node.node_id == port.node_id else node for node in snapshot.nodes]
        }
    )
    changed_c = [
        item.model_copy(update={"revision": item.revision + 1})
        if item.partition_id == "company-c"
        else item
        for item in snapshot.manifest.input_slices
    ]
    query = _scoped_query(
        scoped_snapshot,
        "company-b",
        seed_ids=["node-company-b"],
        max_depth=1,
    )

    result = query_graph(
        query,
        snapshots={(scoped_snapshot.graph_id, scoped_snapshot.revision): scoped_snapshot},
        current_slices=changed_c,
    )

    returned_port = next(
        node for node in result.subgraph.snapshot.nodes if node.node_id == "node-port-vega"
    )
    assert returned_port.provenance == materialized_port.provenance
    assert {str(ref.owner) for ref in returned_port.provenance.source_refs} == {"Documents"}
    assert {str(ref.owner) for ref in returned_port.provenance.evidence_refs} == {"Evidence"}
    assert result.subgraph.freshness == "current"


def test_unknown_freshness_historical_exact_cut_and_missing_graph():
    store, _request, _output, snapshot = _published_graph()
    unknown = query_graph(
        _query(snapshot, policy="allow_stale"), snapshots=store.snapshots(), current_slices=None
    )
    assert unknown.subgraph.freshness == "unknown"
    assert len(unknown.subgraph.missing_slices) == len(snapshot.manifest.input_slices)
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            _query(snapshot, policy="current_required"), snapshots=store.snapshots(), current_slices=None
        )
    assert exc.value.code == "VERSION_CONFLICT"

    historical = query_graph(
        _query(snapshot, policy="historical"), snapshots=store.snapshots(), current_slices=None
    )
    assert historical.subgraph.freshness == "historical"
    mismatched_cut = TimeSlice(
        known_as_of=snapshot.manifest.as_of.known_as_of,
        valid_as_of="2025-06-01T00:00:00Z",
    )
    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            _query(snapshot, policy="historical", as_of=mismatched_cut),
            snapshots=store.snapshots(),
            current_slices=None,
        )
    assert exc.value.code == "VERSION_CONFLICT"

    missing = query_graph(
        _query(snapshot), snapshots={}, current_slices=snapshot.manifest.input_slices
    )
    assert missing.subgraph is None


def test_graph_build_exchange_matches_pinned_operation_contract():
    _registry, operations = load_operation_registry()
    operation = _example("Graph.build")
    request, refs, aggregate_refs = build_shared_request()
    built = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    ).output
    operation["request"]["payload"] = request.model_dump(mode="json")
    operation["response"]["payload"] = built.model_dump(mode="json")
    request_wire = json.dumps(operation["request"], ensure_ascii=False, separators=(",", ":"))
    response_wire = json.dumps(operation["response"], ensure_ascii=False, separators=(",", ":"))
    parsed_request, parsed_response = validate_operation_exchange(
        operations["Graph.build"], request_wire, response_wire
    )
    assert parsed_request.payload.graph_id == built.candidate.graph_id
    assert parsed_response.payload.candidate == built.candidate


def test_current_required_needs_exact_required_and_current_slices_for_full_graph():
    store, _request, _output, snapshot = _published_graph()
    full_query = _query(snapshot, policy="current_required")
    missing_requirements = QueryGraphInput(
        query=full_query.query.model_copy(update={"required_slices": []})
    )

    with pytest.raises(GraphQueryError) as exc:
        query_graph(
            missing_requirements,
            snapshots=store.snapshots(),
            current_slices=[],
        )
    assert exc.value.code == "VERSION_CONFLICT"

    missing_current = query_graph(
        _query(snapshot, policy="allow_stale"),
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices[:-1],
    )
    assert missing_current.subgraph.freshness == "unknown"
    assert missing_current.subgraph.missing_slices

    current = query_graph(
        full_query,
        snapshots=store.snapshots(),
        current_slices=snapshot.manifest.input_slices,
    )
    assert current.subgraph.freshness == "current"


def test_disproved_relationship_is_neither_projected_nor_traversed():
    request, refs, aggregate_refs = build_shared_request()
    statement = next(
        item for item in request.knowledge.statements
        if item.statement_id == "b-buys-microkaskad"
    )
    wire = statement.model_dump(mode="json")
    wire["epistemic_status"] = "disproved"
    disproved = Statement.model_validate_json(
        json.dumps(wire, ensure_ascii=False, separators=(",", ":")), strict=True
    )
    knowledge = request.knowledge.model_copy(update={
        "statements": [
            disproved if item.statement_id == statement.statement_id else item
            for item in request.knowledge.statements
        ]
    })
    request = request.model_copy(update={"knowledge": knowledge})
    refs = dict(refs)
    refs[(statement.statement_id, statement.revision)] = refs[
        (statement.statement_id, statement.revision)
    ].model_copy(update={"hash": canonical_statement_hash(disproved)})

    artifacts = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    assert not any(
        ref.statement_id == statement.statement_id
        for edge in artifacts.output.candidate.edges
        for ref in edge.statement_refs
    )
    assert any(
        item.statement.statement_id == statement.statement_id
        and item.reason == "disproved_not_projected"
        for item in artifacts.preserved_statements
    )

    baseline_request, baseline_refs, baseline_aggregates = build_shared_request()
    baseline = build_graph(
        baseline_request,
        statement_ref_index=baseline_refs,
        aggregate_refs=baseline_aggregates,
        rules=default_graph_rules(baseline_request.ontology),
    ).output.candidate.model_copy(update={"revision": 1})
    target_edge = next(
        edge for edge in baseline.edges
        if edge.statement_refs
        and edge.statement_refs[0].statement_id == statement.statement_id
    )
    unsafe_snapshot = baseline.model_copy(update={
        "edges": [
            edge.model_copy(update={"epistemic_status": "disproved"})
            if edge.edge_id == target_edge.edge_id else edge
            for edge in baseline.edges
        ]
    })
    result = query_graph(
        _query(unsafe_snapshot, seed_ids=["node-company-b"], max_depth=1),
        snapshots={(unsafe_snapshot.graph_id, 1): unsafe_snapshot},
        current_slices=unsafe_snapshot.manifest.input_slices,
    )
    result_node_ids = {node.node_id for node in result.subgraph.snapshot.nodes}
    result_edge_ids = {edge.edge_id for edge in result.subgraph.snapshot.edges}
    assert "node-supplier-b-x" not in result_node_ids
    assert target_edge.edge_id not in result_edge_ids
