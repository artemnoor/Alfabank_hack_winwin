"""Domain clock adapters whose values participate in ordered replay cassettes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter_ns

from alfalab_contracts import DependencyRecord
from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictInt

from alfalab.common.protocols import DomainClockPort
from alfalab.execution.context import OperationContext
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.policy import ResolvedPolicy
from alfalab.execution.recording import artifact_view, canonical_json, hash_text
from alfalab.execution.replay import ReplayCassette
from alfalab.execution.sequence import DependencySequence


class DomainClockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    call_index: StrictInt


class DomainClockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    timestamp: AwareDatetime


class RecordingDomainClock(DomainClockPort):
    """Calls a server clock and records each exact returned domain timestamp."""

    def __init__(
        self,
        *,
        context: OperationContext,
        policy: ResolvedPolicy,
        sequence: DependencySequence,
        on_record: Callable[[DependencyRecord], None],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._context = context
        self._policy = policy
        self._sequence = sequence
        self._on_record = on_record
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        sequence = self._sequence.next()
        request = DomainClockRequest(call_index=sequence)
        request_json = canonical_json(request.model_dump(mode="json"))
        span_id = self._context.trace_recorder.start("clock.domain.now", "dependency")
        started_ns = perf_counter_ns()
        try:
            response = DomainClockResponse(timestamp=self._now())
            response_json = canonical_json(response.model_dump(mode="json"))
            duration_ms = max(0, (perf_counter_ns() - started_ns) // 1_000_000)
            self._on_record(
                DependencyRecord(
                    sequence=sequence,
                    port_id="clock.domain.now",
                    kind="clock",
                    request=artifact_view(
                        artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-request",
                        schema_id=DomainClockRequest.__name__,
                        value_json=request_json,
                        classification=self._policy.decision.classification,
                        include_content=self._policy.full_recording_allowed,
                    ),
                    response=artifact_view(
                        artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-response",
                        schema_id=DomainClockResponse.__name__,
                        value_json=response_json,
                        classification=self._policy.decision.classification,
                        include_content=self._policy.full_recording_allowed,
                    ),
                    error=None,
                    duration_ms=duration_ms,
                    request_hash=hash_text(request_json),
                    substitution="live",
                    original_run_id=None,
                )
            )
        except Exception:
            self._context.trace_recorder.finish(
                span_id,
                status="error",
                safe_detail="Domain clock read failed safely.",
            )
            raise
        self._context.trace_recorder.finish(
            span_id,
            status="success",
            safe_detail="Domain clock value recorded.",
        )
        return response.timestamp


class ReplayDomainClock(DomainClockPort):
    """Returns only a verified timestamp from the source run's clock cassette."""

    def __init__(
        self,
        *,
        context: OperationContext,
        cassette: ReplayCassette,
        sequence: DependencySequence,
    ) -> None:
        self._context = context
        self._cassette = cassette
        self._sequence = sequence

    def now(self) -> datetime:
        sequence = self._sequence.next()
        request = DomainClockRequest(call_index=sequence)
        span_id = self._context.trace_recorder.start(
            "clock.domain.replay", "dependency"
        )
        try:
            response, error, _ = self._cassette.consume(
                sequence=sequence,
                port_id="clock.domain.now",
                kind="clock",
                request=request,
                response_type=DomainClockResponse,
            )
        except SafeExecutionError:
            self._cassette.record_miss(
                sequence=sequence,
                port_id="clock.domain.now",
                kind="clock",
                request=request,
            )
            self._context.trace_recorder.finish(
                span_id,
                status="error",
                safe_detail="Recorded domain clock did not match; replay stopped.",
            )
            raise
        self._context.trace_recorder.finish(
            span_id,
            status="error" if error is not None else "success",
            safe_detail="Recorded domain clock value substituted.",
        )
        if error is not None or not isinstance(response, DomainClockResponse):
            from alfalab.execution.replay import replay_miss

            raise replay_miss()
        return response.timestamp
