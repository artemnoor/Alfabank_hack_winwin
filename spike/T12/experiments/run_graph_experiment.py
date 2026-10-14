"""Run the fixed offline T12 cases and write a reproducible summary artifact."""

from __future__ import annotations

import json
from pathlib import Path

from alfalab_contracts.models import BuildGraphInput, StatementRef, TimeSlice

from helpers import build_shared_request, build_t12_input, shared_data
from t12_graph_spike import (
    build_graph,
    canonical_statement_hash,
    default_graph_rules,
)


ROOT = Path(__file__).resolve().parents[3]
RESULT_PATH = ROOT / "spike/T12/results/experiment-v1.0.1.json"


def summarize_input(input_id: str, *, include_candidate_as_of: bool = False) -> dict:
    request, refs, aggregate_refs, _fixture = build_t12_input(
        input_id,
        include_candidate_as_of=include_candidate_as_of,
    )
    artifacts = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    candidate = artifacts.output.candidate
    return {
        "input_id": input_id,
        "graph_id": candidate.graph_id,
        "node_count": len(candidate.nodes),
        "edge_count": len(candidate.edges),
        "edges": [
            {
                "edge_id": edge.edge_id,
                "source_node_id": edge.source_node_id,
                "target_node_id": edge.target_node_id,
                "relation": edge.relation.code,
                "epistemic_status": edge.epistemic_status.value,
                "statement_refs": [ref.statement_id for ref in edge.statement_refs],
                "input_statement_refs": [
                    ref.statement_id for ref in edge.provenance.input_statement_refs
                ],
                "method": (
                    edge.provenance.derivation_method.id
                    if edge.provenance.derivation_method
                    else None
                ),
            }
            for edge in candidate.edges
        ],
        "missing_data": [item.model_dump(mode="json") for item in candidate.missing_data],
        "preserved_statements": [
            {
                "statement_id": item.statement.statement_id,
                "reason": item.reason,
                "has_exact_statement_ref": item.statement_ref is not None,
            }
            for item in artifacts.preserved_statements
        ],
        "temporal_edge_contexts": [
            {
                "edge_id": item.edge_id,
                "statement_id": item.statement_id,
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "recorded_at": item.recorded_at,
            }
            for item in artifacts.temporal_edge_contexts
        ],
    }


def historical_company_c() -> dict:
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
    knowledge = request.knowledge.model_copy(
        update={
            "as_of": TimeSlice(
                known_as_of="2026-10-14T00:00:00Z",
                valid_as_of="2025-06-01T00:00:00Z",
            )
        }
    )
    historical_request = BuildGraphInput(
        graph_id="graph-company-c-historical",
        knowledge=knowledge,
        ontology=request.ontology,
        rules=request.rules,
    )
    artifacts = build_graph(
        historical_request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    return {
        "graph_id": artifacts.output.candidate.graph_id,
        "valid_as_of": artifacts.output.candidate.manifest.as_of.valid_as_of,
        "edge_ids": [edge.edge_id for edge in artifacts.output.candidate.edges],
        "temporal_contexts": [
            {
                "edge_id": item.edge_id,
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
            }
            for item in artifacts.temporal_edge_contexts
        ],
    }


def main() -> None:
    manifest, _data = shared_data()
    request, refs, aggregate_refs = build_shared_request()
    current_artifacts = build_graph(
        request,
        statement_ref_index=refs,
        aggregate_refs=aggregate_refs,
        rules=default_graph_rules(request.ontology),
    )
    payload = {
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["version"],
        "dataset_status": manifest["status"],
        "dataset_hash": manifest["data_hash"],
        "quality": "PRELIMINARY",
        "live_model_quality": "NOT MEASURED",
        "current_projection": {
            "graph_id": current_artifacts.output.candidate.graph_id,
            "revision": current_artifacts.output.candidate.revision,
            "node_count": len(current_artifacts.output.candidate.nodes),
            "edge_count": len(current_artifacts.output.candidate.edges),
            "edge_ids": [edge.edge_id for edge in current_artifacts.output.candidate.edges],
            "missing_data": [
                item.model_dump(mode="json")
                for item in current_artifacts.output.candidate.missing_data
            ],
        },
        "independent_inputs": [
            summarize_input("hypothetical-only"),
            summarize_input("explicit-negative-country-x"),
            summarize_input("inferred-company-country-x", include_candidate_as_of=True),
        ],
        "historical_case": historical_company_c(),
        "interpretation": [
            "The shared corpus is synthetic, provisional and not an approved gold dataset.",
            "No external data, service, embedding, or live model was used.",
            "Missing edges represent unknown state; this summary does not infer negative dependency.",
        ],
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {RESULT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
