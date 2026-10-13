"""Declared-only dependency gateway with policy, attempt, and trace recording."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter_ns, sleep

from alfalab_contracts import DependencyRecord, ErrorInfo, ModelIdentity
from pydantic import BaseModel

from alfalab.common.limits import MAX_ARTIFACT_RESPONSE_BYTES
from alfalab.common.protocols import OperationContext
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.policy import ResolvedPolicy
from alfalab.execution.recording import (
    artifact_view,
    canonical_json,
    contains_sensitive_data,
    dependency_recording_view,
    hash_text,
)
from alfalab.execution.sequence import DependencySequence


@dataclass(frozen=True, slots=True)
class DependencyDefinition:
    dependency_id: str
    kind: str
    request_type: type[BaseModel]
    response_type: type[BaseModel]
    invoke: Callable[[BaseModel, OperationContext], BaseModel]
    max_attempts: int = 1
    sensitive_values: tuple[str, ...] | None = field(default=None, repr=False)
    # Set only by the server registry after confirming its secret inventory is exhaustive.
    secret_inventory_complete: bool = False
    model_identity: ModelIdentity | None = None


class ControlledDependencyGateway:
    """Resolve calls from a server registry; callers never provide URLs or secrets."""

    def __init__(
        self,
        *,
        definitions: dict[str, DependencyDefinition],
        declared_ids: frozenset[str],
        context: OperationContext,
        policy: ResolvedPolicy,
        on_record: Callable[[DependencyRecord], None],
        sleep_fn: Callable[[float], None] = sleep,
        sequence: DependencySequence | None = None,
    ) -> None:
        self._definitions = definitions
        self._declared_ids = declared_ids
        self._context = context
        self._policy = policy
        self._on_record = on_record
        self._sleep = sleep_fn
        self._sequence = sequence or DependencySequence()

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
        request_value = request.model_dump(mode="json")
        sensitive_values = definition.sensitive_values or ()
        if contains_sensitive_data(request_value, sensitive_values):
            self._record_denied(definition, reason="sensitive-request")
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The active data policy denied this dependency attempt.",
            )
        if not self._policy.egress_allowed:
            self._record_denied(definition, reason="egress-denied")
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The active data policy does not allow external dependency access.",
            )
        if (
            definition.sensitive_values is None
            or not definition.secret_inventory_complete
        ):
            self._record_denied(definition, reason="unregistered-secret-policy")
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The active data policy denied this dependency attempt.",
            )
        if definition.kind == "model" and definition.model_identity is None:
            self._record_denied(definition, reason="unregistered-model-identity")
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The active data policy denied this dependency attempt.",
            )

        request_json = canonical_json(request_value)
        request_bytes = request_json.encode("utf-8")
        if len(request_bytes) > MAX_ARTIFACT_RESPONSE_BYTES:
            raise SafeExecutionError(
                status_code=429,
                code="LIMIT_EXCEEDED",
                category="validation",
                safe_message="The dependency request exceeds the configured size limit.",
            )
        attempt_limit = max(
            1, min(definition.max_attempts, self._context.limits.max_attempts)
        )
        last_error: SafeExecutionError | None = None
        for attempt in range(attempt_limit):
            sequence = self._sequence.next()
            request_view, recorded_request_json, _ = dependency_recording_view(
                artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-request",
                schema_id=definition.request_type.__name__,
                value=request_value,
                classification=self._policy.decision.classification,
                include_content=self._policy.full_recording_allowed,
                sensitive_values=sensitive_values,
            )
            request_hash = hash_text(recorded_request_json)
            span_id = self._context.trace_recorder.start(
                f"dependency.{dependency_id}.attempt-{attempt + 1}",
                "dependency",
            )
            started_ns = perf_counter_ns()
            try:
                response = definition.invoke(request, self._context)
                if type(response) is not definition.response_type:
                    raise SafeExecutionError(
                        status_code=502,
                        code="DEPENDENCY_FAILED",
                        category="dependency",
                        safe_message="The declared dependency returned an invalid response.",
                        outcome="unknown",
                    )
                elapsed_ms = max(0, (perf_counter_ns() - started_ns) // 1_000_000)
                response_json = canonical_json(response.model_dump(mode="json"))
                if len(response_json.encode("utf-8")) > MAX_ARTIFACT_RESPONSE_BYTES:
                    raise SafeExecutionError(
                        status_code=502,
                        code="DEPENDENCY_FAILED",
                        category="dependency",
                        safe_message="The declared dependency returned an oversized response.",
                        outcome="unknown",
                    )
                response_value = response.model_dump(mode="json")
                response_view, _, response_has_sensitive_data = (
                    dependency_recording_view(
                        artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-response",
                        schema_id=definition.response_type.__name__,
                        value=response_value,
                        classification=self._policy.decision.classification,
                        include_content=self._policy.full_recording_allowed,
                        sensitive_values=sensitive_values,
                    )
                )
                if response_has_sensitive_data:
                    raise SafeExecutionError(
                        status_code=502,
                        code="DEPENDENCY_FAILED",
                        category="dependency",
                        safe_message="The declared dependency returned data that cannot be safely exposed.",
                        outcome="unknown",
                    )
                self._context.trace_recorder.finish(
                    span_id,
                    status="success",
                    safe_detail="Dependency attempt completed.",
                )
                self._on_record(
                    DependencyRecord(
                        sequence=sequence,
                        port_id=dependency_id,
                        kind=definition.kind,
                        request=request_view,
                        response=response_view,
                        error=None,
                        duration_ms=elapsed_ms,
                        request_hash=request_hash,
                        substitution="live",
                        original_run_id=None,
                    )
                )
                return response
            except SafeExecutionError as exc:
                elapsed_ms = max(0, (perf_counter_ns() - started_ns) // 1_000_000)
                last_error = exc
                retry = exc.retryable and attempt + 1 < attempt_limit
                self._context.trace_recorder.finish(
                    span_id,
                    status="error",
                    safe_detail="Dependency attempt failed safely.",
                )
                safe_error = ErrorInfo(
                    code="DEPENDENCY_FAILED",
                    category="dependency",
                    retryable=exc.retryable,
                    safe_message="The declared dependency could not be completed.",
                    field_paths=[],
                    dependency_id=dependency_id,
                    outcome="unknown" if exc.outcome == "unknown" else "not_applied",
                )
                self._on_record(
                    DependencyRecord(
                        sequence=sequence,
                        port_id=dependency_id,
                        kind=definition.kind,
                        request=request_view,
                        response=None,
                        error=safe_error,
                        duration_ms=elapsed_ms,
                        request_hash=request_hash,
                        substitution="live",
                        original_run_id=None,
                    )
                )
                if not retry:
                    break
                self._sleep((0.1, 0.5, 1.0)[min(attempt, 2)])
            except Exception as exc:
                elapsed_ms = max(0, (perf_counter_ns() - started_ns) // 1_000_000)
                self._context.trace_recorder.finish(
                    span_id,
                    status="error",
                    safe_detail="Dependency attempt failed safely.",
                )
                self._on_record(
                    DependencyRecord(
                        sequence=sequence,
                        port_id=dependency_id,
                        kind=definition.kind,
                        request=request_view,
                        response=None,
                        error=ErrorInfo(
                            code="DEPENDENCY_FAILED",
                            category="dependency",
                            retryable=False,
                            safe_message="The declared dependency could not be completed.",
                            field_paths=[],
                            dependency_id=dependency_id,
                            outcome="unknown",
                        ),
                        duration_ms=elapsed_ms,
                        request_hash=request_hash,
                        substitution="live",
                        original_run_id=None,
                    )
                )
                raise SafeExecutionError(
                    status_code=502,
                    code="DEPENDENCY_FAILED",
                    category="dependency",
                    safe_message="The declared dependency could not be completed.",
                    outcome="unknown",
                ) from exc
        raise SafeExecutionError(
            status_code=502,
            code="DEPENDENCY_FAILED",
            category="dependency",
            safe_message="The declared dependency could not be completed.",
            retryable=bool(last_error and last_error.retryable),
            outcome=(
                "unknown"
                if last_error is not None and last_error.outcome == "unknown"
                else "not_applied"
            ),
        ) from last_error

    def _record_denied(self, definition: DependencyDefinition, *, reason: str) -> None:
        sequence = self._sequence.next()
        span_id = self._context.trace_recorder.start(
            f"dependency.{definition.dependency_id}.attempt-1",
            "dependency",
        )
        started_ns = perf_counter_ns()
        marker = canonical_json(
            {"policy": reason, "dependency_id": definition.dependency_id}
        )
        view = artifact_view(
            artifact_id=f"artifact-{self._context.run_id}-dep-{sequence}-request",
            schema_id="PolicyDeniedDependencyRequest",
            value_json=marker,
            classification=self._policy.decision.classification,
            include_content=False,
            availability="policy_denied",
        )
        self._on_record(
            DependencyRecord(
                sequence=sequence,
                port_id=definition.dependency_id,
                kind=definition.kind,
                request=view,
                response=None,
                error=ErrorInfo(
                    code="DATA_POLICY_DENIED",
                    category="policy",
                    retryable=False,
                    safe_message="The active data policy denied this dependency attempt.",
                    field_paths=[],
                    dependency_id=definition.dependency_id,
                    outcome="not_applied",
                ),
                duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
                request_hash=hash_text(marker),
                substitution="live",
                original_run_id=None,
            )
        )
        self._context.trace_recorder.finish(
            span_id,
            status="error",
            safe_detail="Dependency attempt was denied before egress.",
        )
