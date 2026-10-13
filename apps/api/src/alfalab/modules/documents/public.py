"""Public operation interfaces owned by Documents."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import (
    PrepareInput,
    PrepareOutput,
    ReadDocumentsInput,
    ReadDocumentsOutput,
    RegisterDocumentInput,
    RegisterDocumentOutput,
)

from alfalab.common.protocols import OperationContext, OperationImplementation


class PrepareOperation(OperationImplementation[PrepareInput, PrepareOutput], Protocol):
    def execute(self, payload: PrepareInput, context: OperationContext, /) -> PrepareOutput: ...


class RegisterOperation(OperationImplementation[RegisterDocumentInput, RegisterDocumentOutput], Protocol):
    def execute(
        self, payload: RegisterDocumentInput, context: OperationContext, /
    ) -> RegisterDocumentOutput: ...


class ReadOperation(OperationImplementation[ReadDocumentsInput, ReadDocumentsOutput], Protocol):
    def execute(self, payload: ReadDocumentsInput, context: OperationContext, /) -> ReadDocumentsOutput: ...


OPERATION_BINDINGS = {
    "Documents.prepare": PrepareOperation,
    "Documents.register": RegisterOperation,
    "Documents.read": ReadOperation,
}

__all__ = ["PrepareOperation", "RegisterOperation", "ReadOperation", "OPERATION_BINDINGS"]
