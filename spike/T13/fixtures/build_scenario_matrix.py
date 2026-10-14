from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SHARED_DATA = ROOT / "spike" / "_shared" / "datasets" / "t09-t13-independent-v1" / "data.json"
OUTPUT = Path(__file__).with_name("scenario_matrix.json")

# Explicit test context, assembled from the frozen event catalog and entity inventory.
# It is metadata for controlled scenarios, not a predicted impact label.
TARGETS = {
    "event-export-x-mk7": ["country-x", "component-mk7"],
    "event-sanction-microkaskad": ["supplier-b-x"],
    "event-port-vega": ["port-vega"],
    "event-fire-north-plant": ["plant-north"],
    "event-fire-east-plant": ["plant-east"],
    "event-price-nickel-actual": ["material-nickel"],
    "event-default-rumor": ["supplier-b-y"],
    "event-tax-lira": [],
    "event-cyber-orbita": ["company-b"],
    "event-line-stop-orbita": ["company-b", "plant-b"],
    "event-investment-techno": ["company-c"],
    "event-export-meridian-mk9": ["country-q", "product-p17"],
    "event-price-nickel-forecast": ["material-nickel"],
    "event-port-old-2025": ["port-vega"],
    "event-industry-outlook": [],
}
FACTUAL_STATUS = {
    "event-export-x-mk7": "confirmed",
    "event-sanction-microkaskad": "confirmed",
    "event-port-vega": "confirmed",
    "event-fire-north-plant": "reported",
    "event-fire-east-plant": "reported",
    "event-price-nickel-actual": "confirmed",
    "event-default-rumor": "rumor",
    "event-tax-lira": "confirmed",
    "event-cyber-orbita": "under_investigation",
    "event-line-stop-orbita": "planned",
    "event-investment-techno": "announced",
    "event-export-meridian-mk9": "confirmed",
    "event-price-nickel-forecast": "forecast",
    "event-port-old-2025": "historical",
    "event-industry-outlook": "sector_only",
}
CURRENT = {event_id: status not in {"historical", "forecast"} for event_id, status in FACTUAL_STATUS.items()}

def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def main() -> None:
    data = json.loads(SHARED_DATA.read_text(encoding="utf-8"))
    data_hash = canonical_hash(data)
    entity_ids = {item["entity_id"] for item in data["entities"]}
    evidence_ids = {item["ref"]["object_id"] for item in data["evidence_catalog"]}
    cases = []
    for row in data["t13_impact_cases"]:
        event_id = row["event_id"]
        event = next(item for item in data["news_event_catalog"] if item["event_id"] == event_id)
        status = FACTUAL_STATUS[event_id]
        case_status = status
        if row["case_id"] == "export-b-source-conflict":
            case_status = "disputed"
        targets = TARGETS[event_id]
        if not set(targets).issubset(entity_ids):
            raise ValueError(f"scenario {row['case_id']} has a target absent from the shared entity inventory")
        if not set(event["evidence_ids"]).issubset(evidence_ids):
            raise ValueError(f"scenario {row['case_id']} has evidence refs absent from the shared corpus")
        scenario = {
            "case_id": row["case_id"],
            "event_id": event_id,
            "event_type": event["type"],
            "company_id": row["company_id"],
            "target_entity_ids": TARGETS[event_id],
            "event_evidence_ids": event["evidence_ids"],
            "factual_status": case_status,
            "current": CURRENT[event_id],
            "graph_freshness": "stale" if row["case_id"] == "stale-port-closure-c" else "current",
            "sector_only": event_id == "event-industry-outlook",
            "numeric_scenario_id": data["controlled_numeric_scenario"]["scenario_id"] if row["case_id"] == "export-b-explicit-numeric-assumptions" else None,
            "provisional_expectations": row["provisional_expectations"],
            "manual_approval": row["manual_approval"],
            "source_case_ref": row["case_id"],
            "data_hash": data_hash,
            "input_refs": [event_id, row["company_id"], "graph-shared-companies-current", *event["evidence_ids"]],
            "limitations": ["Target entity context is an explicit hand-authored test mapping, not a T09 output.", "All expectations are provisional; the graph remains partial/open-world."],
            "provenance": {
                "origin": "synthetic",
                "mapping_source": "shared news_event_catalog plus explicit T13 TARGETS/FACTUAL_STATUS tables",
                "model_outputs_used_as_labels": False,
            },
        }
        scenario["fixture_sha256"] = canonical_hash(scenario)
        cases.append(scenario)
    payload = {
        "schema": "alfalab.spike.t13-scenario-matrix/v1",
        "dataset_ref": {"dataset_id": data["dataset_id"], "version": data["version"], "canonical_sha256": data_hash},
        "status": "provisional_not_gold_not_approved",
        "origin": "synthetic",
        "model_outputs_used_as_labels": False,
        "description": "Materialized event/company test contexts for the T13 offline harness; scenario target mapping is explicit and reviewable.",
        "scenario_count": len(cases),
        "scenarios": cases,
    }
    payload["fixture_sha256"] = canonical_hash(payload)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)} scenarios={len(cases)} dataset={data['version']} hash={payload['dataset_ref']['canonical_sha256']}")

if __name__ == "__main__":
    main()
