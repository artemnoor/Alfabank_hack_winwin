"""Public operation interfaces owned by Recommendations."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import RecommendationInput, RecommendationOutput

from alfalab.common.protocols import OperationContext, OperationImplementation


class ProposeOperation(OperationImplementation[RecommendationInput, RecommendationOutput], Protocol):
    def execute(
        self, payload: RecommendationInput, context: OperationContext, /
    ) -> RecommendationOutput: ...


OPERATION_BINDINGS = {"Recommendations.propose": ProposeOperation}

__all__ = ["ProposeOperation", "OPERATION_BINDINGS"]
