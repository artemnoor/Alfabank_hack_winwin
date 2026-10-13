"""Shared composition root for the HTTP and CLI execution adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alfalab.bootstrap.registry import (
    RuntimeRegistry,
    create_runtime_registry,
    repository_root,
)
from alfalab.execution.context import ExecutionLimits
from alfalab.execution.policy import (
    TrustedDataPolicyResolver,
    TrustedSource,
    load_approved_prepare_sources,
)
from alfalab.execution.service import ExecutionService
from alfalab.modules.runs.storage.database import create_runs_engine
from alfalab.modules.runs.storage.memory import InMemoryRunsRepository
from alfalab.modules.runs.storage.postgres import PostgresRunsRepository
from alfalab.modules.runs.storage.repository import RunsRepository


class _UnavailableRunsRepository:
    """Fail-closed adapter used when a development profile lacks local DB config."""

    def write(self, record, /) -> None:
        del record
        raise OSError("Runs history is unavailable")

    def query(
        self, payload, *, tenant_id, sandbox_id, exclude_run_id, include_artifacts
    ):
        del payload, tenant_id, sandbox_id, exclude_run_id, include_artifacts
        raise OSError("Runs history is unavailable")

    def get(self, run_id, *, tenant_id=None, sandbox_id=None):
        del run_id, tenant_id, sandbox_id

    def close(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class ExecutionRuntime:
    registry: RuntimeRegistry
    runs_writer: RunsRepository
    execution_service: ExecutionService
    limits: ExecutionLimits
    runs_repository: RunsRepository

    def close(self) -> None:
        self.runs_repository.close()


def create_execution_runtime(
    environment: str,
    *,
    runs_database_url: str | None = None,
    runs_repository: RunsRepository | None = None,
    trusted_sources: dict[str, TrustedSource] | None = None,
    artifact_root: Path | None = None,
) -> ExecutionRuntime:
    """Build shared operation, trusted policy, repository, and service adapters."""
    limits = ExecutionLimits()
    if runs_repository is not None:
        repository = runs_repository
    elif runs_database_url:
        repository = PostgresRunsRepository(
            create_runs_engine(runs_database_url),
            environment=environment,
            artifact_root=artifact_root or (repository_root() / ".local" / "artifacts"),
        )
    elif environment == "testing":
        repository = InMemoryRunsRepository()
    else:
        repository = _UnavailableRunsRepository()
    registry = create_runtime_registry(environment, repository)
    source_registry = (
        trusted_sources
        if trusted_sources is not None
        else load_approved_prepare_sources(repository_root())
    )
    policy_resolver = TrustedDataPolicyResolver(source_registry)
    execution_service = ExecutionService(
        registry,
        repository,
        environment=environment,
        limits=limits,
        policy_resolver=policy_resolver,
    )
    return ExecutionRuntime(
        registry=registry,
        runs_writer=repository,
        execution_service=execution_service,
        limits=limits,
        runs_repository=repository,
    )
