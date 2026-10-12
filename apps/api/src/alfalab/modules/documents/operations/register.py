"""Typed Documents.register operation adapter."""

from __future__ import annotations

from alfalab_contracts import RegisterDocumentInput, RegisterDocumentOutput

from ..storage.service import DocumentsStorage
from ..storage.context import OperationContext


class RegisterOperation:
    """Adapt the public operation protocol to Documents-owned storage."""

    def __init__(self, storage: DocumentsStorage) -> None:
        self._storage = storage

    def execute(
        self,
        payload: RegisterDocumentInput,
        context: OperationContext,
        /,
    ) -> RegisterDocumentOutput:
        return self._storage.register(payload, context)
