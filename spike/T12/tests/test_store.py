from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from alfalab_contracts.models import Graph_publishRequest, QueryGraphInput, ReceiptQuery
from alfalab_contracts.registry import load_operation_registry, validate_operation_exchange

from t12_graph_spike import (
    GraphBuildError,
    GraphQueryError,
    IdempotencyConflict,
    IsolatedGraphStore,
    RevisionConflict,
    SourceReferenceMismatch,
    build_graph,
    canonical_hash,
    default_graph_rules,
    query_graph,
)
from helpers import build_shared_request


ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "docs/specs/framework-v1/contracts/examples.json"


def _example(operation_id: str) -> dict:
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))["examples"]
    return deepcopy(next(row for row in examples if row["operation_id"] == operation_id))


def _build_candidate():
    request, refs, aggregate_refs = build_shared_request()
    before = [item.model_dump(mode="json") for item in request.knowledge.statements]
    candidate = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    ).output.candidate
    return request, before, candidate, refs


def _publish_request(candidate, *, key="publish-key-1", expected_revision=0):
    example = _example("Graph.publish")
    example["request"]["payload"] = {
        "candidate": candidate.model_dump(mode="json"),
        "expected_revision": expected_revision,
    }
    example["request"]["idempotency_key"] = key
    return Graph_publishRequest.model_validate_json(
        json.dumps(example["request"], ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )


def test_publish_isolated_revision_receipt_idempotency_and_source_immutability():
    request, before, candidate, refs = _build_candidate()
    store = IsolatedGraphStore()
    publish_request = _publish_request(candidate)
    first = store.publish(publish_request, source_statement_refs=refs)
    repeated = store.publish(publish_request, source_statement_refs=refs)
    receipt_recovery = store.publish(publish_request, source_statement_refs=None)
    assert first == repeated
    assert receipt_recovery == first
    assert first.projection_ref.object_id == candidate.graph_id
    assert first.projection_ref.revision == 1
    assert first.receipt.applied is True
    assert first.receipt.changed_refs == [first.projection_ref]
    assert store.snapshot(candidate.graph_id, 0) is None
    published = store.snapshot(candidate.graph_id, 1)
    assert published is not None
    assert published.edges == candidate.edges
    assert [item.model_dump(mode="json") for item in request.knowledge.statements] == before


def test_publish_rejects_revision_and_idempotency_conflicts_without_mutation():
    _request, _before, candidate, refs = _build_candidate()
    store = IsolatedGraphStore()
    original = _publish_request(candidate)
    first = store.publish(original, source_statement_refs=refs)
    changed = candidate.model_copy(update={"graph_id": "graph-different-command"})
    with pytest.raises(IdempotencyConflict):
        store.publish(_publish_request(changed, key=original.idempotency_key), source_statement_refs=refs)
    with pytest.raises(RevisionConflict):
        store.publish(_publish_request(candidate, key="publish-key-2", expected_revision=0), source_statement_refs=refs)
    assert store.snapshot(candidate.graph_id, 1) is not None
    assert store.snapshot("graph-different-command", 1) is None
    assert store.receipts()[("Graph.publish", original.idempotency_key)] == first.receipt


def test_publish_rejects_invalid_candidate_and_uses_no_persistent_storage():
    _request, _before, candidate, refs = _build_candidate()
    broken = candidate.model_copy(update={"revision": 1})
    store = IsolatedGraphStore()
    with pytest.raises(ValueError, match="revision-zero"):
        store.publish(_publish_request(broken), source_statement_refs=refs)
    assert store.snapshots() == {}
    assert store.receipts() == {}


def test_publish_requires_explicit_exact_source_reference_materialization():
    _request, _before, candidate, refs = _build_candidate()
    store = IsolatedGraphStore()
    publish_request = _publish_request(candidate)
    with pytest.raises(SourceReferenceMismatch, match="explicitly materialized"):
        store.publish(publish_request, source_statement_refs=None)
    with pytest.raises(SourceReferenceMismatch, match="absent from or different"):
        store.publish(publish_request, source_statement_refs={})

    one_key = next(iter(refs))
    tampered = dict(refs)
    tampered[one_key] = refs[one_key].model_copy(update={"hash": "sha256:" + "0" * 64})
    with pytest.raises(SourceReferenceMismatch, match="absent from or different"):
        store.publish(publish_request, source_statement_refs=tampered)
    assert store.snapshots() == {}


def test_receipt_query_returns_only_supplied_isolated_receipt():
    _request, _before, candidate, refs = _build_candidate()
    store = IsolatedGraphStore()
    published = store.publish(_publish_request(candidate), source_statement_refs=refs)
    receipt_query = QueryGraphInput.model_validate_json(
        json.dumps(
            {
                "query": {
                    "kind": "receipt",
                    "operation_id": "Graph.publish",
                    "idempotency_key": "publish-key-1",
                }
            },
            separators=(",", ":"),
        ),
        strict=True,
    )
    receipt = query_graph(
        receipt_query,
        snapshots=store.snapshots(),
        current_slices=None,
        receipts=store.receipts(),
    )
    assert receipt.kind == "receipt"
    assert receipt.receipt == published.receipt
    not_found_query = QueryGraphInput.model_validate_json(
        json.dumps(
            {
                "query": {
                    "kind": "receipt",
                    "operation_id": "Graph.publish",
                    "idempotency_key": "missing-key",
                }
            },
            separators=(",", ":"),
        ),
        strict=True,
    )
    not_found = query_graph(not_found_query, snapshots={}, current_slices=None, receipts={})
    assert not_found.kind == "receipt"
    assert not_found.receipt is None


def test_publish_and_query_exchanges_match_pinned_operation_contracts():
    _registry, operations = load_operation_registry()
    _request, _before, candidate, refs = _build_candidate()
    store = IsolatedGraphStore()
    publish_request = _publish_request(candidate)
    publish_example = _example("Graph.publish")
    publish_example["request"] = json.loads(publish_request.model_dump_json())
    output = store.publish(publish_request, source_statement_refs=refs)
    publish_example["response"]["payload"] = output.model_dump(mode="json")
    parsed_request, parsed_response = validate_operation_exchange(
        operations["Graph.publish"],
        json.dumps(publish_example["request"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(publish_example["response"], ensure_ascii=False, separators=(",", ":")),
    )
    assert parsed_request.payload.expected_revision == 0
    assert parsed_response.payload.projection_ref == output.projection_ref

    example = _example("Graph.query")
    query_payload = {
        "query": {
            "kind": "subgraph",
            "graph_id": candidate.graph_id,
            "revision": 1,
            "seed_ids": ["node-company-b"],
            "relations": [],
            "max_depth": 2,
            "max_nodes": 50,
            "required_slices": [item.model_dump(mode="json") for item in candidate.manifest.input_slices],
            "freshness_policy": "current_required",
            "as_of": candidate.manifest.as_of.model_dump(mode="json"),
        }
    }
    example["request"]["payload"] = query_payload
    query_request = QueryGraphInput.model_validate_json(
        json.dumps(query_payload, ensure_ascii=False, separators=(",", ":")), strict=True
    )
    query_output = query_graph(
        query_request,
        snapshots=store.snapshots(),
        current_slices=candidate.manifest.input_slices,
        receipts=store.receipts(),
    )
    example["response"]["payload"] = query_output.model_dump(mode="json")
    parsed_query, parsed_result = validate_operation_exchange(
        operations["Graph.query"],
        json.dumps(example["request"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(example["response"], ensure_ascii=False, separators=(",", ":")),
    )
    assert parsed_query.payload.query.graph_id == candidate.graph_id
    assert parsed_result.payload.subgraph.snapshot.graph_id == candidate.graph_id


def test_publish_rejects_grounded_references_without_manifest_slices():
    _request, _before, candidate, refs = _build_candidate()
    missing_all = candidate.model_copy(update={
        "manifest": candidate.manifest.model_copy(update={"input_slices": []})
    })
    store = IsolatedGraphStore()
    with pytest.raises(SourceReferenceMismatch, match="manifest"):
        store.publish(_publish_request(missing_all), source_statement_refs=refs)
    assert store.snapshots() == {}

    missing_one = candidate.model_copy(update={
        "manifest": candidate.manifest.model_copy(
            update={"input_slices": candidate.manifest.input_slices[:-1]}
        )
    })
    with pytest.raises(SourceReferenceMismatch, match="manifest"):
        store.publish(_publish_request(missing_one, key="publish-key-partial"), source_statement_refs=refs)
    assert store.snapshots() == {}


def test_published_revision_and_receipt_readbacks_are_detached():
    _request, _before, candidate, refs = _build_candidate()
    store = IsolatedGraphStore()
    publish_request = _publish_request(candidate, key="immutable-readback")
    first = store.publish(publish_request, source_statement_refs=refs)
    expected_hash = first.projection_ref.hash
    original_name = store.snapshot(candidate.graph_id, 1).nodes[0].entity.display_name

    readback = store.snapshot(candidate.graph_id, 1)
    readback.nodes[0].entity.display_name = "REVIEW-MUTATED"
    assert store.snapshot(candidate.graph_id, 1).nodes[0].entity.display_name == original_name
    assert canonical_hash(store.snapshot(candidate.graph_id, 1)) == expected_hash

    mapping_readback = store.snapshots()[(candidate.graph_id, 1)]
    mapping_readback.nodes[0].entity.display_name = "MAPPING-MUTATED"
    assert store.snapshot(candidate.graph_id, 1).nodes[0].entity.display_name == original_name

    first.receipt.changed_refs[0].object_id = "tampered-graph"
    retry = store.publish(publish_request, source_statement_refs=None)
    assert retry.projection_ref.object_id == candidate.graph_id
    assert retry.projection_ref.hash == expected_hash
    assert retry.receipt.changed_refs[0].object_id == candidate.graph_id
    assert store.receipts()[("Graph.publish", publish_request.idempotency_key)].changed_refs[0].object_id == candidate.graph_id
