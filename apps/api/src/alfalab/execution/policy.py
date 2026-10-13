"""Trusted source classification and the pre-write/pre-egress policy gate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from alfalab_contracts import DataPolicyDecision, VersionedRef

TrustedClassification = Literal["synthetic", "public", "closed", "secret"]


@dataclass(frozen=True, slots=True)
class TrustedSource:
    classification: TrustedClassification
    processing_allowed: bool
    egress_allowed: bool
    recording: Literal["full", "metadata_only"]
    export_allowed: bool
    approved_payload_hashes: frozenset[str] = frozenset()
    source_binding_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPolicy:
    decision: DataPolicyDecision
    processing_allowed: bool
    egress_allowed: bool
    full_recording_allowed: bool


class TrustedDataPolicyResolver:
    """Resolve only server-registered sources; ignore caller declarations."""

    def __init__(self, sources: Mapping[str, TrustedSource] | None = None) -> None:
        self._sources = dict(sources or {})

    def resolve(
        self,
        source_id: str | None,
        *,
        payload_hash: str | None = None,
    ) -> ResolvedPolicy:
        source = self._sources.get(source_id or "")
        if source is None:
            return self._decision(
                classification="unknown",
                processing_allowed=True,
                egress_allowed=False,
                recording="metadata_only",
                export_allowed=False,
                reason="UNVERIFIED_SOURCE",
            )
        if (
            source.classification in {"synthetic", "public"}
            and payload_hash not in source.approved_payload_hashes
        ):
            return self._decision(
                classification="unknown",
                processing_allowed=True,
                egress_allowed=False,
                recording="metadata_only",
                export_allowed=False,
                reason="UNVERIFIED_SOURCE_CONTENT",
            )
        if source.classification in {"closed", "secret"}:
            return self._decision(
                classification="unknown",
                processing_allowed=False,
                egress_allowed=False,
                recording="metadata_only",
                export_allowed=False,
                reason="DATA_POLICY_DENIED",
            )
        return self._decision(
            classification=source.classification,
            processing_allowed=source.processing_allowed,
            egress_allowed=source.egress_allowed,
            recording=source.recording,
            export_allowed=source.export_allowed,
            reason="TRUSTED_SOURCE_POLICY",
            policy_binding={
                "source_id": source_id,
                "source_binding_hash": source.source_binding_hash,
                "approved_payload_hash": payload_hash,
            },
        )

    @staticmethod
    def _decision(
        *,
        classification: Literal["synthetic", "public", "unknown"],
        processing_allowed: bool,
        egress_allowed: bool,
        recording: Literal["full", "metadata_only"],
        export_allowed: bool,
        reason: str,
        policy_binding: dict[str, str | None] | None = None,
    ) -> ResolvedPolicy:
        policy_body = {
            "policy": "trusted-source-gate-v1",
            "classification": classification,
            "processing_allowed": processing_allowed,
            "egress_allowed": egress_allowed,
            "recording": recording,
            "export_allowed": export_allowed,
            "reason": reason,
            "policy_binding": policy_binding,
        }
        digest = hashlib.sha256(
            json.dumps(policy_body, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        decision = DataPolicyDecision(
            policy=VersionedRef(
                id="trusted-source-gate-v1",
                version="1.0.0",
                hash="sha256:" + digest,
            ),
            classification=classification,
            processing_allowed=processing_allowed,
            egress_allowed=egress_allowed,
            recording=recording,
            export_allowed=export_allowed,
            reason_codes=[reason],
        )
        full_allowed = (
            classification in {"synthetic", "public"}
            and processing_allowed
            and recording == "full"
        )
        return ResolvedPolicy(
            decision=decision,
            processing_allowed=processing_allowed,
            egress_allowed=egress_allowed,
            full_recording_allowed=full_allowed,
        )


def load_approved_prepare_sources(repository_root: Path) -> dict[str, TrustedSource]:
    """Build a server-only allowlist from hash-indexed, reviewed prepare fixtures.

    The allowlist binds each material ID to exact canonical operation payloads.
    Client ``data_declaration`` and source fields never create trust.
    """
    approved = (repository_root / "fixtures" / "approved").resolve()
    index_path = approved / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if index.get("schema") != "alfalab.approved-fixture-index/v1":
            return {}
        files = index.get("files")
        datasets = index.get("datasets")
        if not isinstance(files, dict) or not isinstance(datasets, dict):
            return {}

        def read_approved(relative: str) -> tuple[Path, bytes, object] | None:
            path_value = PurePosixPath(relative)
            if path_value.is_absolute() or ".." in path_value.parts or "\\" in relative:
                return None
            path = (approved / Path(*path_value.parts)).resolve()
            if not path.is_relative_to(approved):
                return None
            content = path.read_bytes()
            expected = files.get(relative)
            actual = "sha256:" + hashlib.sha256(content).hexdigest()
            if expected != actual:
                return None
            return path, content, json.loads(content)

        review_ref = index.get("approval_review_reference")
        if not isinstance(review_ref, str):
            return {}
        review_row = read_approved(review_ref.removeprefix("fixtures/approved/"))
        if review_row is None:
            return {}
        review = review_row[2]
        if (
            not isinstance(review, dict)
            or review.get("decision") != "approved"
            or review.get("quality_gold_approval") is not False
        ):
            return {}

        verified_materials: dict[str, tuple[str, str, str]] = {}
        for dataset_id, indexed in datasets.items():
            if not isinstance(indexed, dict):
                continue
            manifest_ref = indexed.get("manifest_path")
            data_ref = indexed.get("data_path")
            if not isinstance(manifest_ref, str) or not isinstance(data_ref, str):
                continue
            manifest_row = read_approved(
                manifest_ref.removeprefix("fixtures/approved/")
            )
            data_row = read_approved(data_ref.removeprefix("fixtures/approved/"))
            if manifest_row is None or data_row is None:
                continue
            manifest = manifest_row[2]
            data = data_row[2]
            if (
                not isinstance(manifest, dict)
                or not isinstance(data, dict)
                or manifest.get("dataset_id") != dataset_id
                or manifest.get("classification") != "synthetic"
                or manifest.get("synthetic_only") is not True
                or manifest.get("retention_class") != "approved_fixture"
                or manifest.get("approval_review_reference") != review_ref
                or data.get("dataset_id") != dataset_id
                or data.get("classification") != "synthetic"
                or data.get("synthetic_only") is not True
            ):
                continue
            manifest_hash = hashlib.sha256(manifest_row[1]).hexdigest()
            data_hash = hashlib.sha256(data_row[1]).hexdigest()
            manifest_data_hashes = manifest.get("hashes")
            if (
                indexed.get("manifest_sha256") != manifest_hash
                or indexed.get("data_sha256") != data_hash
                or not isinstance(manifest_data_hashes, dict)
                or manifest_data_hashes.get("data") != "sha256:" + data_hash
                or data.get("version") != manifest.get("version")
            ):
                continue
            records = data.get("records")
            materials = records.get("materials") if isinstance(records, dict) else None
            if not isinstance(materials, list):
                continue
            binding_body = {
                "dataset_id": dataset_id,
                "dataset_manifest_hash": "sha256:" + manifest_hash,
                "dataset_data_hash": "sha256:" + data_hash,
                "review_hash": "sha256:" + hashlib.sha256(review_row[1]).hexdigest(),
            }
            source_binding_hash = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        binding_body, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                ).hexdigest()
            )
            for material in materials:
                if not isinstance(material, dict):
                    continue
                material_id, content_hash, text = (
                    material.get("material_id"),
                    material.get("content_hash"),
                    material.get("text"),
                )
                actual_content_hash = (
                    "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
                    if isinstance(text, str)
                    else None
                )
                if isinstance(material_id, str) and content_hash == actual_content_hash:
                    verified_materials[material_id] = (
                        content_hash,
                        text,
                        source_binding_hash,
                    )

        hashes_by_material: dict[str, set[str]] = {}
        for relative in files:
            if (
                not isinstance(relative, str)
                or not relative.startswith("Documents.prepare/")
                or not relative.endswith("/manifest.json")
            ):
                continue
            manifest_row = read_approved(relative)
            if manifest_row is None:
                continue
            manifest = manifest_row[2]
            if (
                not isinstance(manifest, dict)
                or manifest.get("operation_id") != "Documents.prepare"
                or manifest.get("classification") != "synthetic"
            ):
                continue
            request = manifest.get("request")
            payload = request.get("payload") if isinstance(request, dict) else None
            material = payload.get("material") if isinstance(payload, dict) else None
            if not isinstance(payload, dict) or not isinstance(material, dict):
                continue
            material_id = material.get("material_id")
            approved_material = (
                verified_materials.get(material_id)
                if isinstance(material_id, str)
                else None
            )
            if (
                approved_material is None
                or material.get("content_hash") != approved_material[0]
                or material.get("text") != approved_material[1]
            ):
                continue
            payload_hash = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            )
            hashes_by_material.setdefault(material_id, set()).add(payload_hash)

        return {
            material_id: TrustedSource(
                classification="synthetic",
                processing_allowed=True,
                egress_allowed=False,
                recording="full",
                export_allowed=True,
                approved_payload_hashes=frozenset(payload_hashes),
                source_binding_hash=verified_materials[material_id][2],
            )
            for material_id, payload_hashes in hashes_by_material.items()
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
