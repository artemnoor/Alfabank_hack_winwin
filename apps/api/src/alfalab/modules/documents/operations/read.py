"""Typed Documents.read operation adapter."""

from __future__ import annotations

from alfalab_contracts import (
    DocumentResult,
    DocumentSelection,
    ReadDocumentsInput,
    ReadDocumentsOutput,
    ReceiptQuery,
    ReceiptResult,
)

from alfalab.execution.errors import SafeExecutionError

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
        if isinstance(payload.query, DocumentSelection):
            result = context.dependency_gateway.invoke(
                "documents.read.versions", payload.query
            )
            if type(result) is not DocumentResult:
                raise SafeExecutionError(
                    status_code=502,
                    code="DEPENDENCY_FAILED",
                    category="dependency",
                    safe_message="Documents read returned an invalid response.",
                )
            return result
        if isinstance(payload.query, ReceiptQuery):
            result = context.dependency_gateway.invoke(
                "documents.read.receipt", payload.query
            )
            if type(result) is not ReceiptResult:
                raise SafeExecutionError(
                    status_code=502,
                    code="DEPENDENCY_FAILED",
                    category="dependency",
                    safe_message="Documents receipt read returned an invalid response.",
                )
            return result
        raise SafeExecutionError(
            status_code=422,
            code="INVALID_INPUT",
            category="validation",
            safe_message="The Documents.read query is not supported.",
        )
