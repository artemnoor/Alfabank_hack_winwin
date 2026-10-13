"""Strict typed cassette consumption for actual execution replays."""

from __future__ import annotations

import json
from time import perf_counter_ns

from alfalab_contracts import DependencyRecord, ErrorInfo
from pydantic import BaseModel, ValidationError

from alfalab.common.artifacts import verified_artifact_json
from alfalab.common.limits import MAX_ARTIFACT_RESPONSE_BYTES
from alfalab.common.protocols import OperationContext
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.policy import ResolvedPolicy
from alfalab.execution.recording import (
    canonical_json,
    contains_sensitive_data,
    dependency_recording_view,
    hash_text,
)
from alfalab.execution.sequence import DependencySequence


def replay_miss() -> SafeExecutionError:
    return SafeExecutionError(
        status_code=409,
        code="REPLAY_MISS",
        category="replay",
        safe_message="The recorded execution is incomplete or incompatible.",
        outcome="not_applied",
    )


def replay_incompatible() -> SafeExecutionError:
    return SafeExecutionError(
        status_code=409,
        code="REPLAY_INCOMPATIBLE",
        category="replay",
        safe_message="The recorded execution is not compatible with this request.",
        outcome="not_applied",
    )


class ReplayCassette:
    """Consumes a source run's ordered dependency records exactly once."""

    def __init__(
        self,
        *,
        source_run_id: str,
        entries: list[DependencyRecord],
        context: OperationContext,
        policy: ResolvedPolicy,
        sequence: DependencySequence,
        on_record,
    ) -> None:
        self.source_run_id = source_run_id
        self._entries = tuple(entries)
        self._context = context
        self._policy = policy
        self._sequence = sequence
        self._on_record = on_record
        self._index = 0

    def consume(
        self,
        *,
        sequence: int,
        port_id: str,
        kind: str,
        request: BaseModel,
        response_type: type[BaseModel],
        sensitive_values: tuple[str, ...] = (),
    ) -> tuple[BaseModel | None, ErrorInfo | None, int]:
        """Match the next port/attempt/request and write the replay trace row."""
        started_ns = perf_counter_ns()
        if self._index >= len(self._entries):
            raise replay_miss()
        entry = self._entries[self._index]
        request_value = request.model_dump(mode="json")
        if contains_sensitive_data(request_value, sensitive_values):
            raise replay_miss()
        request_json = canonical_json(request_value)
        expected_sequence = sequence
        try:
            actual_saved_request = verified_artifact_json(
                entry.request,
                expected_schema_id=type(request).__name__,
                expected_classification=self._policy.decision.classification,
            )
        except ValueError as exc:
            raise replay_miss() from exc
        if (
            entry.sequence != expected_sequence
            or entry.port_id != port_id
            or entry.kind != kind
            or entry.request.ref.size_bytes > MAX_ARTIFACT_RESPONSE_BYTES
            or entry.request_hash != hash_text(request_json)
            or actual_saved_request != request_json
            or entry.substitution not in {"live", "replay"}
        ):
            raise replay_miss()
        if contains_sensitive_data(json.loads(actual_saved_request), sensitive_values):
            raise replay_miss()

        response: BaseModel | None = None
        if entry.error is None:
            if entry.response is None:
                raise replay_miss()
            try:
                response_json = verified_artifact_json(
                    entry.response,
                    expected_schema_id=response_type.__name__,
                    expected_classification=self._policy.decision.classification,
                )
                response = response_type.model_validate_json(response_json, strict=True)
            except (ValueError, ValidationError) as exc:
                raise replay_miss() from exc
            if type(response) is not response_type:
                raise replay_miss()
            if contains_sensitive_data(
                response.model_dump(mode="json"), sensitive_values
            ):
                raise replay_miss()
        elif entry.response is not None or (
            entry.error.dependency_id != port_id
            or entry.error.category != "dependency"
            or entry.error.code != "DEPENDENCY_FAILED"
            or entry.error.outcome not in {"unknown", "not_applied"}
        ):
            raise replay_miss()

        elapsed_ms = max(0, (perf_counter_ns() - started_ns) // 1_000_000)
        replay_request, safe_request_json, _ = dependency_recording_view(
            artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-request",
            schema_id=type(request).__name__,
            value=request_value,
            classification=self._policy.decision.classification,
            include_content=self._policy.full_recording_allowed,
            sensitive_values=sensitive_values,
        )
        replay_response = None
        if response is not None:
            replay_response, _, _ = dependency_recording_view(
                artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-response",
                schema_id=response_type.__name__,
                value=response.model_dump(mode="json"),
                classification=self._policy.decision.classification,
                include_content=self._policy.full_recording_allowed,
                sensitive_values=sensitive_values,
            )
        recorded_error = (
            ErrorInfo(
                code=entry.error.code,
                category=entry.error.category,
                retryable=entry.error.retryable,
                safe_message="The recorded dependency attempt failed.",
                field_paths=[],
                dependency_id=port_id,
                outcome=entry.error.outcome,
            )
            if entry.error is not None
            else None
        )
        self._on_record(
            DependencyRecord(
                sequence=sequence,
                port_id=port_id,
                kind=kind,
                request=replay_request,
                response=replay_response,
                error=recorded_error,
                duration_ms=elapsed_ms,
                request_hash=hash_text(safe_request_json),
                substitution="replay",
                original_run_id=self.source_run_id,
            )
        )
        self._index += 1
        return response, recorded_error, elapsed_ms

    def record_miss(
        self,
        *,
        sequence: int,
        port_id: str,
        kind: str,
        request: BaseModel,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        """Record a safe failed attempt without copying mismatched source data."""
        request_view, safe_request_json, _ = dependency_recording_view(
            artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-request",
            schema_id=type(request).__name__,
            value=request.model_dump(mode="json"),
            classification=self._policy.decision.classification,
            include_content=self._policy.full_recording_allowed,
            sensitive_values=sensitive_values,
        )
        self._on_record(
            DependencyRecord(
                sequence=sequence,
                port_id=port_id,
                kind=kind,
                request=request_view,
                response=None,
                error=ErrorInfo(
                    code="REPLAY_MISS",
                    category="replay",
                    retryable=False,
                    safe_message="The recorded dependency does not match this request.",
                    field_paths=[],
                    dependency_id=port_id,
                    outcome="not_applied",
                ),
                duration_ms=0,
                request_hash=hash_text(safe_request_json),
                substitution="replay",
                original_run_id=self.source_run_id,
            )
        )

    def assert_consumed(self) -> None:
        if self._index != len(self._entries):
            raise replay_miss()


class ReplayDependencyGateway:
    """Gateway replacement that has no live adapter or network fallback."""

    def __init__(
        self,
        *,
        definitions: dict,
        declared_ids: frozenset[str],
        context: OperationContext,
        cassette: ReplayCassette,
        sequence: DependencySequence,
        on_record,
    ) -> None:
        self._definitions = definitions
        self._declared_ids = declared_ids
        self._context = context
        self._cassette = cassette
        self._sequence = sequence
        self._on_record = on_record

    def invoke(self, dependency_id: str, request: object, /) -> object:
        definition = self._definitions.get(dependency_id)
        if definition is None or dependency_id not in self._declared_ids:
            raise SafeExecutionError(
                status_code=403,
                code="ACCESS_DENIED",
                category="access",
                safe_message="The operation requested an undeclared dependency.",
            )
        if type(request) is not definition.request_type:
            raise SafeExecutionError(
                status_code=422,
                code="INVALID_INPUT",
                category="validation",
                safe_message="The dependency request does not match its registered contract.",
            )
        if (
            definition.sensitive_values is None
            or not definition.secret_inventory_complete
        ):
            raise replay_miss()
        if definition.kind == "model" and (
            definition.model_identity is None
            or definition.model_identity.provider_revision is None
            or definition.model_identity.unknown_revision_reason is not None
        ):
            raise replay_miss()
        attempt_limit = max(
            1, min(definition.max_attempts, self._context.limits.max_attempts)
        )
        for attempt in range(attempt_limit):
            sequence = self._sequence.next()
            span_id = self._context.trace_recorder.start(
                f"dependency.{dependency_id}.replay-attempt-{attempt + 1}",
                "dependency",
            )
            try:
                response, error, _ = self._cassette.consume(
                    sequence=sequence,
                    port_id=dependency_id,
                    kind=definition.kind,
                    request=request,
                    response_type=definition.response_type,
                    sensitive_values=definition.sensitive_values,
                )
            except SafeExecutionError:
                sensitive_values = definition.sensitive_values or ()
                self._cassette.record_miss(
                    sequence=sequence,
                    port_id=dependency_id,
                    kind=definition.kind,
                    request=request,
                    sensitive_values=sensitive_values,
                )
                self._context.trace_recorder.finish(
                    span_id,
                    status="error",
                    safe_detail="Recorded dependency did not match; replay stopped.",
                )
                raise
            self._context.trace_recorder.finish(
                span_id,
                status="error" if error is not None else "success",
                safe_detail=(
                    "Recorded dependency error was substituted."
                    if error is not None
                    else "Recorded dependency response was substituted."
                ),
            )
            if error is not None:
                if error.retryable and attempt + 1 < attempt_limit:
                    continue
                raise SafeExecutionError(
                    status_code=502,
                    code="DEPENDENCY_FAILED",
                    category="dependency",
                    safe_message="The recorded dependency attempt failed.",
                    retryable=error.retryable,
                    outcome=error.outcome,
                )
            return response
        raise replay_miss()


def cassette_replayable(
    entries: list[DependencyRecord],
    sensitive_values_by_port: dict[str, tuple[str, ...] | None] | None = None,
) -> bool:
    """Return false for cassettes without complete, sequence-stable inputs."""
    registered_sensitive_values = sensitive_values_by_port or {}
    seen: set[int] = set()
    for expected, entry in enumerate(entries):
        if sensitive_values_by_port is not None and (
            entry.port_id not in registered_sensitive_values
            or registered_sensitive_values[entry.port_id] is None
        ):
            return False
        if entry.sequence != expected or entry.sequence in seen:
            return False
        seen.add(entry.sequence)
        if (
            entry.request.content_json is None
            or entry.request.availability != "available"
        ):
            return False
        try:
            if contains_sensitive_data(
                json.loads(entry.request.content_json),
                registered_sensitive_values.get(entry.port_id) or (),
            ):
                return False
        except (json.JSONDecodeError, TypeError):
            return False
        if entry.error is None:
            if entry.response is None or entry.response.content_json is None:
                return False
            try:
                if contains_sensitive_data(
                    json.loads(entry.response.content_json),
                    registered_sensitive_values.get(entry.port_id) or (),
                ):
                    return False
            except (json.JSONDecodeError, TypeError):
                return False
        elif entry.response is not None:
            return False
        if entry.kind == "owner_read":
            # The recorded owner-read bundle needs its own operation-specific adapter.
            return False
    return True
