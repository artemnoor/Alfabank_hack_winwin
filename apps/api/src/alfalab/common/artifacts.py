"""Scoped, immutable, content-addressed local artifacts shared by owner modules."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alfalab_contracts import ArtifactRef, ArtifactView

from alfalab.common.canonical import canonical_json_bytes, sha256_hash
from alfalab.common.limits import MAX_ARTIFACT_RESPONSE_BYTES
from alfalab.common.scope import TrustedScope, validate_scope
from alfalab.common.storage_errors import ArtifactIntegrityError

ARTIFACT_SCHEMA_VERSION = "1.0.0"


def verified_artifact_json(
    view: ArtifactView,
    *,
    expected_schema_id: str,
    expected_classification: str,
) -> str:
    """Check an artifact view's contract, canonical bytes, size, and digest."""
    content = view.content_json
    raw = content.encode("utf-8") if content is not None else b""
    if (
        content is None
        or view.availability != "available"
        or view.ref.schema_id != expected_schema_id
        or view.ref.schema_version != ARTIFACT_SCHEMA_VERSION
        or view.ref.media_type != "application/json"
        or view.ref.classification != expected_classification
        or view.ref.size_bytes != len(raw)
        or len(raw) > MAX_ARTIFACT_RESPONSE_BYTES
        or view.ref.hash != sha256_hash(raw)
    ):
        raise ValueError("recorded artifact is unavailable or incompatible")
    try:
        value = json.loads(content)
        canonical = canonical_json_bytes(value).decode("utf-8")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(
            "recorded artifact is malformed or not canonical JSON"
        ) from exc
    if canonical != content:
        raise ValueError("recorded artifact is not canonical JSON")
    return content


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """A verified artifact reference plus its safe storage key."""

    artifact_ref: ArtifactRef
    relative_key: str


class ArtifactStore:
    """Write and verify JSON artifacts under a tenant/sandbox scoped root."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def put_json(
        self,
        scope: TrustedScope,
        value: Any,
        *,
        schema_id: str,
        schema_version: str,
        classification: str = "unknown",
    ) -> StoredArtifact:
        validate_scope(scope)
        encoded = canonical_json_bytes(value)
        digest = sha256_hash(encoded)
        filename = f"{digest.removeprefix('sha256:')}.json"
        relative = Path(scope.environment, scope.tenant_id, scope.sandbox_id, filename)
        target = self._safe_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        directory = target.parent
        while True:
            _set_private_directory(directory)
            if directory == self._root:
                break
            directory = directory.parent

        fd, temporary_name = tempfile.mkstemp(
            prefix=".artifact-", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError:
                if target.read_bytes() != encoded:
                    raise ArtifactIntegrityError(
                        "existing immutable artifact failed hash verification"
                    )
            _sync_directory(target.parent)
        except OSError as exc:
            raise ArtifactIntegrityError(
                "artifact could not be atomically published"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)

        reference = ArtifactRef(
            artifact_id=digest,
            hash=digest,
            schema_id=schema_id,
            schema_version=schema_version,
            size_bytes=len(encoded),
            classification=classification,
            media_type="application/json",
        )
        return StoredArtifact(reference, relative.as_posix())

    def read_json(
        self,
        scope: TrustedScope,
        artifact_hash: str,
        *,
        expected_size_bytes: int | None = None,
    ) -> bytes:
        """Read bytes only after verifying scope, filename, and content hash."""

        validate_scope(scope)
        if not _is_hash(artifact_hash):
            raise ArtifactIntegrityError("invalid artifact hash reference")
        if expected_size_bytes is not None and (
            type(expected_size_bytes) is not int or expected_size_bytes < 0
        ):
            raise ArtifactIntegrityError("invalid expected artifact size")
        filename = f"{artifact_hash.removeprefix('sha256:')}.json"
        path = self._safe_path(
            Path(scope.environment, scope.tenant_id, scope.sandbox_id, filename)
        )
        try:
            with path.open("rb") as source:
                content = source.read(
                    expected_size_bytes + 1 if expected_size_bytes is not None else -1
                )
        except OSError as exc:
            raise ArtifactIntegrityError(
                "artifact is unavailable in the trusted scope"
            ) from exc
        if expected_size_bytes is not None and len(content) > expected_size_bytes:
            raise ArtifactIntegrityError("artifact exceeds its expected size")
        if sha256_hash(content) != artifact_hash:
            raise ArtifactIntegrityError("artifact content hash verification failed")
        return content

    def _safe_path(self, relative: Path) -> Path:
        candidate = (self._root / relative).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(
                "artifact key escapes the configured storage root"
            ) from exc
        return candidate


def _is_hash(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _set_private_directory(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
