from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from alfalab_contracts.models import (
    BuildGraphInput,
    BusinessSnapshot,
    EntityRef,
    EntityValue,
    EvidenceRecord,
    GraphSnapshot,
    KnowledgeSnapshot,
    ObjectRef,
    Statement,
    StatementRef,
    VersionedRef,
)

from t12_graph_spike import canonical_hash, default_graph_rules

ROOT = Path(__file__).resolve().parents[3]
SHARED_BASE = ROOT / "spike/_shared"
DATASET_PATH = SHARED_BASE / "datasets/t09-t13-independent-v1"
FIXTURE_PATH = SHARED_BASE / "fixtures/t09-t13-independent-v1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_json(model: Any, value: Any) -> Any:
    wire = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return model.model_validate_json(wire, strict=True)


def shared_data() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = read_json(DATASET_PATH / "manifest.json")
    data_bytes = (DATASET_PATH / "data.json").read_bytes()
    if manifest["version"] != "1.0.1":
        raise AssertionError("T12 fixture loader is pinned to shared dataset v1.0.1")
    if manifest["status"] != "provisional_not_gold_not_approved":
        raise AssertionError("shared synthetic fixture status changed unexpectedly")
    file_hash = "sha256:" + hashlib.sha256(data_bytes).hexdigest()
    if file_hash != manifest["files"]["data.json"]["file_sha256"]:
        raise AssertionError("shared data.json physical hash does not match v1.0.1 manifest")
    data = json.loads(data_bytes.decode("utf-8"))
    if canonical_hash(data) != manifest["data_hash"] or data["version"] != "1.0.1":
        raise AssertionError("shared dataset canonical hash/version does not match manifest")
    return manifest, data


def graph_query_snapshot() -> GraphSnapshot:
    fixture = read_json(FIXTURE_PATH / "graph-query.json")
    return validate_json(GraphSnapshot, fixture["response"]["payload"]["subgraph"]["snapshot"])


def statement_refs_from_snapshot(snapshot: GraphSnapshot) -> dict[tuple[str, int], StatementRef]:
    result: dict[tuple[str, int], StatementRef] = {}
    for item in [*snapshot.nodes, *snapshot.edges]:
        for ref in item.statement_refs:
            key = (ref.statement_id, ref.revision)
            prior = result.get(key)
            if prior is not None and prior != ref:
                raise AssertionError(f"fixture has conflicting exact StatementRefs for {key}")
            result[key] = ref
    return result


def evidence_records(data: dict[str, Any], statements: list[Statement]) -> list[EvidenceRecord]:
    refs = {
        ref.object_id: ref
        for statement in statements
        for ref in statement.provenance.evidence_refs
    }
    rows = {row["ref"]["object_id"]: row for row in data["evidence_catalog"]}
    result = []
    for object_id, ref in sorted(refs.items()):
        row = rows[object_id]
        payload = {
            key: row[key]
            for key in (
                "ref",
                "source_ref",
                "locator",
                "source_hash",
                "verification",
                "source_reliability",
                "reliability_method",
            )
        }
        if payload["ref"] != ref.model_dump(mode="json"):
            raise AssertionError(f"evidence ref {object_id} differs from shared EvidenceRecord")
        result.append(validate_json(EvidenceRecord, payload))
    return result


def latest_snapshots(data: dict[str, Any]) -> list[dict[str, Any]]:
    selected = []
    for profile in data["company_profiles"]:
        selected.append(max(profile["snapshots"], key=lambda row: row["ref"]["revision"]))
    return selected


def _known_entities(data: dict[str, Any], statements: list[Statement]) -> list[EntityRef]:
    known = {row["entity_id"]: row for row in data["entities"]}
    used: set[str] = set()
    for statement in statements:
        used.add(statement.subject.entity_id)
        if isinstance(statement.value, EntityValue):
            used.add(statement.value.value.entity_id)
        elif statement.value.kind == "entity":
            used.add(statement.value.value.entity_id)
    return [EntityRef.model_validate(known[key], strict=True) for key in sorted(used)]


def build_shared_request() -> tuple[BuildGraphInput, dict[tuple[str, int], StatementRef], list[ObjectRef]]:
    _manifest, data = shared_data()
    snapshots = latest_snapshots(data)
    statements = [validate_json(Statement, item) for snap in snapshots for item in snap["statements"]]
    slices = [snap["slice"] for snap in snapshots]
    snapshot_ref_values = [snap["ref"] for snap in snapshots]
    aggregate_refs = [validate_json(ObjectRef, item) for item in snapshot_ref_values]
    graph_snapshot = graph_query_snapshot()
    all_statement_refs = statement_refs_from_snapshot(graph_snapshot)
    keys = {(statement.statement_id, statement.revision) for statement in statements}
    statement_ref_index = {key: ref for key, ref in all_statement_refs.items() if key in keys}
    entities = _known_entities(data, statements)
    knowledge = KnowledgeSnapshot(
        statements=statements,
        entities=entities,
        slices=slices,
        evidence=evidence_records(data, statements),
        as_of=data["as_of"],
    )
    ontology = graph_snapshot.manifest.ontology
    rules = default_graph_rules(ontology)
    request = BuildGraphInput(
        graph_id=graph_snapshot.graph_id,
        knowledge=knowledge,
        ontology=ontology,
        rules=rules.ref,
    )
    return request, statement_ref_index, aggregate_refs


def build_t12_input(
    input_id: str,
    *,
    include_candidate_as_of: bool = False,
) -> tuple[BuildGraphInput, dict[tuple[str, int], StatementRef], list[ObjectRef], dict[str, Any]]:
    _manifest, data = shared_data()
    row = next(item for item in data["t12_graph_inputs"] if item["input_id"] == input_id)
    snapshot = validate_json(BusinessSnapshot, row["payload"]["aggregate_snapshot"])
    statements_by_key = {
        (item.statement_id, item.revision): item for item in snapshot.statements
    }
    candidate = validate_json(Statement, row["payload"]["candidate_statement"])
    statements_by_key[(candidate.statement_id, candidate.revision)] = candidate
    statements = list(statements_by_key.values())
    refs: dict[tuple[str, int], StatementRef] = {}
    for source in row["inputs"]:
        if source["kind"] == "StatementRef":
            ref = validate_json(StatementRef, source["ref"])
            refs[(ref.statement_id, ref.revision)] = ref
    # The candidate may already be an immutable statement in the supplied
    # BusinessSnapshot (hypothetical/negative cases); only explicit refs count.
    entities = _known_entities(data, statements)
    knowledge_as_of = snapshot.as_of.model_dump(mode="json")
    if include_candidate_as_of:
        candidate_known_at = candidate.validity.recorded_at
        knowledge_as_of = {
            "known_as_of": candidate_known_at,
            "valid_as_of": candidate_known_at,
        }
    knowledge = KnowledgeSnapshot(
        statements=statements,
        entities=entities,
        slices=[snapshot.slice],
        evidence=evidence_records(data, statements),
        as_of=knowledge_as_of,
    )
    ontology = VersionedRef(
        id="alfalab.supply-chain-ontology",
        version="1.0.1",
        hash="sha256:ab9a6817283a643d64eedf9a827567bf738ab9b1f5cdd301d3117e26d8ab71a1",
    )
    rules = default_graph_rules(ontology)
    request = BuildGraphInput(
        graph_id=f"graph-{snapshot.company.entity_id}-t12-input",
        knowledge=knowledge,
        ontology=ontology,
        rules=rules.ref,
    )
    return request, refs, [snapshot.ref], row
