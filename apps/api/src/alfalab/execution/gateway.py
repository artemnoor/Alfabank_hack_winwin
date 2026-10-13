"""Declared-only dependency gateway with policy, attempt, and trace recording."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter_ns, sleep

from alfalab_contracts import ArtifactRef, ArtifactView, DependencyRecord, ErrorInfo
from pydantic import BaseModel

from alfalab.common.protocols import OperationContext
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.policy import ResolvedPolicy


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DependencyDefinition:
    dependency_id: str
    kind: str
    request_type: type[BaseModel]
    response_type: type[BaseModel]
    invoke: Callable[[BaseModel, OperationContext], BaseModel]
    max_attempts: int = 1


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
    ) -> None:
        self._definitions = definitions
        self._declared_ids = declared_ids
        self._context = context
        self._policy = policy
        self._on_record = on_record
        self._sleep = sleep_fn
        self._sequence = 0

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
        if not self._policy.egress_allowed:
            self._record_denied(definition)
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The active data policy does not allow external dependency access.",
            )

        request_json = _canonical_json(request.model_dump(mode="json"))
        request_bytes = request_json.encode("utf-8")
        if len(request_bytes) > 2 * 1024 * 1024:
            raise SafeExecutionError(
                status_code=429,
                code="LIMIT_EXCEEDED",
                category="validation",
                safe_message="The dependency request exceeds the configured size limit.",
            )
        request_hash = _hash_text(request_json)
        request_view = self._artifact_view(
            artifact_id=f"artifact-{self._context.run_id}-dep-{self._sequence}-request",
            schema_id=definition.request_type.__name__,
            value_json=request_json,
            include_content=self._policy.full_recording_allowed,
        )

        attempt_limit = max(
            1, min(definition.max_attempts, self._context.limits.max_attempts)
        )
        last_error: SafeExecutionError | None = None
        for attempt in range(attempt_limit):
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
                response_json = _canonical_json(response.model_dump(mode="json"))
                if len(response_json.encode("utf-8")) > 2 * 1024 * 1024:
                    raise SafeExecutionError(
                        status_code=502,
                        code="DEPENDENCY_FAILED",
                        category="dependency",
                        safe_message="The declared dependency returned an oversized response.",
                        outcome="unknown",
                    )
                response_view = self._artifact_view(
                    artifact_id=f"artifact-{self._context.run_id}-dep-{self._sequence}-response",
                    schema_id=definition.response_type.__name__,
                    value_json=response_json,
                    include_content=self._policy.full_recording_allowed,
                )
                self._context.trace_recorder.finish(
                    span_id,
                    status="success",
                    safe_detail="Dependency attempt completed.",
                )
                self._on_record(
                    DependencyRecord(
                        sequence=self._sequence,
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
                self._sequence += 1
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
                    retryable=retry,
                    safe_message="The declared dependency could not be completed.",
                    field_paths=[],
                    dependency_id=dependency_id,
                    outcome="unknown" if exc.outcome == "unknown" else "not_applied",
                )
                self._on_record(
                    DependencyRecord(
                        sequence=self._sequence,
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
                self._sequence += 1
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
                        sequence=self._sequence,
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
                self._sequence += 1
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
            outcome="unknown",
        ) from last_error

    def _record_denied(self, definition: DependencyDefinition) -> None:
        span_id = self._context.trace_recorder.start(
            f"dependency.{definition.dependency_id}.attempt-1",
            "dependency",
        )
        started_ns = perf_counter_ns()
        marker = _canonical_json(
            {"policy": "egress-denied", "dependency_id": definition.dependency_id}
        )
        view = self._artifact_view(
            artifact_id=f"artifact-{self._context.run_id}-dep-{self._sequence}-request",
            schema_id="PolicyDeniedDependencyRequest",
            value_json=marker,
            include_content=False,
            availability="policy_denied",
        )
        self._on_record(
            DependencyRecord(
                sequence=self._sequence,
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
                request_hash=_hash_text(marker),
                substitution="live",
                original_run_id=None,
            )
        )
        self._context.trace_recorder.finish(
            span_id,
            status="error",
            safe_detail="Dependency attempt was denied by data policy.",
        )
        self._sequence += 1

    def _artifact_view(
        self,
        *,
        artifact_id: str,
        schema_id: str,
        value_json: str,
        include_content: bool,
        availability: str | None = None,
    ) -> ArtifactView:
        raw = value_json.encode("utf-8")
        classification = self._policy.decision.classification
        return ArtifactView(
            ref=ArtifactRef(
                artifact_id=artifact_id,
                hash=_hash_text(value_json),
                schema_id=schema_id,
                schema_version="1.0.0",
                size_bytes=len(raw),
                classification=classification,
                media_type="application/json",
            ),
            content_json=value_json if include_content else None,
            availability=availability
            or ("available" if include_content else "metadata_only"),
        )
