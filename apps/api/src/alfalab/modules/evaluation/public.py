"""Public operation interfaces owned by Evaluation."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import EvaluationInput, EvaluationOutput

from alfalab.common.protocols import OperationContext, OperationImplementation


class EvaluateOperation(OperationImplementation[EvaluationInput, EvaluationOutput], Protocol):
    def execute(self, payload: EvaluationInput, context: OperationContext, /) -> EvaluationOutput: ...


OPERATION_BINDINGS = {"Evaluation.evaluate": EvaluateOperation}

__all__ = ["EvaluateOperation", "OPERATION_BINDINGS"]
