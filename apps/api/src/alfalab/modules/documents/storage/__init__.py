"""Documents owner storage adapters and transaction helpers."""

from .artifacts import ArtifactIntegrityError, ArtifactStore, StoredArtifact
from .canonical import canonical_hash, canonical_json_bytes, sha256_hash
from .context import OwnerCommandContext, TrustedScope
from .errors import (
    ExpectedRevisionConflict,
    IdempotencyConflict,
    ScopeDenied,
)
from .policy import PrincipalScopePolicy, ScopePolicy
from .service import DocumentsStorage
from .transactions import OwnerCommandRunner, OwnerCommandResult

__all__ = [
    "ArtifactIntegrityError",
    "ArtifactStore",
    "canonical_hash",
    "canonical_json_bytes",
    "DocumentsStorage",
    "ExpectedRevisionConflict",
    "IdempotencyConflict",
    "OwnerCommandContext",
    "OwnerCommandResult",
    "OwnerCommandRunner",
    "PrincipalScopePolicy",
    "ScopePolicy",
    "ScopeDenied",
    "StoredArtifact",
    "sha256_hash",
    "TrustedScope",
]
