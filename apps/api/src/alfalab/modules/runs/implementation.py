"""Runs.query operation implementation over the Runs owner port."""

from __future__ import annotations

from alfalab_contracts import QueryRunsInput, QueryRunsOutput

from alfalab.common.protocols import OperationContext
from alfalab.modules.runs.storage.repository import RunsRepository


class QueryRuns:
    def __init__(self, repository: RunsRepository) -> None:
        self._repository = repository

    def execute(
        self, payload: QueryRunsInput, context: OperationContext, /
    ) -> QueryRunsOutput:
        records, next_cursor = self._repository.query(
            payload,
            tenant_id=context.tenant_id,
            sandbox_id=context.sandbox_id,
            exclude_run_id=context.run_id,
            include_artifacts=payload.include_artifacts,
        )
        return QueryRunsOutput(runs=records, next_cursor=next_cursor)
