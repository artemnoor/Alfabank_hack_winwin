"""Public operation interfaces owned by Graph."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import (
    BuildGraphInput,
    BuildGraphOutput,
    PublishGraphInput,
    PublishGraphOutput,
    QueryGraphInput,
    QueryGraphOutput,
)

from alfalab.common.protocols import OperationContext, OperationImplementation


class BuildOperation(OperationImplementation[BuildGraphInput, BuildGraphOutput], Protocol):
    def execute(self, payload: BuildGraphInput, context: OperationContext, /) -> BuildGraphOutput: ...


class PublishOperation(OperationImplementation[PublishGraphInput, PublishGraphOutput], Protocol):
    def execute(self, payload: PublishGraphInput, context: OperationContext, /) -> PublishGraphOutput: ...


class QueryOperation(OperationImplementation[QueryGraphInput, QueryGraphOutput], Protocol):
    def execute(self, payload: QueryGraphInput, context: OperationContext, /) -> QueryGraphOutput: ...


OPERATION_BINDINGS = {
    "Graph.build": BuildOperation,
    "Graph.publish": PublishOperation,
    "Graph.query": QueryOperation,
}

__all__ = ["BuildOperation", "PublishOperation", "QueryOperation", "OPERATION_BINDINGS"]
