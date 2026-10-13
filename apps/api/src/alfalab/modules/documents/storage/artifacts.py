"""Compatibility exports for the shared immutable artifact store."""

from alfalab.common.artifacts import ArtifactStore, StoredArtifact
from alfalab.common.storage_errors import ArtifactIntegrityError

__all__ = ["ArtifactIntegrityError", "ArtifactStore", "StoredArtifact"]
