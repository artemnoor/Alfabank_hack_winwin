"""Documents.prepare typed operation boundary."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import PrepareInput, PrepareOutput

from alfalab.execution.context import OperationContext


class PrepareOperation(Protocol):
    """Operation signature shared by real and mock implementations."""

    def execute(self, payload: PrepareInput, context: OperationContext, /) -> PrepareOutput: ...
