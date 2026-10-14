from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
T13 = ROOT / "spike" / "T13"
CONTRACT_SRC = ROOT / "packages" / "contracts" / "src"
for path in (str(CONTRACT_SRC), str(T13)):
    if path not in sys.path:
        sys.path.insert(0, path)

from alfalab_contracts.models import (  # noqa: E402
    EvidenceRecord,
    GraphSubgraph,
    ObjectRef,
    RecommendationInput,
    TimeSlice,
    EventRecord,
    BusinessSnapshot,
)
from alfalab_contracts._generated import Audience, Freshness
from impact.approach_c import assess_c, controlled_model_response, validate_controlled_response  # noqa: E402
from impact.approach_d import assess_d  # noqa: E402
from impact.common import ImpactContext, calculate_explicit_gross_exposure, follow_edge_path, object_key  # noqa: E402
from matching.core import EventContext, match_context  # noqa: E402
from recommendations.propose import default_information_actions, propose  # noqa: E402

SHARED = ROOT / "spike" / "_shared"
DATASET = SHARED / "datasets" / "t09-t13-independent-v1"
SHARED_FIXTURES = SHARED / "fixtures" / "t09-t13-independent-v1"
LOCAL_MATRIX = T13 / "fixtures" / "scenario_matrix.json"
OUTPUT = T13 / "results" / "approach-comparison.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_scenario_matrix(matrix: dict[str, Any], data: dict[str, Any]) -> None:
    expected_data_hash = canonical_hash(data)
    if matrix.get("dataset_ref", {}).get("canonical_sha256") != expected_data_hash:
        raise ValueError("T13 scenario matrix does not match the frozen shared dataset hash")
    if matrix.get("scenario_count") != len(matrix.get("scenarios", [])) or matrix["scenario_count"] != len(data["t13_impact_cases"]):
        raise ValueError("T13 scenario count differs from the frozen shared cases")
    unsigned_matrix = dict(matrix)
    declared_fixture_hash = unsigned_matrix.pop("fixture_sha256", None)
    if declared_fixture_hash != canonical_hash(unsigned_matrix):
        raise ValueError("T13 scenario matrix fixture hash mismatch")
    for scenario in matrix["scenarios"]:
        unsigned_case = dict(scenario)
        declared_case_hash = unsigned_case.pop("fixture_sha256", None)
        if declared_case_hash != canonical_hash(unsigned_case):
            raise ValueError(f"T13 scenario fixture hash mismatch: {scenario.get('case_id')}")


def hash_ref(owner: str, object_id: str, revision: int = 1) -> ObjectRef:
    digest = hashlib.sha256(f"t13:{owner}:{object_id}:{revision}".encode("utf-8")).hexdigest()
    return ObjectRef(owner=owner, object_id=object_id, revision=revision, hash=f"sha256:{digest}")


def load_materialized_inputs() -> tuple[dict[str, Any], dict[str, BusinessSnapshot], GraphSubgraph, dict[str, EvidenceRecord], dict[str, EventRecord]]:
    data = load_json(DATASET / "data.json")
    profiles = {
        item["company_id"]: BusinessSnapshot.model_validate(item["snapshots"][-1])
        for item in data["company_profiles"]
    }
    graph_fixture = load_json(SHARED_FIXTURES / "graph-query.json")
    graph = GraphSubgraph.model_validate(graph_fixture["response"]["payload"]["subgraph"])
    evidence_fixture = load_json(SHARED_FIXTURES / "evidence-read.json")
    evidence = {
        row["ref"]["object_id"]: EvidenceRecord.model_validate(row)
        for row in evidence_fixture["response"]["payload"]["records"]
    }
    event_fixture = load_json(SHARED_FIXTURES / "events-read.json")
    events = {
        row["ref"]["object_id"]: EventRecord.model_validate(row)
        for row in event_fixture["response"]["payload"]["snapshot"]["events"]
    }
    return data, profiles, graph, evidence, events


def make_context(row: dict[str, Any], materialized: tuple[dict[str, Any], dict[str, BusinessSnapshot], GraphSubgraph, dict[str, EvidenceRecord], dict[str, EventRecord]]) -> ImpactContext:
    data, profiles, base_graph, evidence_by_id, events = materialized
    profile = profiles[row["company_id"]]
    graph = base_graph
    if row["graph_freshness"] != "current":
        graph = base_graph.model_copy(update={"freshness": Freshness(row["graph_freshness"])})
    event_record = events.get(row["event_id"])
    if event_record:
        event_ref = event_record.ref
    else:
        event_ref = hash_ref("Events", row["event_id"])
    event_evidence = tuple(
        evidence_by_id[evidence_id].ref
        for evidence_id in row["event_evidence_ids"]
        if evidence_id in evidence_by_id
    )
    event = EventContext(
        event_ref=event_ref,
        event_type=row["event_type"],
        target_entity_ids=tuple(sorted(set(row["target_entity_ids"]))),
        evidence_refs=event_evidence,
        factual_status=row["factual_status"],
        current=row["current"],
        sector_only=row["sector_only"],
    )
    result = match_context(event, graph, [profile], "balanced", limit=20)
    matches = [match for match in result.matches if match.company.entity_id == row["company_id"]]
    if not matches:
        raise RuntimeError(f"matching produced no scoped result for {row['case_id']}")
    numeric = data["controlled_numeric_scenario"] if row["numeric_scenario_id"] else None
    return ImpactContext(
        event=event,
        profile=profile,
        match=matches[0],
        graph=graph,
        evidence=tuple(evidence_by_id.values()),
        as_of=TimeSlice.model_validate(data["as_of"]),
        scenario_id=row["case_id"],
        numeric_inputs=numeric,
    )


def summarize(result: Any, graph_paths_used: int) -> dict[str, Any]:
    assessment = result.assessment
    return {
        "exposure": assessment.exposure.value,
        "likelihood": assessment.likelihood.value,
        "direction": assessment.direction.value,
        "materiality": assessment.materiality.value,
        "confidence": assessment.confidence.level.value,
        "mechanisms": [item.code for item in assessment.mechanisms],
        "graph_paths_used": graph_paths_used,
        "validated_claim_count": result.accepted_claim_count,
        "evidence_refs": [item.object_id for item in assessment.evidence_refs],
        "financial_quantity": [scenario.quantity.value if scenario.quantity else None for scenario in assessment.scenarios],
        "trace": list(result.trace),
    }


def run() -> dict[str, Any]:
    matrix = load_json(LOCAL_MATRIX)
    materialized = load_materialized_inputs()
    data = materialized[0]
    validate_scenario_matrix(matrix, data)
    rows = []
    safety = {
        "scenario_count": 0,
        "c_supported_claims_without_graph_path": 0,
        "c_claims_with_unavailable_evidence": 0,
        "c_unsupported_quantities_accepted": 0,
        "d_mechanisms_without_graph_path": 0,
        "d_sector_only_positive_mechanisms": 0,
        "non_null_contract_financial_quantities": 0,
        "recommendations_outside_safe_local_catalog": 0,
    }
    for row in matrix["scenarios"]:
        context = make_context(row, materialized)
        c_response = controlled_model_response(context)
        c_claims = validate_controlled_response(context, c_response)
        c_result = assess_c(context, c_response)
        d_result = assess_d(context)
        recommendation_request = RecommendationInput(
            assessment=d_result.assessment,
            audience=Audience.bank_manager,
            allowed_actions=default_information_actions(),
            constraints=["Informational only; do not execute banking or external-notification actions."],
        )
        recommendations = propose(recommendation_request)
        if row["numeric_scenario_id"]:
            numeric_quantity, numeric_unit = calculate_explicit_gross_exposure(data["controlled_numeric_scenario"])
        else:
            numeric_quantity, numeric_unit = None, None
        safety["scenario_count"] += 1
        if row["sector_only"] and (c_result.assessment.mechanisms or d_result.assessment.mechanisms):
            safety["d_sector_only_positive_mechanisms"] += 1
        edge_by_id = {edge.edge_id: edge for edge in context.graph.snapshot.edges}
        for claim in c_claims:
            resolved = follow_edge_path(context.graph, context.company_id, claim.edge_path)
            if not resolved or resolved[-1] != claim.target_entity_id:
                safety["c_supported_claims_without_graph_path"] += 1
            if any(object_key(ref) not in context.evidence_by_ref for ref in claim.evidence_refs):
                safety["c_claims_with_unavailable_evidence"] += 1
            if claim.quantity is not None and not context.numeric_inputs:
                safety["c_unsupported_quantities_accepted"] += 1
        d_valid_paths = []
        for path in context.match.edge_paths:
            resolved = follow_edge_path(context.graph, context.company_id, path)
            if not resolved or resolved[-1] not in set(context.event.target_entity_ids):
                continue
            if all(edge_id in edge_by_id and edge_by_id[edge_id].epistemic_status.value == "confirmed" for edge_id in path):
                d_valid_paths.append(path)
        if d_result.assessment.mechanisms and not d_valid_paths:
            safety["d_mechanisms_without_graph_path"] += 1
        if any(scenario.quantity is not None for scenario in c_result.assessment.scenarios + d_result.assessment.scenarios):
            safety["non_null_contract_financial_quantities"] += 1
        safe_codes = {"ask_supplier_geography", "check_inventory", "verify_alternative_route", "request_supporting_document", "review_with_analyst"}
        if any(rec.action_type.code not in safe_codes for rec in recommendations.recommendations):
            safety["recommendations_outside_safe_local_catalog"] += 1
        rows.append({
            "case_id": row["case_id"],
            "company_id": row["company_id"],
            "event_id": row["event_id"],
            "same_inputs": True,
            "provisional_expectations": row["provisional_expectations"],
            "approach_c": summarize(c_result, len(c_claims)),
            "approach_d": summarize(d_result, len(d_valid_paths) if d_result.assessment.mechanisms else 0),
            "recommendations": [
                {"action": rec.action_type.code, "requires_approval": rec.requires_approval, "evidence_refs": [ref.object_id for ref in rec.evidence_refs]}
                for rec in recommendations.recommendations
            ],
            "auxiliary_numeric_scenario": None if numeric_quantity is None else {
                "quantity": numeric_quantity,
                "unit": numeric_unit,
                "interpretation": "gross procurement exposure only; not a loss estimate; operation DTO quantity remains null",
            },
        })
    output = {
        "schema": "alfalab.spike.t13.approach-comparison/v1",
        "dataset_ref": matrix["dataset_ref"],
        "status": "provisional_offline_harness",
        "live_model_quality": "NOT MEASURED",
        "cost": "NOT MEASURED",
        "latency": "NOT MEASURED (local deterministic execution only)",
        "interpretation": "Counts test the validators and deterministic rules against synthetic provisional cases. Approach C uses model-shaped controlled fixtures, not LLM inference; this is not comparative model quality.",
        "safety_metrics": safety,
        "cases": rows,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return output

if __name__ == "__main__":
    report = run()
    print(f"scenarios={report['safety_metrics']['scenario_count']} output={OUTPUT.relative_to(ROOT)}")
    print(json.dumps(report["safety_metrics"], sort_keys=True))
