"""Public operation interfaces owned by Evidence."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import (
    ReadEvidenceInput,
    ReadEvidenceOutput,
    RegisterEvidenceInput,
    RegisterEvidenceOutput,
)

from alfalab.common.protocols import OperationContext, OperationImplementation


class RegisterOperation(OperationImplementation[RegisterEvidenceInput, RegisterEvidenceOutput], Protocol):
    def execute(
        self, payload: RegisterEvidenceInput, context: OperationContext, /
    ) -> RegisterEvidenceOutput: ...


class ReadOperation(OperationImplementation[ReadEvidenceInput, ReadEvidenceOutput], Protocol):
    def execute(self, payload: ReadEvidenceInput, context: OperationContext, /) -> ReadEvidenceOutput: ...


OPERATION_BINDINGS = {
    "Evidence.register": RegisterOperation,
    "Evidence.read": ReadOperation,
}

__all__ = ["RegisterOperation", "ReadOperation", "OPERATION_BINDINGS"]
