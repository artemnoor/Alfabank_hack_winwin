from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
T11 = ROOT / "spike" / "T11"
sys.path.insert(0, str(T11 / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))


@pytest.fixture(scope="session")
def t11_paths() -> dict[str, Path]:
    shared = ROOT / "spike" / "_shared"
    dataset_id = "t09-t13-independent-v1"
    return {
        "root": ROOT,
        "t11": T11,
        "shared": shared,
        "data": shared / "datasets" / dataset_id / "data.json",
        "manifest": shared / "datasets" / dataset_id / "manifest.json",
        "policy": shared / "contracts" / dataset_id / "synthetic-owner-policy.json",
        "evidence_read": shared / "fixtures" / dataset_id / "evidence-read.json",
        "local_fixture": T11 / "fixtures" / "trust-cases-v1.0.0.json",
    }


@pytest.fixture(scope="session")
def t11_bundle(t11_paths: dict[str, Path]) -> dict:
    manifest = json.loads(t11_paths["manifest"].read_text(encoding="utf-8"))
    fixture = json.loads(t11_paths["local_fixture"].read_text(encoding="utf-8"))
    data = json.loads(t11_paths["data"].read_text(encoding="utf-8"))
    policy = json.loads(t11_paths["policy"].read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == fixture["dataset_ref"]["dataset_id"]
    assert manifest["version"] == fixture["dataset_ref"]["version"] == "1.0.1"
    assert manifest["data_hash"] == fixture["dataset_ref"]["canonical_sha256"]
    assert manifest["manual_approval"] == fixture["manual_approval"] == "provisional"
    return {
        "manifest": manifest,
        "fixture": fixture,
        "data": data,
        "policy": policy,
        "records": {row["ref"]["object_id"]: row for row in data["evidence_catalog"]},
        "sources": {row["document_id"]: row for row in data["source_documents"]},
        "assertions": fixture["source_assertions"],
    }
