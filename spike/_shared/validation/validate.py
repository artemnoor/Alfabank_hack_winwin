"""Reproducible offline validation for the frozen provisional T09-T13 corpus."""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path
from typing import Any


SHARED = Path(__file__).resolve().parents[1]
ROOT = SHARED.parents[1]
DATASET_ID = "t09-t13-independent-v1"
VERSION = "1.0.1"
REQUIRED_OPERATION_IDS = [
    "Understanding.extract",
    "Events.propose_resolution",
    "Events.apply",
    "Events.read",
    "Business.propose_profile",
    "Business.propose_questions",
    "Business.apply",
    "Business.read",
    "Evidence.register",
    "Evidence.read",
    "Graph.build",
    "Graph.publish",
    "Graph.query",
    "Matching.match",
    "Impact.assess",
    "Recommendations.propose",
]
DATASET_DIR = SHARED / "datasets" / DATASET_ID
CONTRACT_DIR = SHARED / "contracts" / DATASET_ID
FIXTURE_DIR = SHARED / "fixtures" / DATASET_ID


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def schema_references(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.append(ref.removeprefix("#/components/schemas/"))
        for child in value.values():
            found.extend(schema_references(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(schema_references(child))
    return found


def schema_closure(schemas: dict[str, Any], roots: list[str]) -> set[str]:
    closure: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        require(name in schemas, f"missing OpenAPI component: {name}")
        closure.add(name)
        pending.extend(schema_references(schemas[name]))
    return closure


def load_contracts():
    sys.path.insert(0, str(ROOT / "packages/contracts/src"))
    from alfalab_contracts.registry import load_operation_registry

    return load_operation_registry(
        ROOT / "docs/specs/framework-v1/contracts/operations.json",
        ROOT / "docs/specs/framework-v1/contracts/openapi.json",
    )


def check_manifest_and_data(manifest: dict[str, Any], data: dict[str, Any]) -> None:
    require(manifest["schema"] == "alfalab.spike.synthetic-dataset-manifest/v1", "unexpected manifest schema")
    require(manifest["dataset_id"] == DATASET_ID and manifest["version"] == VERSION, "dataset identity/version drift")
    require(manifest["origin"] == "synthetic", "dataset origin must remain synthetic")
    require(manifest["manual_approval"] == "provisional", "dataset must remain provisional")
    require(manifest["status"] == "provisional_not_gold_not_approved", "dataset must not be treated as gold/approved")
    require(canonical_hash(data) == manifest["data_hash"], "canonical data.json hash mismatch")
    require(data["dataset_id"] == DATASET_ID and data["version"] == VERSION, "data identity/version drift")
    require(data["provenance"]["base_commit"] == manifest["provenance"]["base_commit"], "base commit mismatch")
    require(data["provenance"]["model_outputs_used_as_labels"] is False, "model outputs must not become labels")
    require(data["provenance"]["external_sources_used_for_facts"] is False, "unexpected factual external source")
    for name, expected_hash in manifest["files"].items():
        path = (DATASET_DIR / name) if name == "data.json" else (CONTRACT_DIR / name)
        require(path.is_file(), f"manifest file missing: {path}")
        require(file_hash(path) == expected_hash if name != "data.json" else file_hash(path) == expected_hash["file_sha256"], f"manifest file SHA mismatch: {path}")
    require(manifest["files"]["data.json"]["canonical_sha256"] == manifest["data_hash"], "manifest canonical/data hash mismatch")


def check_source_pins(manifest: dict[str, Any]) -> None:
    refs = manifest["provenance"]["framework_sources"]
    require(len(refs) >= 8, "expected pinned normative and implementation source refs")
    for ref in refs:
        path = ROOT / ref["path"]
        require(path.is_file(), f"pinned source missing: {ref['path']}")
        require(file_hash(path) == ref["sha256"], f"pinned source changed: {ref['path']}")
    pdf = manifest["provenance"]["pdf_source"]
    pdf_path = Path(pdf["path"])
    require(pdf["pages_reviewed"] == [4, 5, 6, 7, 8, 9], "PDF page scope changed")
    if pdf_path.is_file():
        require(file_hash(pdf_path) == pdf["sha256"], "source PDF hash mismatch")


def check_approved_refs(refs: dict[str, Any]) -> None:
    index_path = ROOT / refs["index_path"]
    require(file_hash(index_path) == refs["index_sha256"], "approved fixture index hash mismatch")
    index = read_json(index_path)
    for ref in refs["fixture_refs"]:
        path = ROOT / ref["path"]
        require(file_hash(path) == ref["sha256"], f"approved manifest normalized-LF hash mismatch: {ref['path']}")
        index_key = f"{ref['operation_id']}/{ref['fixture_id']}/manifest.json"
        require(index["files"].get(index_key) == ref["approved_index_sha256"], f"approved index reference mismatch: {index_key}")
    for ref in refs["dataset_refs"]:
        data_path = ROOT / ref["data_path"]
        manifest_path = ROOT / ref["manifest_path"]
        expected = index["datasets"][ref["dataset_id"]]
        require(file_hash(data_path) == ref["data_sha256"], f"approved dataset normalized-LF hash changed: {ref['dataset_id']}")
        require(ref["approved_data_index_sha256"] == "sha256:" + expected["data_sha256"], f"approved dataset data index reference mismatch: {ref['dataset_id']}")
        require(file_hash(manifest_path) == ref["manifest_sha256"], f"approved dataset manifest normalized-LF hash changed: {ref['dataset_id']}")
        require(ref["approved_manifest_index_sha256"] == "sha256:" + expected["manifest_sha256"], f"approved dataset manifest index reference mismatch: {ref['dataset_id']}")
    require(refs["manual_approval"] == "provisional", "reference file must remain provisional")


def check_contract_lock(lock: dict[str, Any], schema_snapshot: dict[str, Any]) -> None:
    registry_path = ROOT / "docs/specs/framework-v1/contracts/operations.json"
    openapi_path = ROOT / "docs/specs/framework-v1/contracts/openapi.json"
    require(file_hash(registry_path) == lock["operation_registry_hash"], "operation registry hash mismatch")
    require(file_hash(openapi_path) == lock["openapi_hash"], "OpenAPI source hash mismatch")
    for source in lock["source_refs"]:
        require(file_hash(ROOT / source["path"]) == source["sha256"], f"contract source hash mismatch: {source['path']}")

    openapi = read_json(openapi_path)
    schemas = openapi["components"]["schemas"]
    union_components: set[str] = set()
    require(lock["operation_registry_version"] == "1.0.0", "operation registry version mismatch")
    registry, contracts = load_contracts()
    require(len(lock["operations"]) == 16, "expected all 16 T09-T13 operations in lock")
    require([item["operation_id"] for item in lock["operations"]] == REQUIRED_OPERATION_IDS, "T09-T13 operation lock is incomplete or reordered")
    for frozen in lock["operations"]:
        operation_id = frozen["operation_id"]
        require(operation_id in contracts, f"operation missing from current registry: {operation_id}")
        contract = contracts[operation_id]
        entry = contract.descriptor
        require(frozen["schema_hash"] == entry.schema_hash, f"operation schema hash drift: {operation_id}")
        require(frozen["request_model"] == entry.request_model and frozen["response_model"] == entry.response_model, f"request/response model drift: {operation_id}")
        closure = schema_closure(schemas, [entry.request_model, entry.response_model])
        require(sorted(closure) == frozen["component_names"], f"schema component closure drift: {operation_id}")
        canonical_closure = {name: schemas[name] for name in sorted(closure)}
        closure_hash = "sha256:" + hashlib.sha256(canonical_bytes(canonical_closure)).hexdigest()
        require(closure_hash == frozen["schema_hash"], f"recomputed schema closure hash mismatch: {operation_id}")
        union_components.update(closure)
    require(schema_snapshot["component_names"] == sorted(union_components), "frozen schema component set mismatch")
    require(schema_snapshot["schemas"] == {name: schemas[name] for name in sorted(union_components)}, "frozen schema snapshot differs from OpenAPI")
    require(schema_snapshot["openapi_sha256"] == file_hash(openapi_path), "frozen OpenAPI snapshot source hash mismatch")


def check_fixture_metadata_and_strict_payloads(
    manifest: dict[str, Any],
    lock: dict[str, Any],
) -> list[str]:
    from alfalab_contracts.registry import validate_operation_exchange

    _, contracts = load_contracts()
    expected_operations = {item["operation_id"] for item in lock["operations"]}
    seen_operations: set[str] = set()
    passed: list[str] = []
    require(len(manifest["fixtures"]) == 5, "expected exactly five materialized operation fixtures")
    for ref in manifest["fixtures"]:
        path = SHARED / ref["path"]
        require(path.is_file(), f"materialized fixture missing: {ref['path']}")
        require(file_hash(path) == ref["sha256"], f"materialized fixture file hash mismatch: {ref['path']}")
        fixture = read_json(path)
        required = ["fixture_id", "version", "origin", "provenance", "description", "input_refs", "expected_properties", "limitations", "data_hash", "manual_approval", "operation_id", "request", "response"]
        require(all(key in fixture for key in required), f"fixture metadata missing: {ref['path']}")
        require(fixture["version"] == VERSION and fixture["origin"] == "synthetic", f"fixture identity/origin drift: {path.name}")
        require(fixture["manual_approval"] == "provisional", f"fixture must remain provisional: {path.name}")
        require(fixture["dataset_ref"] == {"dataset_id": DATASET_ID, "version": VERSION}, f"fixture points at wrong dataset: {path.name}")
        require(fixture["request"]["data_declaration"] == "synthetic", f"fixture request does not declare synthetic data: {path.name}")
        meta = fixture["response"]["meta"]
        require(meta["lineage"]["synthetic_source"] is True and meta["lineage"]["mock_derivation"] is True, f"fixture lineage is not explicitly synthetic/materialized: {path.name}")
        policy = meta["data_policy"]
        require(policy["classification"] == "synthetic" and policy["egress_allowed"] is False and policy["export_allowed"] is False, f"fixture data policy must be offline synthetic: {path.name}")
        source_documents = {row["document_id"]: row for row in read_json(DATASET_DIR / "data.json")["source_documents"]}
        for source_ref in meta["lineage"]["source_refs"]:
            source = source_documents[source_ref["object_id"]]
            require(source_ref["hash"] == source["content_hash"], f"fixture lineage source hash mismatch: {path.name}/{source_ref['object_id']}")
        data_hash = canonical_hash({"operation_id": fixture["operation_id"], "request": fixture["request"], "response": fixture["response"]})
        require(data_hash == fixture["data_hash"] == ref["data_hash"], f"fixture canonical data hash mismatch: {path.name}")
        require(fixture["operation_id"] == ref["operation_id"], f"fixture operation reference mismatch: {path.name}")
        require(fixture["operation_id"] in expected_operations, f"fixture operation not in frozen lock: {path.name}")
        validate_operation_exchange(
            contracts[fixture["operation_id"]],
            canonical_bytes(fixture["request"]),
            canonical_bytes(fixture["response"]),
        )
        seen_operations.add(fixture["operation_id"])
        passed.append(fixture["operation_id"])
    require(seen_operations == {"Understanding.extract", "Events.read", "Business.read", "Evidence.read", "Graph.query"}, "materialized fixture operation set mismatch")
    return passed


def check_domain_data(data: dict[str, Any], fixtures: list[str]) -> list[str]:
    from alfalab_contracts.models import SCHEMA_TYPES

    required_entities = {"company-a", "company-b", "company-c", "company-a-near", "company-b-parent", "company-b-subsidiary"}
    entity_ids = {item["entity_id"] for item in data["entities"]}
    require(required_entities <= entity_ids, "required synthetic entity/near-name/parent/subsidiary coverage missing")
    companies = {item["company_id"]: item for item in data["company_profiles"]}
    require(set(companies) == {"company-a", "company-b", "company-c"}, "expected exactly the A/B/C synthetic company profiles")
    require(len(companies["company-a"]["snapshots"]) >= 2, "Company A history must include multiple snapshots")
    require(len(companies["company-b"]["snapshots"][-1]["statements"]) >= 6, "Company B must cover suppliers/components/facility/routes")
    require(len(companies["company-c"]["snapshots"][-1]["contradictions"]) >= 1, "Company C inventory conflict is missing")
    for profile in companies.values():
        for snapshot in profile["snapshots"]:
            SCHEMA_TYPES["BusinessSnapshot"].model_validate_json(canonical_bytes(snapshot), strict=True)

    event_types = {item["type"] for item in data["news_event_catalog"]}
    event_ids = {item["event_id"] for item in data["news_event_catalog"]}
    required_types = {"export_restriction", "sanctions", "port_closure", "facility_fire", "raw_material_price_increase", "supplier_default", "tax_change", "cyber_incident", "production_line_stop", "new_investment"}
    require(required_types <= event_types, "one or more of the 10 required synthetic event types are missing")
    require(len(data["t09_resolution_cases"]) >= 30, "T09 case count below 30")
    require(len(data["t10_business_question_cases"]) >= 20, "T10 case count below 20")
    require(len(data["t13_impact_cases"]) >= 30, "T13 case count below 30")
    require(len(data["t12_graph_cases"]) >= 15, "T12 case count below 15 after executable graph-input additions")
    require(all(case["event_id"] in event_ids for case in data["t10_business_question_cases"]), "T10 case references event outside the frozen catalog")
    require(all(case["event_id"] in event_ids for case in data["t13_impact_cases"]), "T13 case references event outside the frozen catalog")
    actions = {case["provisional_expectation"] for case in data["t09_resolution_cases"]}
    require(actions == {"create", "attach", "correct", "merge", "split", "defer"}, "T09 decision coverage must include create/attach/correct/merge/split/defer")
    negative_ids = {case["case_id"] for case in data["non_positive_evidence_cases"]}
    require({"negative-industry-only", "negative-near-name", "negative-parent-subsidiary", "negative-other-country", "negative-rumor", "negative-forecast", "negative-stale", "negative-unknown-supplier"} <= negative_ids, "required negative cases missing")

    docs = {row["document_id"]: row for row in data["source_documents"]}
    for document in docs.values():
        if document["availability"] == "available":
            require(document["text"] is not None and text_hash(document["text"]) == document["content_hash"], f"source text hash mismatch: {document['document_id']}")
        else:
            require(document["text"] is None, "unavailable source must not expose source text")
    evidence = {item["ref"]["object_id"]: item for item in data["evidence_catalog"]}
    require(any(item["verification"] == "unverified" for item in evidence.values()), "an unverified evidence case is required")
    require(any(item["verification"] == "verified_anchor" for item in evidence.values()), "a verified-anchor case is required")
    for raw in evidence.values():
        standard = {key: value for key, value in raw.items() if key != "test_claim"}
        SCHEMA_TYPES["EvidenceRecord"].model_validate_json(canonical_bytes(standard), strict=True)
        source_ref = raw["source_ref"]
        source = docs[source_ref["object_id"]]
        require(source_ref["revision"] == source["version"] and source_ref["hash"] == source["content_hash"], f"Evidence source ref does not pin source version: {raw['ref']['object_id']}")
        if raw["verification"] == "verified_anchor":
            require(source["availability"] == "available", f"verified anchor points at unavailable source: {raw['ref']['object_id']}")
            locator = raw["locator"]
            start, end = locator["start"], locator["end"]
            quote = source["text"][start:end]
            require(start < end and text_hash(quote) == locator["quote_hash"], f"Evidence anchor hash/range mismatch: {raw['ref']['object_id']}")
        else:
            require(raw["verification"] == "unverified", "unknown verification value")

    extract_fixture_path = FIXTURE_DIR / "understanding-extract.json"
    extract_fixture = read_json(extract_fixture_path)
    material = extract_fixture["request"]["payload"]["material"]
    extract_text = material["material"]["text"]
    require(material["prepared_hash"] == text_hash(extract_text), "prepared material hash mismatch")
    span_map = material["span_map"]
    require(len(span_map) == 1 and span_map[0] == {"prepared_start": 0, "prepared_end": len(extract_text), "raw_start": 0, "raw_end": len(extract_text)}, "prepared/raw span map does not preserve all text")
    claim_ids = {statement["statement_id"] for mention in extract_fixture["response"]["payload"]["mentions"] for statement in mention["statements"]}
    for span in extract_fixture["response"]["payload"]["evidence_spans"]:
        locator = span["locator"]
        quote = extract_text[locator["start"]:locator["end"]]
        require(span["material_hash"] == material["prepared_hash"], "extraction evidence span points to another prepared material")
        require(text_hash(quote) == locator["quote_hash"], f"extraction evidence quote hash mismatch: {span['local_id']}")
        require(set(span["claim_ids"]) <= claim_ids, f"extraction span references missing claim: {span['local_id']}")

    source_groups = data["source_grouping_expectations"]
    reposts = [docs[item] for item in source_groups["document_ids"]]
    require(len(reposts) == 10, "expected ten syndicated copies")
    require({item["publisher_root_id"] for item in reposts} == {source_groups["publisher_root_id"]}, "syndicated copies have more than one source root")
    require({item["syndication_group_id"] for item in reposts} == {source_groups["syndication_group_id"]}, "syndicated copies do not share a group")
    require("Graph.query" in fixtures and "Evidence.read" in fixtures, "strict materialized read fixtures were not checked")
    return ["companies/history", "10 event types + negative cases", "T09/T10/T13 case counts + event references", "evidence/source hash and exact-anchor integrity", "extraction span-map and claim refs", "syndication grouping"]


def check_t12_executable_inputs(data: dict[str, Any]) -> list[str]:
    from alfalab_contracts.models import SCHEMA_TYPES
    from alfalab_contracts.semantics import validate_dto

    snapshot_map = {
        (profile["company_id"], snapshot["ref"]["revision"]): snapshot
        for profile in data["company_profiles"]
        for snapshot in profile["snapshots"]
    }
    evidence = {item["ref"]["object_id"]: item for item in data["evidence_catalog"]}
    documents = {item["document_id"]: item for item in data["source_documents"]}
    inputs = {item["input_id"]: item for item in data["t12_graph_inputs"]}
    required = {"hypothetical-only", "inferred-company-country-x", "explicit-negative-country-x"}
    require(set(inputs) == required, "T12 graph input set is incomplete or has unexpected inputs")
    checked = []
    for input_id, item in inputs.items():
        require(item["version"] == VERSION and item["origin"] == "synthetic", f"T12 input identity/origin drift: {input_id}")
        require(item["manual_approval"] == "provisional", f"T12 input must remain provisional: {input_id}")
        require(item["data_hash"] == canonical_hash(item["payload"]), f"T12 input canonical hash mismatch: {input_id}")
        required_metadata = {"input_id", "version", "origin", "provenance", "description", "inputs", "payload", "expected_properties", "limitations", "data_hash", "manual_approval"}
        require(required_metadata <= set(item), f"T12 input metadata incomplete: {input_id}")
        require(bool(item["description"]) and item["expected_properties"] and item["limitations"], f"T12 input must declare a description, expectations and limits: {input_id}")
        aggregate = item["payload"]["aggregate_snapshot"]
        aggregate_model = SCHEMA_TYPES["BusinessSnapshot"].model_validate_json(canonical_bytes(aggregate), strict=True)
        validate_dto(aggregate_model)
        candidate = item["payload"]["candidate_statement"]
        candidate_model = SCHEMA_TYPES["Statement"].model_validate_json(canonical_bytes(candidate), strict=True)
        validate_dto(candidate_model)
        for input_ref in item["inputs"]:
            kind = input_ref["kind"]
            ref = input_ref["ref"]
            if kind == "BusinessSnapshot":
                require(ref == aggregate["ref"], f"T12 input aggregate reference mismatch: {input_id}")
            elif kind == "StatementRef":
                aggregate_ref = ref["aggregate_ref"]
                if aggregate_ref == aggregate["ref"]:
                    source_snapshot = aggregate
                else:
                    key = (aggregate_ref["object_id"], aggregate_ref["revision"])
                    require(key in snapshot_map, f"T12 metadata StatementRef does not resolve: {input_id}/{key}")
                    source_snapshot = snapshot_map[key]
                require(source_snapshot["ref"] == aggregate_ref, f"T12 metadata StatementRef aggregate hash mismatch: {input_id}")
                source_statement = next((x for x in source_snapshot["statements"] if x["statement_id"] == ref["statement_id"]), None)
                require(source_statement is not None, f"T12 metadata StatementRef statement missing: {input_id}/{ref['statement_id']}")
                require(source_statement["revision"] == ref["revision"] and canonical_hash(source_statement) == ref["hash"], f"T12 metadata StatementRef content hash mismatch: {input_id}/{ref['statement_id']}")
            elif kind == "EvidenceRef":
                evidence_record = evidence.get(ref["object_id"])
                require(evidence_record is not None and evidence_record["ref"] == ref, f"T12 metadata EvidenceRef missing or changed: {input_id}/{ref['object_id']}")
            else:
                raise AssertionError(f"unsupported T12 input ref kind: {kind}")
        refs = candidate["provenance"]["input_statement_refs"]
        if candidate["epistemic_status"] == "inferred":
            require(candidate["provenance"]["origin"] == "derived", f"inferred candidate must have derived provenance: {input_id}")
            require(candidate["provenance"]["derivation_method"] is not None and len(refs) >= 2, f"inferred candidate lacks method or input refs: {input_id}")
        for ref in refs:
            aggregate_ref = ref["aggregate_ref"]
            key = (aggregate_ref["object_id"], aggregate_ref["revision"])
            require(key in snapshot_map, f"T12 input ref does not resolve to a prepared profile snapshot: {input_id}/{key}")
            source_snapshot = snapshot_map[key]
            require(source_snapshot["ref"] == aggregate_ref, f"T12 input ref has wrong immutable aggregate ref: {input_id}/{key}")
            source_statement = next((x for x in source_snapshot["statements"] if x["statement_id"] == ref["statement_id"]), None)
            require(source_statement is not None, f"T12 input statement is missing: {input_id}/{ref['statement_id']}")
            require(source_statement["revision"] == ref["revision"] and canonical_hash(source_statement) == ref["hash"], f"T12 input statement hash/revision mismatch: {input_id}/{ref['statement_id']}")
            require(source_statement["epistemic_status"] == "confirmed", f"inference premise is not confirmed: {input_id}/{ref['statement_id']}")
        if input_id in {"hypothetical-only", "explicit-negative-country-x"}:
            embedded = next((x for x in aggregate["statements"] if x["statement_id"] == candidate["statement_id"]), None)
            require(embedded == candidate, f"T12 candidate is not present in its materialized aggregate: {input_id}")
        if input_id == "hypothetical-only":
            require(candidate["epistemic_status"] == "hypothetical", "hypothetical input status was promoted")
            require(not candidate["provenance"]["source_refs"] and not candidate["provenance"]["evidence_refs"], "hypothetical input must not gain evidence/source refs")
        elif input_id == "inferred-company-country-x":
            require(candidate["epistemic_status"] == "inferred", "inferred candidate status changed")
            require(candidate["provenance"]["derivation_method"]["id"] == "spike.graph.rule.company-supplier-location", "inferred method identifier drift")
            require(len(refs) == 2, "inferred candidate must use the two pinned premises")
        elif input_id == "explicit-negative-country-x":
            require(candidate["epistemic_status"] == "user_declared", "explicit negative must remain a company declaration")
            require(candidate["predicate"]["code"] == "does_not_source_from_country", "negative relation predicate drift")
            evidence_ids = [ref["object_id"] for ref in candidate["provenance"]["evidence_refs"]]
            require(evidence_ids == ["ev-a-source-denial"], "explicit negative must cite its exact evidence record")
            anchor = evidence[evidence_ids[0]]
            source = documents[anchor["source_ref"]["object_id"]]
            require(anchor["verification"] == "verified_anchor" and source["availability"] == "available", "negative source anchor must be available and anchor-verified")
            locator = anchor["locator"]
            quote = source["text"][locator["start"]:locator["end"]]
            require(text_hash(quote) == locator["quote_hash"], "negative statement anchor does not match its source text")
        checked.append(input_id)

    cases = {case["case_id"]: case for case in data["t12_graph_cases"]}
    require(cases["hypothetical-only"]["input_ref"] == "hypothetical-only", "hypothetical case is dangling")
    require(cases["inferred-relation-grounding"]["input_ref"] == "inferred-company-country-x", "inferred case is dangling")
    require(cases["explicit-negative-not-positive-dependency"]["input_ref"] == "explicit-negative-country-x", "explicit-negative case is dangling")
    negative_limitations = " ".join(inputs["explicit-negative-country-x"]["limitations"]).lower()
    require("not that its claim is true" in negative_limitations, "negative input limitations must distinguish anchor from truth")
    return ["strict T12 snapshot/candidate DTO and semantic checks", "inferred refs resolve to confirmed immutable premises", "hypothetical and explicit-negative inputs resolve to materialized statements", "negative evidence anchor integrity without truth promotion"]


def check_owner_policy_and_graph(data: dict[str, Any], fixture_files: list[Path]) -> list[str]:
    from alfalab_contracts.models import SCHEMA_TYPES

    policy = data["synthetic_confirmed_assertion_policy"]
    authorized = set(policy["authorized_statement_ids"])
    evidence = {item["ref"]["object_id"]: item for item in data["evidence_catalog"]}
    docs = {row["document_id"]: row for row in data["source_documents"]}
    statement_map: dict[tuple[str, int, str], dict[str, Any]] = {}
    confirmed = []
    for company_id, profile in ((p["company_id"], p) for p in data["company_profiles"]):
        for snapshot in profile["snapshots"]:
            for item in snapshot["statements"]:
                statement_map[(company_id, snapshot["ref"]["revision"], item["statement_id"])] = item
                if item["epistemic_status"] == "confirmed":
                    confirmed.append(item)
    for path in fixture_files:
        fixture = read_json(path)
        payload = fixture["response"]["payload"]
        if fixture["operation_id"] == "Events.read":
            for event in payload["snapshot"]["events"]:
                SCHEMA_TYPES["EventRecord"].model_validate_json(canonical_bytes(event), strict=True)
                for item in event["statements"]:
                    if item["epistemic_status"] == "confirmed":
                        confirmed.append(item)
        if fixture["operation_id"] == "Graph.query":
            graph = payload["subgraph"]["snapshot"]
            SCHEMA_TYPES["GraphSnapshot"].model_validate_json(canonical_bytes(graph), strict=True)
            nodes = {node["node_id"] for node in graph["nodes"]}
            require(len(nodes) == len(graph["nodes"]), "graph node IDs are not unique")
            for edge in graph["edges"]:
                require(edge["source_node_id"] in nodes and edge["target_node_id"] in nodes, f"edge endpoint missing: {edge['edge_id']}")
                require(edge["epistemic_status"] != "inferred", "dataset must not contain an ungrounded inferred edge")
                require(len(edge["statement_refs"]) > 0, f"graph edge lacks source statement refs: {edge['edge_id']}")
                for ref in edge["statement_refs"]:
                    key = (ref["aggregate_ref"]["object_id"], ref["aggregate_ref"]["revision"], ref["statement_id"])
                    require(key in statement_map, f"graph statement ref cannot be resolved: {edge['edge_id']} -> {key}")
                    statement_item = statement_map[key]
                    require(ref["hash"] == canonical_hash(statement_item), f"graph statement ref hash mismatch: {edge['edge_id']}")
    for item in confirmed:
        require(item["statement_id"] in authorized, f"confirmed synthetic statement lacks named owner-policy opt-in: {item['statement_id']}")
        evidence_ids = [ref["object_id"] for ref in item["provenance"]["evidence_refs"]]
        require(evidence_ids, f"confirmed synthetic statement has no evidence refs: {item['statement_id']}")
        root_ids = set()
        for evidence_id in evidence_ids:
            record = evidence[evidence_id]
            require(record["verification"] == "verified_anchor", f"confirmed statement uses an unverified anchor: {item['statement_id']}")
            root_ids.add(docs[record["source_ref"]["object_id"]]["publisher_root_id"])
        require(len(root_ids) >= 2, f"confirmed synthetic statement lacks independent publisher roots: {item['statement_id']}")
    require(policy["scope"].startswith("Only this provisional synthetic corpus"), "owner policy must be corpus-scoped, not production policy")
    require(data["company_profiles"][0]["company_id"] == "company-a", "profile order changed unexpectedly")
    a_latest = data["company_profiles"][0]["snapshots"][-1]
    require(any(item["statement_id"] == "a-supplier-unknown" and item["epistemic_status"] == "unknown" for item in a_latest["statements"]), "sparse company A must explicitly preserve unknown supplier")
    graph_fixture = next(read_json(path) for path in fixture_files if read_json(path)["operation_id"] == "Graph.query")
    graph = graph_fixture["response"]["payload"]["subgraph"]["snapshot"]
    a_node = next(node for node in graph["nodes"] if node["entity"]["entity_id"] == "company-a")
    require(not any(edge["source_node_id"] == a_node["node_id"] and edge["relation"]["code"] in {"purchases_from", "uses_component", "uses_material"} for edge in graph["edges"]), "sparse company A has a fabricated dependency edge")
    require(graph["completeness"] == "partial", "shared graph must declare partial completeness")
    return ["named test-owner confirmed policy", "confirmed statements cite distinct verified source roots", "graph edge endpoint/provenance/hash checks", "open-world sparse A check"]


def check_reproducible_builder(data: dict[str, Any], fixture_paths: list[Path]) -> list[str]:
    namespace = runpy.run_path(str(SHARED / "validation" / "freeze_v1.py"))
    regenerated = namespace["data_payload"]()
    require(canonical_hash(regenerated) == canonical_hash(data), "freeze builder output differs from committed data.json")
    fixture_values = namespace["materialized_fixture_payloads"]()
    frozen_by_name = {path.stem: read_json(path) for path in fixture_paths}
    require(set(fixture_values) == set(frozen_by_name), "freeze builder fixture set differs from frozen files")
    for name, fixture in fixture_values.items():
        require(fixture == frozen_by_name[name], f"freeze builder output differs from frozen fixture: {name}")
    return ["deterministic data builder reproduction", "deterministic five-fixture reproduction"]


def write_report(checks: list[str], failures: list[str]) -> None:
    py_version = sys.version.split()[0]
    import pydantic
    data = read_json(DATASET_DIR / "data.json")
    lines = [
        "# Shared dataset validation report",
        "",
        f"- Dataset: `{DATASET_ID}` version `{VERSION}`; v1.0.0 is preserved in historical commit `db48cd37491e8fab8a9f122ae4b100da72197a81` and superseded due CRLF-sensitive hashes and a dangling T12 case.",
        "- Command: `python -B spike/_shared/validation/validate.py`.",
        "- Canonical dataset SHA-256: `" + canonical_hash(data) + "`.",
        "- Scope: canonical hashes, pinned sources, immutable approved-fixture refs, current OpenAPI closure, five strict operation exchanges, domain/provenance rules, and fixture counts.",
        "- Environment: Python `" + py_version + "`; Pydantic `" + pydantic.__version__ + "`.",
        "- Network/database/model calls: none.",
        f"- Passed checks: {len(checks)}; failed checks: {len(failures)}; skipped checks: 0.",
        f"- Provisional scenario counts: T09 `{len(data['t09_resolution_cases'])}`, T10 `{len(data['t10_business_question_cases'])}`, T11 `{len(data['t11_evidence_policy_cases'])}`, T12 `{len(data['t12_graph_cases'])}`, T13 `{len(data['t13_impact_cases'])}`.",
        "",
        "## Passed",
        "",
    ]
    lines.extend(f"- {item}" for item in checks)
    lines.extend(["", "## Failed", ""])
    lines.extend(f"- {item}" for item in failures) if failures else lines.append("- None.")
    lines.extend(["", "## Interpretation", "", "A green strict contract check establishes payload shape and contract semantics only. Synthetic property expectations are provisional and do not establish algorithm quality or real-world truth.", ""])
    report_path = SHARED / "validation" / "VALIDATION_REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> int:
    manifest_path = DATASET_DIR / "manifest.json"
    data_path = DATASET_DIR / "data.json"
    manifest = read_json(manifest_path)
    data = read_json(data_path)
    lock = read_json(CONTRACT_DIR / "operations-lock.json")
    schema_snapshot = read_json(CONTRACT_DIR / "openapi-schema-snapshot.json")
    approved = read_json(CONTRACT_DIR / "approved-fixture-refs.json")
    failures: list[str] = []
    checks: list[str] = []

    def run(label: str, function, *args) -> Any:
        try:
            result = function(*args)
            checks.append(label)
            return result
        except Exception as exc:  # Report all independent groups before returning nonzero.
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    run("dataset identity and canonical/file hashes", check_manifest_and_data, manifest, data)
    run("PDF/framework source pins", check_source_pins, manifest)
    run("immutable approved fixture and dataset refs", check_approved_refs, approved)
    run("16-operation and OpenAPI component lock", check_contract_lock, lock, schema_snapshot)

    strict_operation_ids: list[str] = []
    try:
        strict_operation_ids = check_fixture_metadata_and_strict_payloads(manifest, lock)
        checks.extend(f"strict Pydantic exchange: {operation_id}" for operation_id in strict_operation_ids)
    except Exception as exc:
        failures.append(f"strict Pydantic operation fixtures: {type(exc).__name__}: {exc}")

    fixture_paths = [SHARED / ref["path"] for ref in manifest["fixtures"]]
    run("company/event/case coverage and evidence anchors", check_domain_data, data, strict_operation_ids)
    run("executable T12 hypothetical/inferred/negative graph inputs", check_t12_executable_inputs, data)
    run("confirmed-policy and graph provenance invariants", check_owner_policy_and_graph, data, fixture_paths)
    run("deterministic freeze builder reproduction", check_reproducible_builder, data, fixture_paths)
    write_report(checks, failures)
    print(json.dumps({"dataset_id": DATASET_ID, "canonical_data_hash": manifest["data_hash"], "passed_checks": len(checks), "failed_checks": len(failures), "strict_operation_fixtures": strict_operation_ids, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
