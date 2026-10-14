"""Build immutable T09 test inputs from the pinned provisional shared corpus."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from alfalab_contracts.models import SCHEMA_TYPES

from .resolution import canonical_json, sha256_ref

ROOT = Path(__file__).resolve().parents[4]
SHARED_DIR = ROOT / "spike" / "_shared"
DEFAULT_DATASET_VERSION = "1.0.1"
DEFAULT_DATASET_HASH = "sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725"


def _shared_path(environment_key: str, default: Path, allowed_root: Path) -> Path:
    configured = os.environ.get(environment_key)
    if not configured:
        return default
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{environment_key} must remain under {root}")
    return resolved


EXPECTED_DATASET_VERSION = os.environ.get("T09_SHARED_DATASET_VERSION", DEFAULT_DATASET_VERSION)
EXPECTED_DATA_HASH = os.environ.get("T09_SHARED_DATASET_HASH", DEFAULT_DATASET_HASH)
if EXPECTED_DATASET_VERSION != DEFAULT_DATASET_VERSION and "T09_SHARED_DATASET_HASH" not in os.environ:
    raise ValueError("Set T09_SHARED_DATASET_HASH when selecting a non-default shared dataset version")
DATASET_DIR = _shared_path(
    "T09_SHARED_DATASET_DIR",
    SHARED_DIR / "datasets" / "t09-t13-independent-v1",
    SHARED_DIR / "datasets",
)
SHARED_FIXTURES = _shared_path(
    "T09_SHARED_FIXTURES_DIR",
    SHARED_DIR / "fixtures" / "t09-t13-independent-v1",
    SHARED_DIR / "fixtures",
)

ResolutionInput = SCHEMA_TYPES["ResolutionInput"]
EventRecord = SCHEMA_TYPES["EventRecord"]
EventSnapshot = SCHEMA_TYPES["EventSnapshot"]
EvidenceRecord = SCHEMA_TYPES["EvidenceRecord"]
EntityRef = SCHEMA_TYPES["EntityRef"]
Statement = SCHEMA_TYPES["Statement"]

EVENT_KIND = {"hash": "sha256:4eb3ed57797dda993fe8fab2b3f09ac726a5a874050af3d22310989afed8d0c1", "id": "entity.facility", "version": "1.0.0"}
EVENT_TAXONOMY = "alfalab.event-taxonomy"
EVENTS_NAMESPACE = "alfalab.events"


@lru_cache(maxsize=1)
def _event_vocab_versions() -> tuple[str, str]:
    """Read event and statement vocabulary versions from the pinned Events.read input.

    Dataset release versions and vocabulary versions are independent. Mentions
    synthesized for the spike must use the exact vocabulary refs already present
    in the materialized snapshot, or candidate matching will correctly reject
    them as incompatible.
    """
    fixture = _load_json(SHARED_FIXTURES / "events-read.json")
    snapshot = EventSnapshot.model_validate(fixture["response"]["payload"]["snapshot"])
    event_versions = {
        event.event_type.version
        for event in snapshot.events
        if event.event_type.namespace == EVENT_TAXONOMY
    }
    predicate_versions = {
        statement.predicate.version
        for event in snapshot.events
        for statement in event.statements
        if statement.predicate.namespace == EVENTS_NAMESPACE
    }
    if len(event_versions) != 1 or len(predicate_versions) != 1:
        raise ValueError("Pinned Events.read fixture must expose one event and statement vocabulary version")
    return next(iter(event_versions)), next(iter(predicate_versions))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset() -> dict[str, Any]:
    manifest = _load_json(DATASET_DIR / "manifest.json")
    if manifest.get("dataset_id") != "t09-t13-independent-v1" or manifest.get("version") != EXPECTED_DATASET_VERSION:
        raise ValueError("Unexpected shared dataset identity/version")
    if manifest.get("data_hash") != EXPECTED_DATA_HASH:
        raise ValueError("Shared dataset hash does not match the T09 frozen dependency")
    data = _load_json(DATASET_DIR / "data.json")
    if sha256_ref(data) != EXPECTED_DATA_HASH:
        raise ValueError("Shared dataset canonical content hash failed")
    file_hash = "sha256:" + hashlib.sha256((DATASET_DIR / "data.json").read_bytes()).hexdigest()
    declared_file_hash = manifest.get("files", {}).get("data.json", {}).get("file_sha256")
    if declared_file_hash and file_hash != declared_file_hash:
        raise ValueError("Shared dataset exact file hash failed")
    return data


def _entities(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["entity_id"]: deepcopy(item) for item in data["entities"]}


def _entity(data: dict[str, Any], entity_id: str, *, name: str | None = None) -> dict[str, Any]:
    found = data.get(entity_id)
    if found:
        result = deepcopy(found)
    else:
        # Explicit test-only perturbations retain the same entity kind while
        # changing the ID. This is not a real company/product assertion.
        source = data.get("component-mk7")
        if source is None:
            source = next(iter(data.values()))
        result = deepcopy(source)
        result["entity_id"] = entity_id
    if name is not None:
        result["display_name"] = name
    return result


def _doc_refs(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["document_id"]: {
            "owner": "Documents",
            "object_id": item["document_id"],
            "revision": item["version"],
            "hash": item["content_hash"],
        }
        for item in data["source_documents"]
    }


def _evidence_records(data: dict[str, Any], doc_refs: dict[str, dict[str, Any]]) -> list[Any]:
    records = []
    for item in data["evidence_catalog"]:
        raw = {
            "ref": item["ref"],
            "source_ref": item["source_ref"],
            "locator": item["locator"],
            "source_hash": item["source_hash"],
            "verification": item["verification"],
            "source_reliability": item["source_reliability"],
            "reliability_method": item["reliability_method"],
        }
        if raw["source_ref"]["object_id"] in doc_refs:
            records.append(EvidenceRecord.model_validate(raw))
    return records


def _base_spec(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    doc = next(item for item in data["source_documents"] if item["document_id"] == doc_id)
    published = doc.get("published_at") or "2026-10-14T00:00:00Z"
    event_day = published[:10] + "T00:00:00Z"
    spec: dict[str, Any] = {
        "event_type": "business_activity",
        "actors": [],
        "objects": [],
        "effective_at": event_day,
        "predicate": "reports_event",
        "epistemic_status": "observed",
        "valid_from": None,
        "valid_to": None,
        "missing_data": [],
    }
    if doc_id.startswith("doc-export-"):
        spec.update(event_type="export_restriction", actors=["country-x"], objects=["component-mk7"], predicate="restricts_export", effective_at="2026-10-13T00:00:00Z")
    if doc_id.startswith("doc-export-reprint-"):
        spec.update(event_type="export_restriction", actors=["country-x"], objects=["component-mk7"], predicate="restricts_export", effective_at="2026-10-13T00:00:00Z")
    if doc_id == "doc-export-correction":
        spec.update(valid_to="2026-11-30T23:59:59Z")
    if doc_id == "doc-export-multi":
        spec.update(event_type="export_restriction", actors=["country-x"], objects=["component-mk7"], predicate="restricts_export", effective_at="2026-10-13T00:00:00Z", multi=True)
    if doc_id == "doc-unrelated-country":
        spec.update(event_type="export_restriction", actors=["country-y"], objects=["component-mk9"], predicate="restricts_export", effective_at="2026-10-13T00:00:00Z")
    if doc_id.startswith("doc-port-"):
        spec.update(event_type="port_closure", actors=["country-z"], objects=["port-vega"], predicate="closes_port", effective_at="2026-10-13T00:00:00Z", valid_from="2026-10-13T00:00:00Z")
    if doc_id == "doc-stale-port":
        spec.update(event_type="port_closure", actors=["country-z"], objects=["port-vega"], predicate="closes_port", effective_at="2025-02-01T00:00:00Z", valid_from="2025-02-01T00:00:00Z")
    if doc_id in {"doc-fire-north", "doc-fire-east", "doc-fire-rumor"}:
        facility = "plant-east" if doc_id == "doc-fire-east" else "plant-north"
        spec.update(event_type="facility_fire", objects=[facility], predicate="fire_at", effective_at="2026-10-13T11:00:00Z")
    if doc_id == "doc-fire-rumor":
        spec["epistemic_status"] = "hypothetical"
    if doc_id == "doc-sanction":
        spec.update(event_type="sanctions", actors=["country-y"], objects=["supplier-b-x"], predicate="sanctions_entity", effective_at="2026-10-12T00:00:00Z")
    if doc_id in {"doc-price-fact", "doc-price-forecast"}:
        spec.update(event_type="price_change", actors=["company-c"], objects=["material-nickel"], predicate="increases_price", effective_at="2026-10-01T00:00:00Z")
    if doc_id == "doc-price-forecast":
        spec["epistemic_status"] = "hypothetical"
    if doc_id == "doc-default-rumor":
        spec.update(event_type="supplier_default", actors=["supplier-b-x"], objects=["supplier-b-x"], predicate="defaults", epistemic_status="hypothetical", effective_at="2026-10-13T00:00:00Z")
    if doc_id == "doc-tax":
        spec.update(event_type="tax_change", actors=["country-y"], objects=["material-nickel"], predicate="changes_import_tax", effective_at="2026-10-10T00:00:00Z")
    if doc_id == "doc-cyber":
        spec.update(event_type="cyber_incident", actors=["company-b"], objects=["plant-b"], predicate="reports_cyber_incident", effective_at="2026-10-13T00:00:00Z")
    if doc_id == "doc-line-stop":
        spec.update(event_type="production_stop", actors=["company-b"], objects=["plant-b"], predicate="stops_production", effective_at="2026-10-14T00:00:00Z")
    if doc_id == "doc-investment":
        spec.update(event_type="investment", actors=["company-b"], objects=["plant-b"], predicate="invests_in", effective_at="2026-10-11T00:00:00Z")
    if doc_id == "doc-parent-release":
        spec.update(event_type="investment", actors=["company-b-parent"], objects=["plant-b"], predicate="invests_in", effective_at="2026-10-09T00:00:00Z")
    if doc_id == "doc-industry-only":
        spec.update(event_type="business_activity", actors=["company-a-near"], objects=[], predicate="operates_in_industry", effective_at="2026-10-13T00:00:00Z", missing_data=[{"path": "/event/object", "reason": "not_provided", "detail": "No event object is identified."}])
    if doc_id in {"doc-c-history", "doc-c-official"}:
        spec.update(event_type="supplier_change", actors=["company-c"], objects=["supplier-c-old"], predicate="changes_supplier", effective_at="2025-01-15T00:00:00Z", valid_from="2025-01-15T00:00:00Z")
    if doc_id == "doc-c-history":
        spec["missing_data"] = [{"path": "/event/successor_supplier", "reason": "not_provided", "detail": "The successor supplier is not stated in this version."}]
    if doc_id == "doc-c-official":
        spec.update(objects=["supplier-c-old", "supplier-c-current"], effective_at="2026-10-02T00:00:00Z", valid_from="2025-01-15T00:00:00Z")
    if doc_id == "doc-archived-unavailable":
        spec.update(event_type="business_activity", actors=[], objects=[], effective_at=None, missing_data=[{"path": "/event/source", "reason": "unavailable", "detail": "Source text is unavailable."}])
    return spec


def _make_mention(doc_id: str, data: dict[str, Any], doc_refs: dict[str, dict[str, Any]], *, variant: str | None = None) -> list[Any]:
    doc = next(item for item in data["source_documents"] if item["document_id"] == doc_id)
    all_entities = _entities(data)
    evidence_by_source: dict[str, list[Any]] = {}
    for item in data["evidence_catalog"]:
        evidence_by_source.setdefault(item["source_ref"]["object_id"], []).append(item["ref"])
    spec = _base_spec(doc_id, data)
    if variant == "unknown-date":
        spec["effective_at"] = None
    if variant == "unverified-source":
        spec["epistemic_status"] = "unknown"
    if variant == "hypothetical":
        spec["epistemic_status"] = "hypothetical"
    if variant == "historical-date":
        spec["effective_at"] = "2025-01-15T00:00:00Z"
    if variant == "object-typo":
        spec["objects"] = ["component-mk7-typo"]
    source_refs = [doc_refs[doc_id]] if doc_id in doc_refs and variant != "unverified-source" else []
    refs = evidence_by_source.get(doc_id, []) if source_refs else []
    descriptions = [spec]
    if spec.get("multi"):
        descriptions = [
            spec,
            {
                **spec,
                "event_type": "price_change",
                "actors": ["company-b"],
                "objects": ["product-p17"],
                "predicate": "increases_sale_price",
                "effective_at": "2026-10-13T00:00:00Z",
                "valid_from": None,
                "valid_to": None,
                "missing_data": [],
            },
        ]
    results = []
    for index, item in enumerate(descriptions):
        mention_id = f"mention-{doc_id.removeprefix('doc-')}-{index + 1}" if len(descriptions) > 1 else f"mention-{doc_id.removeprefix('doc-')}"
        actor_refs = []
        object_refs = []
        for entity_id in item["actors"]:
            source = all_entities.get(entity_id) or _entity(all_entities, entity_id)
            actor_refs.append(source)
        for entity_id in item["objects"]:
            if entity_id == "component-mk9":
                object_refs.append(_entity(all_entities, entity_id, name="Микросхема МК-9"))
            elif entity_id == "component-mk7-typo":
                object_refs.append(_entity(all_entities, entity_id, name="Микросхема МК-7"))
            else:
                object_refs.append(all_entities.get(entity_id) or _entity(all_entities, entity_id))
        subjects = actor_refs[:1] or object_refs[:1]
        statements = []
        for object_index, value_entity in enumerate(object_refs or [None]):
            subject = subjects[0] if subjects else None
            if subject is None:
                continue
            typed_value = {"kind": "entity", "value": value_entity} if value_entity else {"kind": "text", "value": "unspecified"}
            predicate = item["predicate"]
            if object_index > 0:
                predicate = "identifies_supplier"
            statements.append(
                {
                    "statement_id": f"statement-{mention_id}-{object_index + 1}",
                    "revision": 1,
                    "subject": subject,
                    "predicate": {"namespace": EVENTS_NAMESPACE, "code": predicate, "version": _event_vocab_versions()[1]},
                    "value": typed_value,
                    "epistemic_status": item["epistemic_status"],
                    "validity": {"valid_from": item.get("valid_from"), "valid_to": item.get("valid_to"), "recorded_at": doc.get("published_at") or "2026-10-14T00:00:00Z"},
                    "provenance": {
                        "origin": "synthetic",
                        "source_refs": source_refs,
                        "input_statement_refs": [],
                        "producer_run_id": None,
                        "derivation_method": None,
                        "evidence_refs": refs,
                        "origin_verified": False,
                    },
                }
            )
        mention = {
            "mention_id": mention_id,
            "event_type": {"namespace": EVENT_TAXONOMY, "code": item["event_type"], "version": _event_vocab_versions()[0]},
            "actors": actor_refs,
            "objects": object_refs,
            "statements": statements,
            "effective_at": item.get("effective_at"),
            "missing_data": item.get("missing_data", []),
            "provenance": {
                "origin": "synthetic",
                "source_refs": source_refs,
                "input_statement_refs": [],
                "producer_run_id": None,
                "derivation_method": None,
                "evidence_refs": refs,
                "origin_verified": False,
            },
        }
        results.append(SCHEMA_TYPES["EventMention"].model_validate(mention))
    return results


def _record_for_mention(mention: Any, event_id: str, *, missing_data: list[dict[str, Any]] | None = None) -> Any:
    statements = [item.model_dump(mode="json") for item in mention.statements]
    data = {
        "event_type": mention.event_type.model_dump(mode="json"),
        "lifecycle": "active",
        "statements": statements,
        "mention_ids": [mention.mention_id],
        "lineage_refs": [],
        "missing_data": missing_data if missing_data is not None else [item.model_dump(mode="json") for item in mention.missing_data],
    }
    return EventRecord.model_validate(
        {
            "ref": {"owner": "Events", "object_id": event_id, "revision": 1, "hash": sha256_ref(data)},
            **data,
        }
    )


def _record_for_mentions(mentions: list[Any], event_id: str) -> Any:
    """Materialize a deliberately conflated prior record for split regression."""
    first = mentions[0]
    statements = [
        statement.model_dump(mode="json")
        for mention in mentions
        for statement in mention.statements
    ]
    data = {
        "event_type": first.event_type.model_dump(mode="json"),
        "lifecycle": "active",
        "statements": statements,
        "mention_ids": sorted(mention.mention_id for mention in mentions),
        "lineage_refs": [],
        "missing_data": [],
    }
    return EventRecord.model_validate(
        {
            "ref": {"owner": "Events", "object_id": event_id, "revision": 1, "hash": sha256_ref(data)},
            **data,
        }
    )


def _snapshot(data: dict[str, Any], records: list[Any]) -> Any:
    baseline = _load_json(SHARED_FIXTURES / "events-read.json")["response"]["payload"]["snapshot"]
    return EventSnapshot.model_validate({**baseline, "events": [item.model_dump(mode="json") for item in records]})


def _clone_duplicate(record: Any, event_id: str) -> Any:
    raw = record.model_dump(mode="json")
    raw["ref"]["object_id"] = event_id
    raw["ref"]["hash"] = sha256_ref({key: value for key, value in raw.items() if key != "ref"})
    return EventRecord.model_validate(raw)


def _setup(case_id: str) -> tuple[str, str | None, dict[str, str]]:
    # (snapshot profile, focus source document, per-document perturbations)
    common = ("empty", None, {})
    setups = {
        "same-export-ru-en": ("export", "doc-export-wire-en", {}),
        "same-export-ten-reprints": ("export", "doc-export-reprint-01", {}),
        "same-port-closure-two-sources": ("port", "doc-port-independent", {}),
        "same-export-with-correction": ("export", "doc-export-correction", {}),
        "merge-duplicate-export-records": ("export", "doc-export-official", {}),
        "fire-same-title-north-east": ("empty", "doc-fire-north", {}),
        "split-two-events-one-article": ("empty", "doc-export-multi", {}),
        "company-near-name": ("company", "doc-industry-only", {}),
        "parent-vs-subsidiary": ("parent", "doc-parent-release", {}),
        "supplier-sanction-vs-export-ban": common,
        "same-product-different-country": common,
        "actual-price-vs-forecast": ("empty", "doc-price-fact", {}),
        "rumored-default-not-confirmed": ("empty", "doc-default-rumor", {}),
        "rumored-plant-closure-vs-fire": ("fire", "doc-fire-rumor", {}),
        "old-vs-current-port-closure": ("stale-port", "doc-port-official", {}),
        "cyber-vs-maintenance-stop": common,
        "tax-change-vs-sanction": common,
        "investment-vs-production-stop": common,
        "unknown-date-export": ("export", "doc-export-official", {"doc-export-official": "unknown-date"}),
        "export-product-typo-candidate": ("export", "doc-unrelated-country", {"doc-unrelated-country": "object-typo"}),
        "new-investment-same-company": common,
        "different-fire-facility-alias": common,
        "multi-article-price-and-export": ("export", "doc-export-official", {}),
        "potential-vs-actual-shutdown": ("production", "doc-line-stop", {"doc-line-stop": "hypothetical"}),
        "historical-supplier-change": ("supplier-history", "doc-c-official", {"doc-c-official": "historical-date"}),
        "source-version-correction": ("export", "doc-export-correction", {}),
        "partial-actor-only": ("company", "doc-industry-only", {}),
        "country-name-overlap": common,
        "same-supplier-different-events": ("empty", "doc-default-rumor", {}),
        "no-source-support": ("empty", "doc-archived-unavailable", {"doc-archived-unavailable": "unverified-source"}),
        "repost-not-independent-corroboration": ("export", "doc-export-reprint-01", {}),
        "near-identical-title-different-sites": common,
    }
    return setups.get(case_id, common)


def _records_for_profile(profile: str, data: dict[str, Any]) -> list[Any]:
    if profile == "empty":
        return []
    base_fixture = _load_json(SHARED_FIXTURES / "events-read.json")["response"]["payload"]["snapshot"]["events"]
    if profile == "export":
        export = next(item for item in base_fixture if item["ref"]["object_id"] == "event-export-x-mk7")
        return [EventRecord.model_validate(export)]
    if profile == "fire":
        fire = next(item for item in base_fixture if item["ref"]["object_id"] == "event-fire-north-plant")
        return [EventRecord.model_validate(fire)]
    if profile == "port":
        mention = _make_mention("doc-port-official", data, _doc_refs(data))[0]
        return [_record_for_mention(mention, "event-port-vega-closure")]
    if profile == "stale-port":
        mention = _make_mention("doc-stale-port", data, _doc_refs(data))[0]
        return [_record_for_mention(mention, "event-port-vega-closure-2025")]
    if profile == "production":
        mention = _make_mention("doc-line-stop", data, _doc_refs(data))[0]
        return [_record_for_mention(mention, "event-production-stop-current")]
    if profile == "supplier-history":
        mention = _make_mention("doc-c-history", data, _doc_refs(data))[0]
        return [_record_for_mention(mention, "event-company-c-supplier-change", missing_data=[{"path": "/event/successor_supplier", "reason": "not_provided", "detail": "The successor supplier is not stated in this version."}])]
    if profile == "company":
        mention = _make_mention("doc-industry-only", data, _doc_refs(data))[0]
        raw = mention.model_dump(mode="json")
        raw["actors"] = [_entity(_entities(data), "company-a")]
        raw["statements"][0]["subject"] = _entity(_entities(data), "company-a")
        adjusted = SCHEMA_TYPES["EventMention"].model_validate(raw)
        return [_record_for_mention(adjusted, "event-company-a-business-activity")]
    if profile == "parent":
        mention = _make_mention("doc-parent-release", data, _doc_refs(data))[0]
        raw = mention.model_dump(mode="json")
        raw["actors"] = [_entity(_entities(data), "company-b")]
        raw["statements"][0]["subject"] = _entity(_entities(data), "company-b")
        adjusted = SCHEMA_TYPES["EventMention"].model_validate(raw)
        return [_record_for_mention(adjusted, "event-company-b-investment")]
    raise ValueError(f"Unknown snapshot profile: {profile}")


def build_cases() -> list[dict[str, Any]]:
    data = load_dataset()
    manifest = _load_json(DATASET_DIR / "manifest.json")
    doc_refs = _doc_refs(data)
    evidence = _evidence_records(data, doc_refs)
    cases = []
    for shared_case in data["t09_resolution_cases"]:
        case_id = shared_case["case_id"]
        profile, focus_doc, variants = _setup(case_id)
        document_ids = list(shared_case["input_document_ids"])
        if case_id == "no-source-support":
            document_ids = ["doc-archived-unavailable"]
        mentions = []
        for doc_id in document_ids:
            mentions.extend(_make_mention(doc_id, data, doc_refs, variant=variants.get(doc_id)))
        if case_id == "actual-price-vs-forecast":
            focus_doc = "doc-price-fact"
        if case_id == "same-supplier-different-events":
            focus_doc = "doc-default-rumor"
        if case_id == "no-source-support":
            focus_doc = "doc-archived-unavailable"
        focus_mention_id = next(
            (
                item.mention_id
                for item in mentions
                if focus_doc and any(ref.object_id == focus_doc for ref in item.provenance.source_refs)
            ),
            None,
        )
        if focus_doc and focus_mention_id is None:
            focus_mention_id = next((item.mention_id for item in mentions if item.mention_id.startswith("mention-" + focus_doc.removeprefix("doc-"))), None)
        if not focus_mention_id and mentions:
            focus_mention_id = mentions[0].mention_id

        records = _records_for_profile(profile, data)
        if case_id == "split-two-events-one-article":
            records = [_record_for_mentions(mentions, "event-mixed-article-aggregate")]
        if case_id == "merge-duplicate-export-records":
            records.append(_clone_duplicate(records[0], "event-export-x-mk7-duplicate"))
        # A local mapped event demonstrates distinct station/facility identities
        # even when source headlines are nearly identical.
        snapshot = _snapshot(data, records)
        case_source_ids = {
            ref.object_id
            for mention in mentions
            for ref in mention.provenance.source_refs
        }
        case_source_ids.update(
            ref.object_id
            for record in snapshot.events
            for statement in record.statements
            for ref in statement.provenance.source_refs
        )
        case_evidence = [item for item in evidence if item.source_ref.object_id in case_source_ids]
        local_input = ResolutionInput.model_validate(
            {
                "mentions": [item.model_dump(mode="json") for item in mentions],
                "existing": snapshot.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in case_evidence],
                "policy": {"id": "t09-experimental-policy", "version": "1.0.0", "hash": "sha256:" + "4" * 64},
            }
        )
        case_fixture = {
            "fixture_id": "fixture-t09-" + case_id,
            "version": "1.0.0",
            "origin": "synthetic",
            "description": "Materialized, hand-authored T09 case derived from pinned shared synthetic records.",
            "input_data": {
                "dataset_id": manifest["dataset_id"],
                "dataset_version": manifest["version"],
                "dataset_hash": manifest["data_hash"],
                "document_ids": document_ids,
                "snapshot_profile": profile,
                "focus_mention_id": focus_mention_id,
                "case_variant": variants,
            },
            "expected_properties": shared_case["expected_properties"],
            "provisional_expectation": shared_case["provisional_expectation"],
            "limitations": [
                "Expected action is provisional and not an approved gold label.",
                "Entity/event mentions are hand-authored contract materializations; no model output generated them.",
                "Raw article text is intentionally not passed to the ResolutionInput contract.",
            ],
            "manual_approval": "provisional",
            "request": local_input.model_dump(mode="json"),
        }
        case_fixture["sha256"] = sha256_ref({key: value for key, value in case_fixture.items() if key != "sha256"})
        cases.append(case_fixture)
    return cases


def write_fixture_manifest(path: Path | None = None) -> Path:
    target = path or (ROOT / "spike" / "T09" / "fixtures" / "scenarios-v1.json")
    manifest = {
        "schema": "alfalab.spike.fixture-set/v1",
        "fixture_id": "fixture-set-t09-v1",
        "version": "1.0.0",
        "origin": "synthetic",
        "provenance": "Materialized from the immutable provisional shared dataset version selected by the T09 version/hash/path pins, with deterministic hand-authored event mappings.",
        "dataset_id": "t09-t13-independent-v1",
        "dataset_version": EXPECTED_DATASET_VERSION,
        "dataset_hash": EXPECTED_DATA_HASH,
        "manual_approval": "provisional",
        "limitations": ["No real news/model output was used; case expectations require independent review."],
        "cases": build_cases(),
    }
    manifest["sha256"] = sha256_ref({key: value for key, value in manifest.items() if key != "sha256"})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or (ROOT / "spike" / "T09" / "fixtures" / "scenarios-v1.json")
    raw = _load_json(target)
    digest = sha256_ref({key: value for key, value in raw.items() if key != "sha256"})
    if (
        raw.get("sha256") != digest
        or raw.get("dataset_hash") != EXPECTED_DATA_HASH
        or raw.get("dataset_version") != EXPECTED_DATASET_VERSION
    ):
        raise ValueError("T09 fixture hash or shared data hash failed")
    for case in raw["cases"]:
        digest = sha256_ref({key: value for key, value in case.items() if key != "sha256"})
        if case.get("sha256") != digest:
            raise ValueError(f"T09 case hash failed: {case.get('fixture_id')}")
    return raw["cases"]


def input_from_fixture(case: dict[str, Any]) -> Any:
    return ResolutionInput.model_validate(case["request"])


if __name__ == "__main__":
    print(write_fixture_manifest())
