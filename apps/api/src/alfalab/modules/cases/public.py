"""Public operation interfaces owned by Cases."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import (
    QueryCasesInput,
    QueryCasesOutput,
    SaveCaseInput,
    SaveCaseOutput,
)

from alfalab.common.protocols import OperationContext, OperationImplementation


class SaveOperation(OperationImplementation[SaveCaseInput, SaveCaseOutput], Protocol):
    def execute(self, payload: SaveCaseInput, context: OperationContext, /) -> SaveCaseOutput: ...


class QueryOperation(OperationImplementation[QueryCasesInput, QueryCasesOutput], Protocol):
    def execute(self, payload: QueryCasesInput, context: OperationContext, /) -> QueryCasesOutput: ...


OPERATION_BINDINGS = {
    "Cases.save": SaveOperation,
    "Cases.query": QueryOperation,
}

__all__ = ["SaveOperation", "QueryOperation", "OPERATION_BINDINGS"]
