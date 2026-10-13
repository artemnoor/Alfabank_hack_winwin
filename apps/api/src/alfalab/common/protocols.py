"""Shared structural interfaces for operation implementations.

These interfaces contain no transport, persistence, or concrete execution code.
They deliberately depend only on Python's standard library and public DTOs.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

from alfalab_contracts import ArtifactRef, ArtifactView, EvidenceRecord, ObjectRef


@runtime_checkable
class TrustedPrincipal(Protocol):
    """Server-authenticated caller identity supplied by the composition root."""

    @property
    def actor_id(self) -> str: ...

    @property
    def tenant_id(self) -> str: ...

    @property
    def role(self) -> str: ...

    @property
    def allowed_sandboxes(self) -> frozenset[str]: ...

    @property
    def permissions(self) -> frozenset[str]: ...


@runtime_checkable
class AnalyticalClock(Protocol):
    """Deterministic domain time; wall-clock telemetry is kept separately."""

    def now(self) -> datetime: ...


@runtime_checkable
class RandomSource(Protocol):
    """Seeded random source provided by the execution context."""

    def getrandbits(self, bit_count: int, /) -> int: ...


@runtime_checkable
class ArtifactReadPort(Protocol):
    """Read-only access to an artifact after scope and hash verification."""

    def read(self, ref: ArtifactRef, /) -> ArtifactView: ...


@runtime_checkable
class EvidenceReadPort(Protocol):
    """Read-only access to evidence records through the Evidence owner."""

    def read(self, ref: ObjectRef, /) -> EvidenceRecord | None: ...


@runtime_checkable
class DependencyGateway(Protocol):
    """Controlled adapter boundary for declared external dependencies."""

    def invoke(self, dependency_id: str, request: object, /) -> object: ...


@runtime_checkable
class TraceRecorder(Protocol):
    """Recorder accepts only explicitly safe metadata from operation code."""

    def record_safe_event(
        self,
        event_name: str,
        attributes: Mapping[str, str | int | float | bool | None],
        /,
    ) -> None: ...


@runtime_checkable
class ExecutionLimits(Protocol):
    """Resolved server-side limits for one operation invocation."""

    @property
    def timeout_ms(self) -> int: ...

    @property
    def max_document_chars(self) -> int: ...

    @property
    def max_attempts(self) -> int: ...


@runtime_checkable
class OperationContext(Protocol):
    """Trusted server-built dependencies passed to an operation core.

    ``tenant_id`` is copied from the authenticated principal and
    ``sandbox_id`` is an authorized server-side selection. Neither value is
    trusted when it appears in client JSON.
    """

    @property
    def principal(self) -> TrustedPrincipal: ...

    @property
    def operation_id(self) -> str: ...

    @property
    def request_id(self) -> str: ...

    @property
    def contract_version(self) -> str: ...

    @property
    def implementation_id(self) -> str: ...

    @property
    def implementation_version(self) -> str: ...

    @property
    def implementation_configuration_hash(self) -> str: ...

    @property
    def idempotency_key(self) -> str | None: ...

    @property
    def tenant_id(self) -> str: ...

    @property
    def sandbox_id(self) -> str: ...

    @property
    def environment(self) -> str: ...

    @property
    def run_id(self) -> str: ...

    @property
    def analytical_clock(self) -> AnalyticalClock: ...

    @property
    def rng(self) -> RandomSource: ...

    @property
    def artifact_reader(self) -> ArtifactReadPort: ...

    @property
    def evidence_reader(self) -> EvidenceReadPort: ...

    @property
    def dependency_gateway(self) -> DependencyGateway: ...

    @property
    def trace_recorder(self) -> TraceRecorder: ...

    @property
    def cancelled(self) -> bool: ...

    @property
    def limits(self) -> ExecutionLimits: ...


@runtime_checkable
class OperationImplementation[InputT_contra, OutputT_co](Protocol):
    """Typed operation port: payload plus trusted context produces typed output."""

    def execute(
        self, payload: InputT_contra, context: OperationContext, /
    ) -> OutputT_co: ...


class TrustedContextError(ValueError):
    """Raised when server context scope disagrees with its authenticated principal."""


def validate_trusted_scope(context: OperationContext) -> None:
    """Check duplicated context scope before an operation receives it."""
    principal = context.principal
    if context.tenant_id != principal.tenant_id:
        raise TrustedContextError(
            "operation tenant does not match authenticated principal"
        )
    if context.sandbox_id not in principal.allowed_sandboxes:
        raise TrustedContextError(
            "operation sandbox is not authorized for authenticated principal"
        )


__all__ = [
    "AnalyticalClock",
    "ArtifactReadPort",
    "DependencyGateway",
    "EvidenceReadPort",
    "ExecutionLimits",
    "OperationContext",
    "OperationImplementation",
    "RandomSource",
    "TraceRecorder",
    "TrustedContextError",
    "TrustedPrincipal",
    "validate_trusted_scope",
]
