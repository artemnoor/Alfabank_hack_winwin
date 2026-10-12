"""Typed Documents.read operation adapter."""

from __future__ import annotations

from alfalab_contracts import ReadDocumentsInput, ReadDocumentsOutput

from ..storage.context import OperationContext
from ..storage.service import DocumentsStorage


class ReadOperation:
    """Adapt owner-scoped immutable reads to the public operation protocol."""

    def __init__(self, storage: DocumentsStorage) -> None:
        self._storage = storage

    def execute(
        self,
        payload: ReadDocumentsInput,
        context: OperationContext,
        /,
    ) -> ReadDocumentsOutput:
        return self._storage.read(payload, context)
