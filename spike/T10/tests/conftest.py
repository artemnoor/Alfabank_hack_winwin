"""Shared, read-only adapters for the pinned synthetic T10 corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alfalab_contracts.models import BusinessSnapshot, CodeRef, EventRecord, ObjectRef


ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = ROOT / "spike" / "_shared" / "datasets" / "t09-t13-independent-v1"
DATASET_HASH = "sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725"


@pytest.fixture(scope="session")
def dataset() -> dict[str, object]:
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == "t09-t13-independent-v1"
    assert manifest["version"] == "1.0.1"
    assert manifest["data_hash"] == DATASET_HASH
    assert manifest["manual_approval"] == "provisional"
    return json.loads((DATASET_DIR / "data.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def profiles(dataset: dict[str, object]) -> dict[str, list[BusinessSnapshot]]:
    return {
        item["company_id"]: [BusinessSnapshot.model_validate(row) for row in item["snapshots"]]
        for item in dataset["company_profiles"]
    }


@pytest.fixture(scope="session")
def events(dataset: dict[str, object]) -> dict[str, EventRecord]:
    records: dict[str, EventRecord] = {}
    for item in dataset["news_event_catalog"]:
        records[item["event_id"]] = EventRecord(
            ref=ObjectRef(
                owner="Events",
                object_id=item["event_id"],
                revision=1,
                hash="sha256:" + ("0" * 64),
            ),
            event_type=CodeRef(namespace="alfalab.event", version="1.0.1", code=item["type"]),
            lifecycle="active",
            statements=[],
            mention_ids=[],
            lineage_refs=[],
            missing_data=[],
        )
    return records


@pytest.fixture(scope="session")
def latest_profile(profiles: dict[str, list[BusinessSnapshot]]):
    def get(company_id: str) -> BusinessSnapshot:
        return max(profiles[company_id], key=lambda item: item.ref.revision)

    return get
