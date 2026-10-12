"""Shared composition root for the HTTP and CLI execution adapters."""

from __future__ import annotations

from dataclasses import dataclass

from alfalab.bootstrap.registry import RuntimeRegistry, create_runtime_registry
from alfalab.execution.context import ExecutionLimits
from alfalab.execution.recording import RunsWriter
from alfalab.execution.service import ExecutionService


@dataclass(frozen=True, slots=True)
class ExecutionRuntime:
    registry: RuntimeRegistry
    runs_writer: RunsWriter
    execution_service: ExecutionService
    limits: ExecutionLimits


def create_execution_runtime(environment: str) -> ExecutionRuntime:
    """Build the same operation registry, metadata writer and service for each adapter."""
    limits = ExecutionLimits()
    registry = create_runtime_registry(environment)
    runs_writer = RunsWriter()
    execution_service = ExecutionService(
        registry,
        runs_writer,
        environment=environment,
        limits=limits,
    )
    return ExecutionRuntime(
        registry=registry,
        runs_writer=runs_writer,
        execution_service=execution_service,
        limits=limits,
    )
