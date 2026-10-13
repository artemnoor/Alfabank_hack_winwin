"""Public operation interfaces owned by Matching."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import MatchingInput, MatchingOutput

from alfalab.common.protocols import OperationContext, OperationImplementation


class MatchOperation(OperationImplementation[MatchingInput, MatchingOutput], Protocol):
    def execute(self, payload: MatchingInput, context: OperationContext, /) -> MatchingOutput: ...


OPERATION_BINDINGS = {"Matching.match": MatchOperation}

__all__ = ["MatchOperation", "OPERATION_BINDINGS"]
