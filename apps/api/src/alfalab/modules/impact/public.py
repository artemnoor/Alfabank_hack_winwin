"""Public operation interfaces owned by Impact."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import ImpactInput, ImpactOutput

from alfalab.common.protocols import OperationContext, OperationImplementation


class AssessOperation(OperationImplementation[ImpactInput, ImpactOutput], Protocol):
    def execute(self, payload: ImpactInput, context: OperationContext, /) -> ImpactOutput: ...


OPERATION_BINDINGS = {"Impact.assess": AssessOperation}

__all__ = ["AssessOperation", "OPERATION_BINDINGS"]
