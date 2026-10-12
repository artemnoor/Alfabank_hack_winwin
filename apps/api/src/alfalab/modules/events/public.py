"""Public operation interfaces owned by Events."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import (
    ApplyEventsInput,
    ApplyEventsOutput,
    ReadEventsInput,
    ReadEventsOutput,
    ResolutionInput,
    ResolutionOutput,
)

from alfalab.common.protocols import OperationContext, OperationImplementation


class ProposeResolutionOperation(OperationImplementation[ResolutionInput, ResolutionOutput], Protocol):
    def execute(self, payload: ResolutionInput, context: OperationContext, /) -> ResolutionOutput: ...


class ApplyOperation(OperationImplementation[ApplyEventsInput, ApplyEventsOutput], Protocol):
    def execute(self, payload: ApplyEventsInput, context: OperationContext, /) -> ApplyEventsOutput: ...


class ReadOperation(OperationImplementation[ReadEventsInput, ReadEventsOutput], Protocol):
    def execute(self, payload: ReadEventsInput, context: OperationContext, /) -> ReadEventsOutput: ...


OPERATION_BINDINGS = {
    "Events.propose_resolution": ProposeResolutionOperation,
    "Events.apply": ApplyOperation,
    "Events.read": ReadOperation,
}

__all__ = ["ProposeResolutionOperation", "ApplyOperation", "ReadOperation", "OPERATION_BINDINGS"]
