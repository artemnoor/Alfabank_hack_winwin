"""Public operation interfaces owned by Understanding."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import (
    ClassificationInput,
    ClassificationOutput,
    ExtractionInput,
    ExtractionOutput,
)

from alfalab.common.protocols import OperationContext, OperationImplementation


class ClassifyOperation(OperationImplementation[ClassificationInput, ClassificationOutput], Protocol):
    def execute(
        self, payload: ClassificationInput, context: OperationContext, /
    ) -> ClassificationOutput: ...


class ExtractOperation(OperationImplementation[ExtractionInput, ExtractionOutput], Protocol):
    def execute(self, payload: ExtractionInput, context: OperationContext, /) -> ExtractionOutput: ...


OPERATION_BINDINGS = {
    "Understanding.classify": ClassifyOperation,
    "Understanding.extract": ExtractOperation,
}

__all__ = ["ClassifyOperation", "ExtractOperation", "OPERATION_BINDINGS"]
