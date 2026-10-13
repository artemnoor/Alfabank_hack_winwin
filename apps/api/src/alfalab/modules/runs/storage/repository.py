"""Owner-facing persistence port for scoped execution history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from alfalab_contracts import QueryRunsInput, RunRecord, SpanRecord


@dataclass(frozen=True, slots=True)
class StoredRun:
    tenant_id: str
    sandbox_id: str
    record: RunRecord
    input_hash: str
    started_at: datetime
    updated_at: datetime
    writer_status: Literal["in_progress", "success", "error", "unknown"]

    @property
    def run_id(self) -> str:
        return self.record.run_id

    @property
    def status(self) -> str:
        return self.writer_status

    @property
    def analytical_time(self) -> str:
        return self.record.analytical_time

    @property
    def random_seed(self) -> int:
        return self.record.random_seed

    @property
    def spans(self) -> tuple[SpanRecord, ...]:
        return tuple(self.record.spans)

    @property
    def dependencies(self) -> tuple[object, ...]:
        return tuple(self.record.dependencies)


class RunsRepository(Protocol):
    """Scope-aware Runs owner boundary used by execution and query modules."""

    def write(self, record: StoredRun, /) -> None: ...

    def query(
        self,
        payload: QueryRunsInput,
        *,
        tenant_id: str,
        sandbox_id: str,
        exclude_run_id: str,
        include_artifacts: bool,
    ) -> tuple[list[RunRecord], str | None]: ...

    def get(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        sandbox_id: str | None = None,
    ) -> StoredRun | None: ...

    def close(self) -> None: ...
