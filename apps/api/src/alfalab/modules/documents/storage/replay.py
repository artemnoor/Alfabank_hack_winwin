"""Typed Documents owner state carried by strict replay cassettes."""

from __future__ import annotations

from alfalab_contracts import DocumentVersion, Hash, Identifier, Timestamp
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt


class RegisterBeforeStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    document_id: Identifier
    expected_revision: StrictInt
    idempotency_key: Identifier


class RestorableDocumentVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: DocumentVersion
    semantic_hash: Hash
    published_at: Timestamp | None
    recorded_at: Timestamp


class RegisterBeforeState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    document_id: Identifier
    current_revision: StrictInt
    versions: list[RestorableDocumentVersion]
    replayable: StrictBool
