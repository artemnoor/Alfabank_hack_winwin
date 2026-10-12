"""Typed shared execution path for HTTP and future non-HTTP callers."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from decimal import Decimal
from threading import Event
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from alfalab_contracts import (
    DataPolicyDecision,
    ExecutionMeta,
    LineageSummary,
    Measurement,
    MockParameters,
    OperationDescriptor,
    PrepareInput,
    RealPrepareParameters,
    VersionedRef,
)
from alfalab_contracts.semantics import validate_dto, validate_operation_semantics
from alfalab_contracts.registry import OperationContract

from alfalab.bootstrap.registry import RegisteredImplementation, RuntimeRegistry
from alfalab.execution.context import (
    DISABLED_ARTIFACT_READER,
    DISABLED_DEPENDENCY_GATEWAY,
    DISABLED_EVIDENCE_READER,
    ExecutionLimits,
    FixedAnalyticalClock,
    OperationContext,
    TrustedPrincipal,
)
from alfalab.execution.errors import SafeExecutionError, invalid_input
from alfalab.execution.recording import InMemoryRun, RunsWriter
from alfalab.execution.temporal import parse_utc_timestamp
from alfalab.execution.tracing import InMemoryTraceRecorder


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _measurement_ms(elapsed_ns: int) -> str:
    return format((Decimal(elapsed_ns) / Decimal(1_000_000)).quantize(Decimal("0.001")), "f")


@dataclass(frozen=True, slots=True)
class _RunState:
    operation_id: str
    run_id: str
    input_hash: str
    analytical_time: str
    random_seed: int
    implementation: RegisteredImplementation
    configuration_hash: str
    policy: DataPolicyDecision
    recorder: InMemoryTraceRecorder
    context: OperationContext
    root_span_id: str
    operation_span_id: str
    started_ns: int


class ExecutionService:
    """Resolve typed requests through the registry and record actual safe metadata."""

    def __init__(
        self,
        registry: RuntimeRegistry,
        runs_writer: RunsWriter,
        *,
        environment: str,
        limits: ExecutionLimits | None = None,
    ) -> None:
        self._registry = registry
        self._runs_writer = runs_writer
        self._environment = environment
        self._limits = limits or ExecutionLimits()

    def invoke(
        self,
        descriptor: OperationDescriptor,
        request: BaseModel,
        principal: TrustedPrincipal,
    ) -> BaseModel:
        """Run one operation descriptor against its strictly bound request DTO."""
        operation_id = descriptor.operation_id
        contract = self._registry.contract(operation_id)
        if not isinstance(request, contract.request_type):
            raise invalid_input()

        if request.sandbox_id not in principal.allowed_sandboxes:
            raise SafeExecutionError(
                status_code=403,
                code="ACCESS_DENIED",
                category="access",
                safe_message="The requested sandbox is not available to this principal.",
            )

        if request.execution.mode != "live":
            raise SafeExecutionError(
                status_code=409,
                code="REPLAY_INCOMPATIBLE",
                category="replay",
                safe_message="Replay is unavailable for this execution slice.",
            )

        implementation = self._resolve_implementation(
            operation_id,
            request.implementation.id,
            request.implementation.version,
        )
        if type(request.implementation.parameters) is not implementation.parameter_type:
            raise invalid_input("implementation.parameters")
        self._validate_scenario(request.payload, request.implementation.parameters)

        if isinstance(request.payload, PrepareInput):
            if len(request.payload.material.text) > self._limits.max_document_chars:
                raise invalid_input("payload.material.text")
            try:
                validate_dto(request.payload.material)
            except ValueError as exc:
                raise invalid_input("payload.material.content_hash") from exc

        state = self._begin_run(
            operation_id,
            contract,
            request,
            principal,
            implementation,
        )
        try:
            self._write_run(
                state,
                self._build_meta(state, elapsed_ns=0),
                status="in_progress",
            )
        except OSError as exc:
            raise SafeExecutionError(
                status_code=503,
                code="HISTORY_UNAVAILABLE",
                category="unavailable",
                safe_message="Execution metadata could not be recorded before the operation started.",
                retryable=True,
            ) from exc
        try:
            self._apply_scenario(request.implementation.parameters)
            output = implementation.execute(request.payload, state.context)
            if not isinstance(output, contract.output_type):
                raise SafeExecutionError(
                    status_code=500,
                    code="OUTPUT_CONTRACT_VIOLATION",
                    category="internal",
                    safe_message="The implementation returned an invalid operation result.",
                    outcome="unknown",
                )

            preliminary_meta = self._build_meta(
                state,
                elapsed_ns=perf_counter_ns() - state.started_ns,
            )
            response = contract.response_type(meta=preliminary_meta, status="success", payload=output)
            try:
                validate_operation_semantics(operation_id, request, response)
            except ValueError as exc:
                raise SafeExecutionError(
                    status_code=500,
                    code="OUTPUT_CONTRACT_VIOLATION",
                    category="internal",
                    safe_message="The implementation returned a result outside the operation contract.",
                    outcome="unknown",
                    meta=preliminary_meta,
                ) from exc

            elapsed_ns = perf_counter_ns() - state.started_ns
            if elapsed_ns > request.execution.timeout_ms * 1_000_000:
                raise SafeExecutionError(
                    status_code=504,
                    code="TIMEOUT",
                    category="timeout",
                    safe_message="The operation exceeded its configured time limit.",
                    retryable=True,
                    outcome="unknown",
                )

            meta = self._build_meta(state, elapsed_ns=elapsed_ns)
            response = contract.response_type(meta=meta, status="success", payload=output)
            self._finish_spans(state, status="success")
            self._write_run(state, meta, status="success")
            return response
        except SafeExecutionError as exc:
            self._finish_spans(state, status="error")
            elapsed_ns = perf_counter_ns() - state.started_ns
            meta = self._build_meta(state, elapsed_ns=elapsed_ns)
            self._write_run(state, meta, status="error")
            if exc.meta is None:
                raise SafeExecutionError(
                    status_code=exc.status_code,
                    code=exc.code,
                    category=exc.category,
                    safe_message=exc.safe_message,
                    retryable=exc.retryable,
                    field_paths=exc.field_paths,
                    outcome=exc.outcome,
                    meta=meta,
                ) from exc
            raise
        except Exception as exc:
            # Operation implementations are pluggable, so unknown failures at
            # this execution boundary must become sanitized safe errors. Never
            # serialize exception text, which can contain payloads or locals.
            self._finish_spans(state, status="error")
            elapsed_ns = perf_counter_ns() - state.started_ns
            meta = self._build_meta(state, elapsed_ns=elapsed_ns)
            self._write_run(state, meta, status="error")
            raise SafeExecutionError(
                status_code=500,
                code="INTERNAL_ERROR",
                category="internal",
                safe_message="The operation could not be completed.",
                outcome="unknown",
                meta=meta,
            ) from exc

    def _resolve_implementation(
        self,
        operation_id: str,
        implementation_id: str,
        version: str,
    ) -> RegisteredImplementation:
        key = (operation_id, implementation_id, version)
        try:
            implementation = self._registry.implementations[key]
        except KeyError as exc:
            raise SafeExecutionError(
                status_code=503,
                code="IMPLEMENTATION_UNAVAILABLE",
                category="unavailable",
                safe_message="The selected implementation is unavailable.",
                retryable=True,
            ) from exc
        return implementation

    @staticmethod
    def _validate_scenario(payload: object, parameters: object) -> None:
        if not isinstance(parameters, MockParameters):
            return
        scenario = parameters.scenario.value
        if scenario in {"default", "empty", "timeout", "retryable_error", "fatal_error"}:
            if scenario == "empty" and isinstance(payload, PrepareInput) and payload.material.text:
                raise invalid_input("implementation.parameters.scenario")
            return
        raise invalid_input("implementation.parameters.scenario")

    @staticmethod
    def _apply_scenario(parameters: object) -> None:
        if not isinstance(parameters, MockParameters):
            return
        scenario = parameters.scenario.value
        if scenario == "timeout":
            raise SafeExecutionError(
                status_code=504,
                code="TIMEOUT",
                category="timeout",
                safe_message="The controlled mock execution timed out.",
                retryable=True,
            )
        if scenario in {"retryable_error", "fatal_error"}:
            raise SafeExecutionError(
                status_code=502,
                code="DEPENDENCY_FAILED",
                category="dependency",
                safe_message="The controlled mock failure was triggered.",
                retryable=scenario == "retryable_error",
            )

    def _begin_run(
        self,
        operation_id: str,
        contract: OperationContract,
        request: BaseModel,
        principal: TrustedPrincipal,
        implementation: RegisteredImplementation,
    ) -> _RunState:
        run_id = uuid4().hex
        analytical_time = request.execution.analytical_time
        analytical_clock = parse_utc_timestamp(analytical_time)
        seed = request.execution.random_seed
        params = request.implementation.parameters.model_dump(mode="json")
        configuration_hash = _canonical_hash(
            {
                "implementation": implementation.id,
                "version": implementation.version,
                "configuration": implementation.configuration,
                "parameters": params,
            }
        )
        # Inline content has no approved fixture manifest in this slice. The
        # client declaration and embedded provenance therefore cannot raise trust.
        policy_hash = _canonical_hash(
            {
                "policy": "inline-unknown-v1",
                "processing": "local-only",
                "recording": "metadata_only",
            }
        )
        policy = DataPolicyDecision(
            policy=VersionedRef(id="inline-unknown-v1", version="1.0.0", hash=policy_hash),
            classification="unknown",
            processing_allowed=True,
            egress_allowed=False,
            recording="metadata_only",
            export_allowed=False,
            reason_codes=["UNVERIFIED_INLINE_INPUT"],
        )
        recorder = InMemoryTraceRecorder()
        cancellation = Event()
        context = OperationContext(
            principal=principal,
            tenant_id=principal.tenant_id,
            sandbox_id=request.sandbox_id,
            environment=self._environment,
            run_id=run_id,
            operation_id=operation_id,
            request_id=request.request_id,
            contract_version=contract.descriptor.contract_version,
            idempotency_key=getattr(request, "idempotency_key", None),
            implementation_id=implementation.id,
            implementation_version=implementation.version,
            implementation_configuration_hash=configuration_hash,
            analytical_clock=FixedAnalyticalClock(analytical_clock),
            rng=random.Random(seed),
            artifact_reader=DISABLED_ARTIFACT_READER,
            evidence_reader=DISABLED_EVIDENCE_READER,
            dependency_gateway=DISABLED_DEPENDENCY_GATEWAY,
            trace_recorder=recorder,
            cancellation_event=cancellation,
            limits=self._limits,
        )
        root_span_id = recorder.start(operation_id, "operation")
        operation_span_id = recorder.start(
            f"{implementation.id}.execute",
            "operation",
            root_span_id,
        )
        input_hash = _canonical_hash(request.payload.model_dump(mode="json"))
        return _RunState(
            operation_id=operation_id,
            run_id=run_id,
            input_hash=input_hash,
            analytical_time=analytical_time,
            random_seed=seed,
            implementation=implementation,
            configuration_hash=configuration_hash,
            policy=policy,
            recorder=recorder,
            context=context,
            root_span_id=root_span_id,
            operation_span_id=operation_span_id,
            started_ns=perf_counter_ns(),
        )

    @staticmethod
    def _finish_spans(state: _RunState, *, status: str) -> None:
        safe_detail = "Operation completed." if status == "success" else "Operation failed safely."
        state.recorder.finish(state.operation_span_id, status=status, safe_detail=safe_detail)
        state.recorder.finish(state.root_span_id, status=status, safe_detail=safe_detail)

    def _build_meta(self, state: _RunState, *, elapsed_ns: int) -> ExecutionMeta:
        implementation_hash = _canonical_hash(
            {"id": state.implementation.id, "version": state.implementation.version}
        )
        return ExecutionMeta(
            run_id=state.run_id,
            operation_id=state.operation_id,
            contract_version="1.0.0",
            implementation=VersionedRef(
                id=state.implementation.id,
                version=state.implementation.version,
                hash=implementation_hash,
            ),
            execution_mode="live",
            environment=self._environment,
            configuration_hash=state.configuration_hash,
            duration_ms=max(0, elapsed_ns // 1_000_000),
            lineage=LineageSummary(
                synthetic_source=False,
                mock_derivation=state.implementation.kind == "mock",
                unknown_origin=True,
                source_refs=[],
            ),
            trace_status="metadata_only",
            replay_status="unavailable",
            measurements=[
                Measurement(
                    name="duration_ms",
                    value=_measurement_ms(elapsed_ns),
                    unit="ms",
                    basis="measured",
                )
            ],
            data_policy=state.policy,
        )

    def _write_run(
        self,
        state: _RunState,
        meta: ExecutionMeta,
        *,
        status: Literal["in_progress", "success", "error"],
    ) -> None:
        self._runs_writer.write(
            InMemoryRun(
                run_id=state.run_id,
                input_hash=state.input_hash,
                analytical_time=state.analytical_time,
                random_seed=state.random_seed,
                meta=meta,
                spans=state.recorder.spans,
                status=status,
            )
        )
