"""Run the hand-authored T11 trust cases without network, models, or writes."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
T11 = ROOT / "spike" / "T11"
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(T11 / "src"))

from evidence_trust import (  # noqa: E402
    SourceAssertion,
    assess_claim,
    evaluate_owner_policy,
    project_catalog_record,
)


DATASET_ID = "t09-t13-independent-v1"
DATASET_VERSION = "1.0.1"
DATA_HASH = "sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def main() -> int:
    shared = ROOT / "spike" / "_shared"
    data_dir = shared / "datasets" / DATASET_ID
    fixture_dir = shared / "fixtures" / DATASET_ID
    contracts_dir = shared / "contracts" / DATASET_ID
    t11_fixture_path = T11 / "fixtures" / "trust-cases-v1.0.0.json"
    manifest = read_json(data_dir / "manifest.json")
    data = read_json(data_dir / "data.json")
    policy = read_json(contracts_dir / "synthetic-owner-policy.json")
    fixture = read_json(t11_fixture_path)

    if manifest["version"] != DATASET_VERSION or fixture["dataset_ref"]["version"] != DATASET_VERSION:
        raise SystemExit("T11 fixture is intentionally pinned to the named shared dataset version")
    if canonical_hash(data) != DATA_HASH or manifest["data_hash"] != DATA_HASH:
        raise SystemExit("pinned shared dataset content hash mismatch")
    fixture_hash_input = dict(fixture)
    expected_fixture_hash = fixture_hash_input.pop("content_hash")
    if canonical_hash(fixture_hash_input) != expected_fixture_hash:
        raise SystemExit("T11 case fixture content hash mismatch")

    record_catalog = {row["ref"]["object_id"]: row for row in data["evidence_catalog"]}
    source_catalog = {row["document_id"]: row for row in data["source_documents"]}
    assertions = [SourceAssertion.from_mapping(row) for row in fixture["source_assertions"]]
    results: list[dict[str, Any]] = []

    for case in fixture["cases"]:
        refs = case["evidence_refs"]
        records = {ref: project_catalog_record(record_catalog[ref]) for ref in refs}
        sources = {
            record["source_ref"]["object_id"]: copy.deepcopy(source_catalog[record["source_ref"]["object_id"]])
            for record in records.values()
        }
        if case["mutation"] == "wrong_quote":
            records["ev-export-official"]["locator"]["start"] += 1
        elif case["mutation"] == "wrong_source_hash":
            records["ev-export-official"]["source_hash"] = "sha256:" + "0" * 64
        elif case["mutation"] == "source_version_mismatch":
            records["ev-export-correction"]["source_ref"]["revision"] += 1

        case_assertions = [item for item in assertions if item.evidence_ref in set(refs)]
        assessment = assess_claim(
            case["claim_id"], case_assertions, records, sources,
            valid_as_of=manifest["as_of"]["valid_as_of"],
            known_as_of=manifest["as_of"]["known_as_of"],
        )
        anchor_states = sorted({item.anchor.integrity.value for item in assessment.observations})
        if not anchor_states:
            anchor_states = ["none"]
        policy_result = None
        if case.get("policy_mode") == "explicit":
            policy_result = evaluate_owner_policy(
                case["statement_id"], assessment, case_assertions, records, sources,
                policy, dataset_id=DATASET_ID,
            )
        results.append({
            "case_id": case["case_id"],
            "anchor_integrity": anchor_states,
            "source_assertion_state": assessment.source_assertion_state,
            "claim_status": assessment.status.value,
            "evidence_refs": list(assessment.evidence_refs),
            "distinct_supporting_publisher_roots": assessment.distinct_supporting_publisher_roots,
            "observations": [
                {
                    "annotation_id": row.annotation_id,
                    "annotation_provenance": row.annotation_provenance,
                    "evidence_ref": row.evidence_ref,
                    "relation": row.relation,
                    "value": row.value,
                    "temporal_scope": row.temporal_scope,
                    "source_ref": {
                        "owner": row.source_ref[0],
                        "object_id": row.source_ref[1],
                        "revision": row.source_ref[2],
                        "hash": row.source_ref[3],
                    },
                    "source": {
                        "availability": row.source_availability,
                        "published_at": row.source_published_at,
                        "collected_at": row.source_collected_at,
                        "recorded_at": row.source_recorded_at,
                        "registration_at": row.source_registration_at,
                        "registration_method": row.source_registration_method,
                        "applicability_reason_codes": list(row.applicability_reason_codes),
                        "source_type": row.source_type,
                        "origin": row.source_origin,
                        "publisher_id": row.source_publisher_id,
                        "publisher_root_id": row.publisher_root_id,
                        "syndication_group_id": row.syndication_group_id,
                    },
                    "anchor": {
                        "integrity": row.anchor.integrity.value,
                        "reason_codes": list(row.anchor.reason_codes),
                        "locator_kind": row.anchor.locator_kind,
                        "start": row.anchor.locator_start,
                        "end": row.anchor.locator_end,
                        "quote_hash": row.anchor.quote_hash,
                        "declared_verification": row.anchor.declared_verification,
                    },
                    "applicable_as_of": row.applicable_as_of,
                }
                for row in assessment.observations
            ],
            "owner_review_eligible": (
                policy_result.eligible_for_owner_review if policy_result is not None else None
            ),
            "owner_policy_reason_codes": (
                list(policy_result.reason_codes) if policy_result is not None else []
            ),
            "owner_policy_id": policy_result.policy_id if policy_result is not None else None,
            "owner_policy_version": policy_result.policy_version if policy_result is not None else None,
            "owner_policy_hash": policy_result.policy_hash if policy_result is not None else None,
            "final_status": assessment.final_status,
        })

    output = {
        "experiment_id": "t11-evidence-trust-offline-v1.0.1",
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "dataset_hash": DATA_HASH,
        "fixture_id": fixture["fixture_id"],
        "fixture_content_hash": expected_fixture_hash,
        "origin": "synthetic",
        "manual_approval": "provisional",
        "time_slice": {
            "valid_as_of": manifest["as_of"]["valid_as_of"],
            "known_as_of": manifest["as_of"]["known_as_of"],
        },
        "model_quality": "NOT MEASURED",
        "cases": results,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
