"""Public operation interface owned by Sources."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import FetchInput, FetchOutput

from alfalab.common.protocols import OperationContext, OperationImplementation


class FetchOperation(OperationImplementation[FetchInput, FetchOutput], Protocol):
    def execute(self, payload: FetchInput, context: OperationContext, /) -> FetchOutput: ...


OPERATION_BINDINGS = {"Sources.fetch": FetchOperation}

__all__ = ["FetchOperation", "OPERATION_BINDINGS"]
