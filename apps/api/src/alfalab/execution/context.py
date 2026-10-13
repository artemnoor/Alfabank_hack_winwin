"""Concrete trusted context passed to operation implementations."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event
from typing import Literal, NoReturn, Protocol

from alfalab_contracts import ArtifactRef, ArtifactView, EvidenceRecord, ObjectRef

from alfalab.common.protocols import (
    DomainClockPort,
)
from alfalab.common.protocols import (
    TraceRecorder as SafeTraceRecorder,
)


@dataclass(frozen=True, slots=True)
class TrustedPrincipal:
    """Identity and grants derived from the server-side developer profile."""

    actor_id: str
    tenant_id: str
    role: str
    allowed_sandboxes: frozenset[str]
    permissions: frozenset[str]


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    request_body_bytes: int = 2 * 1024 * 1024
    timeout_ms: int = 30_000
    max_document_chars: int = 200_000
    max_attempts: int = 3

    @property
    def document_codepoints(self) -> int:
        """Compatibility alias for the original T03 operation limit."""
        return self.max_document_chars


@dataclass(frozen=True, slots=True)
class FixedAnalyticalClock:
    """Stable analytical time supplied by the request's execution envelope."""

    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass(frozen=True, slots=True)
class SystemDomainClock:
    """Real domain clock used by direct test contexts without runtime recording."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class TraceRecorder(SafeTraceRecorder, Protocol):
    """Safe metadata-only trace sink used by an operation invocation."""

    def start(self, name: str, kind: str, parent_span_id: str | None = None) -> str: ...

    def finish(self, span_id: str, *, status: str, safe_detail: str) -> None: ...


class ArtifactReader(Protocol):
    """Typed artifact read boundary; no implementation is wired in T03."""

    def read(self, ref: ArtifactRef, /) -> ArtifactView: ...


class EvidenceReader(Protocol):
    """Typed evidence read boundary; no implementation is wired in T03."""

    def read(self, ref: ObjectRef, /) -> EvidenceRecord | None: ...


class DependencyGateway(Protocol):
    """External dependency boundary; Documents.prepare has no egress."""

    def invoke(self, dependency_id: str, request: object, /) -> object: ...


class ContextPortUnavailable(RuntimeError):
    """Raised when an operation asks an unwired T03 context port for data."""


class _DisabledArtifactReader:
    def read(self, ref: ArtifactRef, /) -> NoReturn:
        del ref
        raise ContextPortUnavailable(
            "artifact reads are unavailable in this execution slice"
        )


class _DisabledEvidenceReader:
    def read(self, ref: ObjectRef, /) -> NoReturn:
        del ref
        raise ContextPortUnavailable(
            "evidence reads are unavailable in this execution slice"
        )


class _DisabledDependencyGateway:
    def invoke(self, dependency_id: str, request: object, /) -> NoReturn:
        del dependency_id, request
        raise ContextPortUnavailable(
            "external dependencies are unavailable in this execution slice"
        )


DISABLED_ARTIFACT_READER = _DisabledArtifactReader()
DISABLED_EVIDENCE_READER = _DisabledEvidenceReader()
DISABLED_DEPENDENCY_GATEWAY = _DisabledDependencyGateway()


@dataclass(slots=True)
class OperationContext:
    """Trusted, per-run execution inputs; never constructed from client fields."""

    principal: TrustedPrincipal
    tenant_id: str
    sandbox_id: str
    environment: Literal["development", "testing", "production"]
    run_id: str
    operation_id: str
    request_id: str
    contract_version: str
    idempotency_key: str | None
    implementation_id: str
    implementation_version: str
    implementation_configuration_hash: str
    analytical_clock: FixedAnalyticalClock
    rng: random.Random
    artifact_reader: ArtifactReader
    evidence_reader: EvidenceReader
    dependency_gateway: DependencyGateway
    trace_recorder: TraceRecorder
    cancellation_event: Event
    limits: ExecutionLimits
    domain_clock: DomainClockPort = field(default_factory=SystemDomainClock)
    execution_mode: Literal["live", "replay"] = "live"
    replay_source_sandbox_id: str | None = None

    @property
    def cancelled(self) -> bool:
        return self.cancellation_event.is_set()
