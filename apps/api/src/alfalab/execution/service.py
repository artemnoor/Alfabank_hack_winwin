"""Typed shared execution path for HTTP, CLI, Runs.query, and dependencies."""

from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4

from alfalab_contracts import (
    ArtifactRef,
    ArtifactView,
    DependencyRecord,
    ExecutionMeta,
    LineageSummary,
    Measurement,
    MockParameters,
    OperationDescriptor,
    PrepareInput,
    RunManifest,
    RunRecord,
    VersionedRef,
)
from alfalab_contracts._generated import TraceStatus
from alfalab_contracts.registry import OperationContract
from alfalab_contracts.semantics import validate_dto, validate_operation_semantics
from pydantic import BaseModel

from alfalab.bootstrap.registry import (
    RegisteredImplementation,
    RuntimeRegistry,
    repository_root,
    runtime_build_hash,
)
from alfalab.common.limits import MAX_ARTIFACT_RESPONSE_BYTES
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
from alfalab.execution.gateway import ControlledDependencyGateway
from alfalab.execution.policy import ResolvedPolicy, TrustedDataPolicyResolver
from alfalab.execution.temporal import parse_utc_timestamp
from alfalab.execution.tracing import InMemoryTraceRecorder
from alfalab.modules.runs.storage.repository import RunsRepository, StoredRun


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(value: object) -> str:
    encoded = _canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _measurement_ms(elapsed_ns: int) -> str:
    return format(
        (Decimal(elapsed_ns) / Decimal(1_000_000)).quantize(Decimal("0.001")), "f"
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _RunState:
    operation_id: str
    run_id: str
    input_hash: str
    analytical_time: str
    random_seed: int
    implementation: RegisteredImplementation
    configuration_hash: str
    policy: ResolvedPolicy
    recorder: InMemoryTraceRecorder
    dependencies: list[DependencyRecord]
    context: OperationContext
    root_span_id: str
    operation_span_id: str
    started_at: datetime
    started_ns: int
    payload: BaseModel
    scenario_id: str | None


class ExecutionService:
    """Resolve typed requests and persist only records allowed by trusted policy."""

    def __init__(
        self,
        registry: RuntimeRegistry,
        runs_repository: RunsRepository,
        *,
        environment: str,
        limits: ExecutionLimits | None = None,
        policy_resolver: TrustedDataPolicyResolver | None = None,
    ) -> None:
        self._registry = registry
        self._runs_repository = runs_repository
        self._environment = environment
        self._limits = limits or ExecutionLimits()
        self._policy_resolver = policy_resolver or TrustedDataPolicyResolver()

    def invoke(
        self,
        descriptor: OperationDescriptor,
        request: BaseModel,
        principal: TrustedPrincipal,
    ) -> BaseModel:
        """Run one operation through one trusted lifecycle for every adapter."""
        operation_id = descriptor.operation_id
        contract = self._registry.contract(operation_id)
        if not isinstance(request, contract.request_type):
            raise invalid_input()
        if (
            operation_id not in principal.permissions
            and "operations.execute" not in principal.permissions
        ):
            raise SafeExecutionError(
                status_code=403,
                code="ACCESS_DENIED",
                category="access",
                safe_message="This operation is not available to the authenticated principal.",
            )
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
        if (
            implementation.payload_type is not contract.input_type
            or implementation.output_type is not contract.output_type
        ):
            raise SafeExecutionError(
                status_code=503,
                code="IMPLEMENTATION_UNAVAILABLE",
                category="unavailable",
                safe_message="The registered implementation is not bound to the operation contract.",
                retryable=True,
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

        # Classification is resolved before payload hashes or artifacts are recorded.
        source_id = None
        if isinstance(request.payload, PrepareInput):
            # A material ID is only a lookup key into the server's reviewed source
            # registry; trust still requires an exact approved payload hash.
            source_id = (
                request.payload.material.source_id
                or request.payload.material.material_id
            )
        candidate_payload_hash = _canonical_hash(
            request.payload.model_dump(mode="json")
        )
        policy = self._policy_resolver.resolve(
            source_id,
            payload_hash=candidate_payload_hash,
        )
        state = self._begin_run(
            operation_id,
            contract,
            request,
            principal,
            implementation,
            policy,
        )

        if not policy.processing_allowed:
            self._finish_spans(state, status="error")
            meta = self._build_meta(
                state, elapsed_ns=perf_counter_ns() - state.started_ns
            )
            try:
                self._write_run(state, meta, status="error", output=None)
            except OSError:
                meta = meta.model_copy(update={"trace_status": TraceStatus.partial})
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The active data policy does not allow local processing.",
                meta=meta,
            )

        initial_meta = self._build_meta(state, elapsed_ns=0)
        try:
            self._write_run(state, initial_meta, status="in_progress", output=None)
        except OSError as exc:
            raise SafeExecutionError(
                status_code=503,
                code="HISTORY_UNAVAILABLE",
                category="unavailable",
                safe_message="Execution history could not be recorded before the operation started.",
                retryable=True,
                meta=initial_meta,
            ) from exc

        try:
            self._apply_scenario(request.implementation.parameters)
            output = implementation.execute(request.payload, state.context)
            if not isinstance(output, implementation.output_type) or not isinstance(
                output, contract.output_type
            ):
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
            preliminary_response = contract.response_type(
                meta=preliminary_meta,
                status="success",
                payload=output,
            )
            try:
                validate_operation_semantics(
                    operation_id, request, preliminary_response
                )
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
            if operation_id == "Runs.query" and getattr(
                request.payload, "include_artifacts", False
            ):
                response_bytes = preliminary_response.model_dump_json().encode("utf-8")
                if len(response_bytes) > MAX_ARTIFACT_RESPONSE_BYTES:
                    raise SafeExecutionError(
                        status_code=429,
                        code="LIMIT_EXCEEDED",
                        category="validation",
                        safe_message="The artifact response exceeds 2 MiB; retry with include_artifacts=false.",
                    )
        except SafeExecutionError as exc:
            self._finish_spans(state, status="error")
            return self._finalize_error(contract, state, exc)
        except OSError as exc:
            self._finish_spans(state, status="error")
            safe = SafeExecutionError(
                status_code=503,
                code="HISTORY_UNAVAILABLE",
                category="unavailable",
                safe_message="Execution history is temporarily unavailable.",
                retryable=True,
                outcome="unknown",
            )
            return self._finalize_error(contract, state, safe, cause=exc)
        except Exception as exc:  # noqa: BLE001 - redact arbitrary implementation and storage failures
            # Exception text may contain source material, provider bodies, or locals.
            self._finish_spans(state, status="error")
            safe = SafeExecutionError(
                status_code=500,
                code="INTERNAL_ERROR",
                category="internal",
                safe_message="The operation could not be completed.",
                outcome="unknown",
            )
            return self._finalize_error(contract, state, safe, cause=exc)

        self._finish_spans(state, status="success")
        meta = self._build_meta(state, elapsed_ns=perf_counter_ns() - state.started_ns)
        response = contract.response_type(meta=meta, status="success", payload=output)
        try:
            self._write_run(state, meta, status="success", output=output)
        except OSError as exc:
            partial_meta = meta.model_copy(update={"trace_status": TraceStatus.partial})
            response = response.model_copy(update={"meta": partial_meta})
            try:
                self._write_run(state, partial_meta, status="unknown", output=None)
            except OSError:
                # A persistent Runs outage can leave the initial in-progress row;
                # the caller still gets the safe unknown-outcome signal.
                pass
            if self._contains_owner_receipt(output):
                # The owner receipt, when present, remains authoritative after commit.
                return response
            raise SafeExecutionError(
                status_code=503,
                code="HISTORY_UNAVAILABLE",
                category="unavailable",
                safe_message="The operation completed but its final history could not be recorded.",
                retryable=True,
                outcome="unknown",
                meta=partial_meta,
            ) from exc
        return response

    def _finalize_error(
        self,
        contract: OperationContract,
        state: _RunState,
        error: SafeExecutionError,
        *,
        cause: Exception | None = None,
    ) -> BaseModel:
        del cause
        elapsed_ns = perf_counter_ns() - state.started_ns
        meta = self._build_meta(state, elapsed_ns=elapsed_ns)
        try:
            self._write_run(state, meta, status="error", output=None)
        except OSError:
            meta = meta.model_copy(update={"trace_status": TraceStatus.partial})
        raise SafeExecutionError(
            status_code=error.status_code,
            code=error.code,
            category=error.category,
            safe_message=error.safe_message,
            retryable=error.retryable,
            field_paths=error.field_paths,
            outcome=error.outcome,
            meta=meta if error.meta is None else error.meta,
        ) from error

    def _resolve_implementation(
        self,
        operation_id: str,
        implementation_id: str,
        version: str,
    ) -> RegisteredImplementation:
        key = (operation_id, implementation_id, version)
        try:
            return self._registry.implementations[key]
        except KeyError as exc:
            raise SafeExecutionError(
                status_code=503,
                code="IMPLEMENTATION_UNAVAILABLE",
                category="unavailable",
                safe_message="The selected implementation is unavailable.",
                retryable=True,
            ) from exc

    @staticmethod
    def _validate_scenario(payload: object, parameters: object) -> None:
        if not isinstance(parameters, MockParameters):
            return
        scenario = parameters.scenario.value
        if scenario in {
            "default",
            "empty",
            "timeout",
            "retryable_error",
            "fatal_error",
        }:
            if (
                scenario == "empty"
                and isinstance(payload, PrepareInput)
                and payload.material.text
            ):
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
        policy: ResolvedPolicy,
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
        if policy.processing_allowed:
            input_hash = _canonical_hash(request.payload.model_dump(mode="json"))
        else:
            # A denied payload is not hashed or retained; only a safe marker is recorded.
            input_hash = _canonical_hash({"policy_denied": True})
        recorder = InMemoryTraceRecorder()
        cancellation = Event()
        dependencies: list[DependencyRecord] = []
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
        context.dependency_gateway = ControlledDependencyGateway(
            definitions=self._registry.dependencies,
            declared_ids=implementation.dependency_ids,
            context=context,
            policy=policy,
            on_record=dependencies.append,
        )
        root_span_id = recorder.start(operation_id, "operation")
        operation_span_id = recorder.start(
            f"{implementation.id}.execute",
            "operation",
            root_span_id,
        )
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
            dependencies=dependencies,
            context=context,
            root_span_id=root_span_id,
            operation_span_id=operation_span_id,
            started_at=_utc_now(),
            started_ns=perf_counter_ns(),
            payload=request.payload,
            scenario_id=(
                request.implementation.parameters.scenario.value
                if isinstance(request.implementation.parameters, MockParameters)
                else None
            ),
        )

    @staticmethod
    def _finish_spans(state: _RunState, *, status: str) -> None:
        safe_detail = (
            "Operation completed."
            if status == "success"
            else "Operation failed safely."
        )
        state.recorder.finish(
            state.operation_span_id, status=status, safe_detail=safe_detail
        )
        state.recorder.finish(
            state.root_span_id, status=status, safe_detail=safe_detail
        )

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
                synthetic_source=state.policy.decision.classification == "synthetic",
                mock_derivation=state.implementation.kind == "mock",
                unknown_origin=state.policy.decision.classification == "unknown",
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
            data_policy=state.policy.decision,
        )

    def _write_run(
        self,
        state: _RunState,
        meta: ExecutionMeta,
        *,
        status: Literal["in_progress", "success", "error", "unknown"],
        output: BaseModel | None,
    ) -> None:
        record = self._build_run_record(state, meta, status=status, output=output)
        self._runs_repository.write(
            StoredRun(
                tenant_id=state.context.tenant_id,
                sandbox_id=state.context.sandbox_id,
                record=record,
                input_hash=state.input_hash,
                started_at=state.started_at,
                updated_at=_utc_now(),
                writer_status=status,
            )
        )

    def _build_run_record(
        self,
        state: _RunState,
        meta: ExecutionMeta,
        *,
        status: Literal["in_progress", "success", "error", "unknown"],
        output: BaseModel | None,
    ) -> RunRecord:
        # A denied payload is represented only by a constant safe marker.
        if not state.policy.processing_allowed:
            payload_json = _canonical_json({"policy_denied": True})
            payload_schema = "ExecutionInputReference"
            payload_hash = _canonical_hash({"policy_denied": True})
            payload_size = len(payload_json.encode("utf-8"))
            payload_content = None
        else:
            payload_model = state.payload
            payload_value = payload_model.model_dump(mode="json")
            payload_json = _canonical_json(payload_value)
            payload_schema = type(payload_model).__name__
            payload_hash = _canonical_hash(payload_value)
            payload_size = len(payload_json.encode("utf-8"))
            payload_content = (
                payload_json
                if state.policy.full_recording_allowed
                and payload_size <= MAX_ARTIFACT_RESPONSE_BYTES
                else None
            )
        input_view = None
        if payload_size <= MAX_ARTIFACT_RESPONSE_BYTES:
            input_ref = ArtifactRef(
                artifact_id=f"artifact-{state.run_id}-input",
                hash=payload_hash,
                schema_id=payload_schema,
                schema_version="1.0.0",
                size_bytes=payload_size,
                classification=state.policy.decision.classification,
                media_type="application/json",
            )
            input_view = ArtifactView(
                ref=input_ref,
                content_json=payload_content,
                availability="available"
                if payload_content is not None
                else "metadata_only",
            )

        configuration_json = _canonical_json(
            {
                "implementation": state.implementation.id,
                "version": state.implementation.version,
                "configuration_hash": state.configuration_hash,
            }
        )
        configuration_ref = ArtifactRef(
            artifact_id=f"artifact-{state.run_id}-configuration",
            hash=_canonical_hash(configuration_json),
            schema_id="RuntimeConfiguration",
            schema_version="1.0.0",
            size_bytes=len(configuration_json.encode("utf-8")),
            classification=state.policy.decision.classification,
            media_type="application/json",
        )
        configuration_view = ArtifactView(
            ref=configuration_ref,
            content_json=None,
            availability="metadata_only",
        )
        output_view = self._artifact_for_output(state, output)
        contract = self._registry.contract(state.operation_id)
        contract_hash = _canonical_hash(contract.descriptor.model_dump(mode="json"))
        root = repository_root()
        lock_path = root / "uv.lock"
        runtime_lock_hash = (
            "sha256:" + hashlib.sha256(lock_path.read_bytes()).hexdigest()
            if lock_path.is_file()
            else _canonical_hash({"lock": "unavailable"})
        )
        scenario = (
            VersionedRef(
                id=state.scenario_id,
                version="1.0.0",
                hash=_canonical_hash({"scenario": state.scenario_id}),
            )
            if state.scenario_id is not None
            else None
        )
        manifest = RunManifest(
            contract_hash=contract_hash,
            envelope_version="1.0.0",
            hash_format="canonical-json-v1",
            implementation=meta.implementation,
            configuration=configuration_view,
            models=[],
            prompts=[],
            taxonomies=[],
            ontologies=[],
            rules=[],
            bindings=[],
            scenario=scenario,
            runtime_lock_hash=runtime_lock_hash,
            runtime_build_hash=runtime_build_hash(),
            platform=f"python-{sys.version_info.major}.{sys.version_info.minor}",
            analytical_time=state.analytical_time,
            random_seed=state.random_seed,
            recording=state.policy.decision.recording,
            state_capture=None,
            replay_of=None,
            data_classification=state.policy.decision.classification,
            data_policy=state.policy.decision,
        )
        record_status = {
            "in_progress": "running",
            "success": "success",
            "error": "failed",
            "unknown": "unknown",
        }[status]
        return RunRecord(
            run_id=state.run_id,
            operation_id=state.operation_id,
            contract_version="1.0.0",
            implementation=meta.implementation,
            configuration_hash=state.configuration_hash,
            manifest=manifest,
            scenario=scenario,
            parent_run_id=None,
            status=record_status,
            input=input_view,
            output=output_view,
            dependencies=list(state.dependencies),
            spans=list(state.recorder.spans),
            measurements=list(meta.measurements),
            lineage=meta.lineage,
            trace_status=meta.trace_status,
            replay_status=meta.replay_status,
            analytical_time=state.analytical_time,
            random_seed=state.random_seed,
            runtime_build_hash=manifest.runtime_build_hash,
        )

    def _artifact_for_output(
        self, state: _RunState, output: BaseModel | None
    ) -> ArtifactView | None:
        if output is None:
            return None
        value = output.model_dump(mode="json")
        encoded = _canonical_json(value)
        raw = encoded.encode("utf-8")
        if len(raw) > MAX_ARTIFACT_RESPONSE_BYTES:
            return None
        content = encoded if state.policy.full_recording_allowed else None
        return ArtifactView(
            ref=ArtifactRef(
                artifact_id=f"artifact-{state.run_id}-output",
                hash=_canonical_hash(value),
                schema_id=type(output).__name__,
                schema_version="1.0.0",
                size_bytes=len(raw),
                classification=state.policy.decision.classification,
                media_type="application/json",
            ),
            content_json=content,
            availability="available" if content is not None else "metadata_only",
        )

    @staticmethod
    def _contains_owner_receipt(value: object) -> bool:
        if isinstance(value, BaseModel):
            if (
                "receipt" in value.model_fields_set
                and getattr(value, "receipt", None) is not None
            ):
                return True
            return any(
                ExecutionService._contains_owner_receipt(item)
                for item in value.__dict__.values()
                if isinstance(item, (BaseModel, list, tuple, dict))
            )
        if isinstance(value, dict):
            return any(
                ExecutionService._contains_owner_receipt(item)
                for item in value.values()
            )
        if isinstance(value, (list, tuple)):
            return any(ExecutionService._contains_owner_receipt(item) for item in value)
        return False
