"""Hash-verified, server-registered synthetic source fixtures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from alfalab_contracts import RawMaterial
from alfalab_contracts._generated import Language


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class FixtureMaterial:
    material_id: str
    source_id: str
    source_url: str | None
    title: str
    text: str
    published_at: str | None
    language: str
    content_hash: str

    def material_identity(self) -> dict[str, object]:
        return {
            "material_id": self.material_id,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "title": self.title,
            "text": self.text,
            "published_at": self.published_at,
            "language": self.language,
            "content_hash": self.content_hash,
        }

    def matches(self, material: RawMaterial) -> bool:
        return (
            material.model_dump(mode="json", exclude={"collected_at", "provenance"})
            == self.material_identity()
        )


@dataclass(frozen=True, slots=True)
class FixtureSource:
    source_id: str
    dataset_id: str
    version: str
    binding_hash: str
    materials: tuple[FixtureMaterial, ...]


class FixtureSourceCatalog:
    """Immutable runtime registry loaded only from the approved fixture index."""

    def __init__(self, sources: dict[str, FixtureSource] | None = None) -> None:
        self._sources = dict(sources or {})
        self._materials = {
            (material.source_id, material.material_id): material
            for source in self._sources.values()
            for material in source.materials
        }

    def resolve(self, source_id: str) -> FixtureSource | None:
        return self._sources.get(source_id)

    def sources(self) -> dict[str, FixtureSource]:
        return dict(self._sources)

    def matches_material(self, material: RawMaterial) -> bool:
        expected = self._materials.get((material.source_id or "", material.material_id))
        if expected is None or not expected.matches(material):
            return False
        provenance = material.provenance
        return (
            provenance.origin == "synthetic"
            and provenance.origin_verified is True
            and not provenance.source_refs
            and not provenance.input_statement_refs
            and not provenance.evidence_refs
            and provenance.derivation_method is None
        )

    def trusts_content_hash(self, content_hash: str) -> bool:
        return any(
            material.content_hash == content_hash
            for source in self._sources.values()
            for material in source.materials
        )

    def trusted_source_binding(self, material: RawMaterial) -> str | None:
        source = self.resolve(material.source_id or "")
        if source is None or not self.matches_material(material):
            return None
        return source.binding_hash


def load_fixture_source_catalog(repository_root: Path) -> FixtureSourceCatalog:
    """Load sources only when index, review, dataset and material hashes agree."""
    approved_root = (repository_root / "fixtures" / "approved").resolve()
    try:
        index = json.loads((approved_root / "index.json").read_text(encoding="utf-8"))
        if index.get("schema") != "alfalab.approved-fixture-index/v1":
            return FixtureSourceCatalog()
        files = index.get("files")
        datasets = index.get("datasets")
        if not isinstance(files, dict) or not isinstance(datasets, dict):
            return FixtureSourceCatalog()

        def verified_file(relative: object) -> tuple[bytes, Any] | None:
            if not isinstance(relative, str):
                return None
            relative_path = PurePosixPath(relative)
            if (
                relative_path.is_absolute()
                or ".." in relative_path.parts
                or "\\" in relative
            ):
                return None
            resolved = (approved_root / Path(*relative_path.parts)).resolve()
            if not resolved.is_relative_to(approved_root):
                return None
            body = resolved.read_bytes()
            if files.get(relative) != _sha256(body):
                return None
            return body, json.loads(body)

        review_ref = index.get("approval_review_reference")
        review_file = verified_file(
            review_ref.removeprefix("fixtures/approved/")
            if isinstance(review_ref, str)
            else None
        )
        if review_file is None:
            return FixtureSourceCatalog()
        review = review_file[1]
        if (
            not isinstance(review, dict)
            or review.get("decision") != "approved"
            or review.get("quality_gold_approval") is not False
        ):
            return FixtureSourceCatalog()
        review_hash = _sha256(review_file[0])

        sources: dict[str, FixtureSource] = {}
        for dataset_id, indexed in datasets.items():
            if not isinstance(dataset_id, str) or not isinstance(indexed, dict):
                continue
            manifest_file = verified_file(
                str(indexed.get("manifest_path", "")).removeprefix("fixtures/approved/")
            )
            data_file = verified_file(
                str(indexed.get("data_path", "")).removeprefix("fixtures/approved/")
            )
            if manifest_file is None or data_file is None:
                continue
            manifest, data = manifest_file[1], data_file[1]
            if (
                not isinstance(manifest, dict)
                or not isinstance(data, dict)
                or manifest.get("dataset_id") != dataset_id
                or data.get("dataset_id") != dataset_id
                or manifest.get("classification") != "synthetic"
                or data.get("classification") != "synthetic"
                or manifest.get("synthetic_only") is not True
                or data.get("synthetic_only") is not True
                or manifest.get("retention_class") != "approved_fixture"
                or manifest.get("approval_review_reference") != review_ref
                or manifest.get("version") != data.get("version")
                or manifest.get("hashes", {}).get("data") != _sha256(data_file[0])
                or indexed.get("manifest_sha256")
                != hashlib.sha256(manifest_file[0]).hexdigest()
                or indexed.get("data_sha256")
                != hashlib.sha256(data_file[0]).hexdigest()
            ):
                continue
            records = data.get("records")
            rows = records.get("materials") if isinstance(records, dict) else None
            if not isinstance(rows, list):
                continue
            materials: list[FixtureMaterial] = []
            source_ids: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                text = row.get("text")
                material_id = row.get("material_id")
                source_id = row.get("source_id")
                language = row.get("language", "unknown")
                if (
                    not isinstance(text, str)
                    or not isinstance(material_id, str)
                    or not isinstance(source_id, str)
                    or not isinstance(row.get("title"), str)
                    or row.get("content_hash") != _sha256(text.encode("utf-8"))
                ):
                    continue
                try:
                    Language(language)
                except ValueError:
                    continue
                source_ids.add(source_id)
                materials.append(
                    FixtureMaterial(
                        material_id=material_id,
                        source_id=source_id,
                        source_url=row.get("source_url"),
                        title=row["title"],
                        text=text,
                        published_at=row.get("published_at"),
                        language=language,
                        content_hash=row["content_hash"],
                    )
                )
            if len(source_ids) != 1 or not materials:
                continue
            source_id = next(iter(source_ids))
            binding_hash = _sha256(
                json.dumps(
                    {
                        "dataset_id": dataset_id,
                        "manifest_hash": _sha256(manifest_file[0]),
                        "data_hash": _sha256(data_file[0]),
                        "review_hash": review_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            candidate = FixtureSource(
                source_id=source_id,
                dataset_id=dataset_id,
                version=str(data["version"]),
                binding_hash=binding_hash,
                materials=tuple(materials),
            )
            previous = sources.get(source_id)
            if previous is not None and previous != candidate:
                # Ambiguous source IDs fail closed instead of selecting a dataset.
                sources.pop(source_id, None)
                continue
            sources[source_id] = candidate
        return FixtureSourceCatalog(sources)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return FixtureSourceCatalog()
