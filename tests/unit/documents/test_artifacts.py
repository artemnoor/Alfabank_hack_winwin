from __future__ import annotations

import json

import pytest
from alfalab.modules.documents.storage.artifacts import (
    ArtifactIntegrityError,
    ArtifactStore,
)
from alfalab.modules.documents.storage.canonical import canonical_hash
from alfalab.modules.documents.storage.context import TrustedScope


def test_artifact_is_scoped_content_addressed_and_verified(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    scope = TrustedScope("tenant-a", "sandbox-a", "testing")
    artifact = store.put_json(
        scope,
        {"text": "Альфа", "revision": 1},
        schema_id="DocumentsTestPayload",
        schema_version="1.0.0",
    )

    assert artifact.artifact_ref.hash == canonical_hash(
        {"text": "Альфа", "revision": 1}
    )
    assert artifact.artifact_ref.hash.startswith("sha256:")
    assert artifact.artifact_ref.classification == "unknown"
    assert json.loads(store.read_json(scope, artifact.artifact_ref.hash)) == {
        "revision": 1,
        "text": "Альфа",
    }
    with pytest.raises(ArtifactIntegrityError):
        store.read_json(
            TrustedScope("tenant-b", "sandbox-a", "testing"), artifact.artifact_ref.hash
        )


def test_artifact_does_not_overwrite_a_tampered_content_address(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    scope = TrustedScope("tenant-a", "sandbox-a", "testing")
    artifact = store.put_json(
        scope,
        {"revision": 1},
        schema_id="DocumentsTestPayload",
        schema_version="1.0.0",
    )
    path = tmp_path / "artifacts" / artifact.relative_key
    path.write_bytes(b'{"revision":2}')

    with pytest.raises(ArtifactIntegrityError):
        store.put_json(
            scope,
            {"revision": 1},
            schema_id="DocumentsTestPayload",
            schema_version="1.0.0",
        )
    with pytest.raises(ArtifactIntegrityError):
        store.read_json(scope, artifact.artifact_ref.hash)


def test_artifact_read_stops_at_the_trusted_expected_size(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    scope = TrustedScope("tenant-a", "sandbox-a", "testing")
    artifact = store.put_json(
        scope,
        {"revision": 1},
        schema_id="DocumentsTestPayload",
        schema_version="1.0.0",
    )
    path = tmp_path / "artifacts" / artifact.relative_key
    path.write_bytes(b"x" * 1_000_000)

    with pytest.raises(ArtifactIntegrityError, match="expected size"):
        store.read_json(
            scope,
            artifact.artifact_ref.hash,
            expected_size_bytes=artifact.artifact_ref.size_bytes,
        )
