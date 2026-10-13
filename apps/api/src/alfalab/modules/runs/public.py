"""Public operation interfaces owned by Runs."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import QueryRunsInput, QueryRunsOutput

from alfalab.common.protocols import OperationContext, OperationImplementation


class QueryOperation(OperationImplementation[QueryRunsInput, QueryRunsOutput], Protocol):
    def execute(self, payload: QueryRunsInput, context: OperationContext, /) -> QueryRunsOutput: ...


OPERATION_BINDINGS = {"Runs.query": QueryOperation}

__all__ = ["QueryOperation", "OPERATION_BINDINGS"]
