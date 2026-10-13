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
    ErrorInfo,
    ExecutionMeta,
    LineageSummary,
    Measurement,
    MockParameters,
    ModelIdentity,
    OperationDescriptor,
    PrepareInput,
    RunManifest,
    RunRecord,
    VersionedRef,
)
from alfalab_contracts._generated import ReplayStatus, TraceStatus
from alfalab_contracts.registry import OperationContract
from alfalab_contracts.semantics import validate_dto, validate_operation_semantics
from pydantic import BaseModel, ValidationError

from alfalab.bootstrap.registry import (
    RegisteredImplementation,
    RuntimeRegistry,
    repository_root,
    runtime_build_hash,
)
from alfalab.common.artifacts import verified_artifact_json
from alfalab.common.limits import MAX_ARTIFACT_RESPONSE_BYTES
from alfalab.execution.clock import RecordingDomainClock, ReplayDomainClock
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
from alfalab.execution.recording import canonical_hash as _canonical_hash
from alfalab.execution.recording import canonical_json as _canonical_json
from alfalab.execution.recording import hash_text
from alfalab.execution.replay import (
    ReplayCassette,
    ReplayDependencyGateway,
    cassette_replayable,
    replay_incompatible,
    replay_miss,
)
from alfalab.execution.sequence import DependencySequence
from alfalab.execution.temporal import parse_utc_timestamp
from alfalab.execution.tracing import InMemoryTraceRecorder
from alfalab.modules.runs.storage.repository import RunsRepository, StoredRun


def _measurement_ms(elapsed_ns: int) -> str:
    return format(
        (Decimal(elapsed_ns) / Decimal(1_000_000)).quantize(Decimal("0.001")), "f"
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
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
    execution_mode: Literal["live", "replay"]
    replay_of: str | None
    sequence: DependencySequence
    replay_cassette: ReplayCassette | None
    expected_output: BaseModel | None
    expected_error: ErrorInfo | None
    successful: bool = False
    recording_complete: bool = False


@dataclass(frozen=True, slots=True)
class _ReplaySource:
    stored: StoredRun
    payload: BaseModel
    output: BaseModel | None
    expected_error: ErrorInfo | None
    policy: ResolvedPolicy


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
        replay_source = None
        payload = request.payload
        if request.execution.mode == "replay":
            self._validate_scenario(payload, request.implementation.parameters)
            self._validate_payload(payload)
            replay_source = self._load_replay_source(
                operation_id,
                contract,
                request,
                principal,
                implementation,
            )
            payload = replay_source.payload
            policy = replay_source.policy
        else:
            self._validate_scenario(payload, request.implementation.parameters)
            self._validate_payload(payload)
            policy = self._resolve_policy(payload)

        state = self._begin_run(
            operation_id,
            contract,
            request,
            principal,
            implementation,
            policy,
            payload=payload,
            replay_source=replay_source,
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

        initial_meta = self._build_meta(state, elapsed_ns=0, completed=False)
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
            output = implementation.execute(state.payload, state.context)
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
            if state.replay_cassette is not None:
                state.replay_cassette.assert_consumed()
            if state.expected_error is not None:
                raise replay_miss()
            if state.expected_output is not None and _canonical_json(
                output.model_dump(mode="json")
            ) != _canonical_json(state.expected_output.model_dump(mode="json")):
                raise replay_miss()
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
        except SafeExecutionError as caught_error:
            execution_error = caught_error
            if state.execution_mode == "replay" and state.replay_cassette is not None:
                try:
                    state.replay_cassette.assert_consumed()
                except SafeExecutionError:
                    execution_error = replay_miss()
            if state.execution_mode == "replay" and execution_error.code not in {
                "REPLAY_MISS",
                "REPLAY_INCOMPATIBLE",
            }:
                expected = state.expected_error
                if (
                    expected is None
                    or execution_error.code != expected.code
                    or execution_error.category != expected.category
                    or execution_error.retryable != expected.retryable
                    or execution_error.outcome != expected.outcome
                ):
                    execution_error = replay_miss()
            self._finish_spans(state, status="error")
            return self._finalize_error(contract, state, execution_error)
        except OSError as exc:
            self._finish_spans(state, status="error")
            if state.execution_mode == "replay":
                return self._finalize_error(contract, state, replay_miss(), cause=exc)
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
            if state.execution_mode == "replay":
                return self._finalize_error(contract, state, replay_miss(), cause=exc)
            safe = SafeExecutionError(
                status_code=500,
                code="INTERNAL_ERROR",
                category="internal",
                safe_message="The operation could not be completed.",
                outcome="unknown",
            )
            return self._finalize_error(contract, state, safe, cause=exc)

        state.successful = True
        state.recording_complete = self._recording_supports_replay(state, output)
        self._finish_spans(state, status="success")
        meta = self._build_meta(state, elapsed_ns=perf_counter_ns() - state.started_ns)
        response = contract.response_type(meta=meta, status="success", payload=output)
        try:
            self._write_run(state, meta, status="success", output=output)
        except OSError as exc:
            partial_meta = meta.model_copy(
                update={
                    "trace_status": TraceStatus.partial,
                    "replay_status": ReplayStatus.unavailable,
                }
            )
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
        state.recording_complete = self._recording_supports_replay(
            state, None, error=error
        )
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

    def _validate_payload(self, payload: BaseModel) -> None:
        if not isinstance(payload, PrepareInput):
            return
        if len(payload.material.text) > self._limits.max_document_chars:
            raise invalid_input("payload.material.text")
        try:
            validate_dto(payload.material)
        except ValueError as exc:
            raise invalid_input("payload.material.content_hash") from exc

    def _resolve_policy(self, payload: BaseModel) -> ResolvedPolicy:
        source_id = None
        if isinstance(payload, PrepareInput):
            source_id = payload.material.source_id or payload.material.material_id
        return self._policy_resolver.resolve(
            source_id,
            payload_hash=_canonical_hash(payload.model_dump(mode="json")),
        )

    @staticmethod
    def _configuration_hash(
        implementation: RegisteredImplementation, parameters: BaseModel
    ) -> str:
        return _canonical_hash(
            {
                "implementation": implementation.id,
                "version": implementation.version,
                "configuration": implementation.configuration,
                "parameters": parameters.model_dump(mode="json"),
            }
        )

    def _load_replay_source(
        self,
        operation_id: str,
        contract: OperationContract,
        request: BaseModel,
        principal: TrustedPrincipal,
        implementation: RegisteredImplementation,
    ) -> _ReplaySource:
        execution = request.execution
        source_run_id = execution.source_run_id
        if execution.strict is not True or execution.recording != "full":
            raise replay_incompatible()
        profile = contract.descriptor.replay_profile
        profile_value = getattr(profile, "value", profile)
        if profile_value not in {"fixed_input", "recorded_dependencies"}:
            # Runs.query has no approved immutable owner-read bundle yet.
            raise replay_incompatible()
        try:
            stored = self._runs_repository.get(
                source_run_id,
                tenant_id=principal.tenant_id,
                sandbox_id=request.sandbox_id,
            )
        except OSError as exc:
            raise SafeExecutionError(
                status_code=503,
                code="HISTORY_UNAVAILABLE",
                category="unavailable",
                safe_message="Execution history is temporarily unavailable.",
                retryable=True,
            ) from exc
        if stored is None:
            raise replay_incompatible()

        record = stored.record
        if (
            stored.tenant_id != principal.tenant_id
            or stored.sandbox_id != request.sandbox_id
        ):
            raise replay_incompatible()
        expected_error = None
        if (
            stored.writer_status == "success"
            and record.status == "success"
            and record.output is not None
        ):
            pass
        elif (
            stored.writer_status == "error"
            and record.status == "failed"
            and record.output is None
        ):
            expected_error = self._terminal_dependency_error(record.dependencies)
            if expected_error is None:
                raise replay_incompatible()
        else:
            raise replay_incompatible()

        if (
            record.operation_id != operation_id
            or record.replay_status != "available"
            or record.trace_status != "complete"
            or record.manifest.recording != "full"
            or record.manifest.data_classification not in {"synthetic", "public"}
            or not record.manifest.data_policy.processing_allowed
            or record.manifest.envelope_version != "1.0.0"
            or record.manifest.hash_format != "canonical-json-v1"
            or record.analytical_time != record.manifest.analytical_time
            or record.random_seed != record.manifest.random_seed
            or record.contract_version != contract.descriptor.contract_version
            or record.implementation.id != implementation.id
            or record.implementation.version != implementation.version
            or record.manifest.implementation != record.implementation
        ):
            raise replay_incompatible()

        configuration_hash = self._configuration_hash(
            implementation, request.implementation.parameters
        )
        if (
            record.configuration_hash != configuration_hash
            or record.manifest.configuration.ref.schema_id != "RuntimeConfiguration"
            or record.manifest.configuration.ref.schema_version != "1.0.0"
        ):
            raise replay_incompatible()

        current_contract_hash = _canonical_hash(
            contract.descriptor.model_dump(mode="json")
        )
        current_build_hash = runtime_build_hash()
        lock_path = repository_root() / "uv.lock"
        current_lock_hash = (
            "sha256:" + hashlib.sha256(lock_path.read_bytes()).hexdigest()
            if lock_path.is_file()
            else _canonical_hash({"lock": "unavailable"})
        )
        if (
            record.manifest.contract_hash != current_contract_hash
            or record.manifest.runtime_build_hash != current_build_hash
            or record.runtime_build_hash != current_build_hash
            or record.manifest.runtime_lock_hash != current_lock_hash
        ):
            raise replay_incompatible()
        source_models = [
            model.model_dump(mode="json") for model in record.manifest.models
        ]
        current_models = [
            model.model_dump(mode="json")
            for model in self._model_identities_for_dependencies(record.dependencies)
        ]
        if not self._dependencies_have_replayable_model_identities(
            record.dependencies
        ) or _canonical_json(source_models) != _canonical_json(current_models):
            raise replay_incompatible()

        if record.input is None or (expected_error is None and record.output is None):
            raise replay_incompatible()
        if (
            record.input.ref.schema_id != contract.input_type.__name__
            or record.input.ref.schema_version != "1.0.0"
            or (
                record.output is not None
                and (
                    record.output.ref.schema_id != contract.output_type.__name__
                    or record.output.ref.schema_version != "1.0.0"
                )
            )
        ):
            raise replay_incompatible()
        supplied_hash = _canonical_hash(request.payload.model_dump(mode="json"))
        if supplied_hash != record.input.ref.hash or supplied_hash != stored.input_hash:
            raise replay_incompatible()

        policy = self._resolve_policy(request.payload)
        if (
            policy.decision.model_dump(mode="json")
            != record.manifest.data_policy.model_dump(mode="json")
            or not policy.full_recording_allowed
        ):
            raise replay_incompatible()

        refs = [record.manifest.configuration.ref, record.input.ref]
        if record.output is not None:
            refs.append(record.output.ref)
        for dependency in record.dependencies:
            refs.append(dependency.request.ref)
            if dependency.response is not None:
                refs.append(dependency.response.ref)
        if len({ref.artifact_id for ref in refs}) != len(refs):
            raise replay_miss()
        try:
            contents = self._runs_repository.read_replay_artifacts(
                source_run_id,
                tuple(refs),
                tenant_id=principal.tenant_id,
                sandbox_id=request.sandbox_id,
            )
        except OSError as exc:
            raise SafeExecutionError(
                status_code=503,
                code="HISTORY_UNAVAILABLE",
                category="unavailable",
                safe_message="Execution history is temporarily unavailable.",
                retryable=True,
            ) from exc
        if contents is None or len(contents) != len(refs):
            raise replay_miss()

        source_record = record.model_copy(deep=True)
        views = [source_record.manifest.configuration, source_record.input]
        if source_record.output is not None:
            views.append(source_record.output)
        for dependency in source_record.dependencies:
            views.append(dependency.request)
            if dependency.response is not None:
                views.append(dependency.response)
        try:
            for view in views:
                view.content_json = contents[view.ref.artifact_id]
                view.availability = "available"
            config_json = verified_artifact_json(
                source_record.manifest.configuration,
                expected_schema_id="RuntimeConfiguration",
                expected_classification=record.manifest.data_classification,
            )
            expected_config = {
                "implementation": implementation.id,
                "version": implementation.version,
                "configuration_hash": configuration_hash,
            }
            if config_json != _canonical_json(expected_config):
                raise ValueError("configuration artifact does not match its hash")
            input_json = verified_artifact_json(
                source_record.input,
                expected_schema_id=contract.input_type.__name__,
                expected_classification=record.manifest.data_classification,
            )
            payload = contract.input_type.model_validate(json.loads(input_json))
            expected_output = None
            if source_record.output is not None:
                output_json = verified_artifact_json(
                    source_record.output,
                    expected_schema_id=contract.output_type.__name__,
                    expected_classification=record.manifest.data_classification,
                )
                expected_output = contract.output_type.model_validate(
                    json.loads(output_json)
                )
            for dependency in source_record.dependencies:
                verified_artifact_json(
                    dependency.request,
                    expected_schema_id=dependency.request.ref.schema_id,
                    expected_classification=record.manifest.data_classification,
                )
                if dependency.response is not None:
                    verified_artifact_json(
                        dependency.response,
                        expected_schema_id=dependency.response.ref.schema_id,
                        expected_classification=record.manifest.data_classification,
                    )
        except (KeyError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise replay_miss() from exc

        if _canonical_hash(payload.model_dump(mode="json")) != record.input.ref.hash:
            raise replay_miss()
        if not cassette_replayable(
            source_record.dependencies, self._dependency_sensitive_values_by_port()
        ):
            raise replay_miss()
        return _ReplaySource(
            stored=StoredRun(
                tenant_id=stored.tenant_id,
                sandbox_id=stored.sandbox_id,
                record=source_record,
                input_hash=stored.input_hash,
                started_at=stored.started_at,
                updated_at=stored.updated_at,
                writer_status=stored.writer_status,
            ),
            payload=payload,
            output=expected_output,
            expected_error=expected_error,
            policy=policy,
        )

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
        *,
        payload: BaseModel,
        replay_source: _ReplaySource | None,
    ) -> _RunState:
        run_id = uuid4().hex
        execution_mode: Literal["live", "replay"] = request.execution.mode
        analytical_time = (
            replay_source.stored.record.analytical_time
            if replay_source is not None
            else request.execution.analytical_time
        )
        analytical_clock = parse_utc_timestamp(analytical_time)
        seed = (
            replay_source.stored.record.random_seed
            if replay_source is not None
            else request.execution.random_seed
        )
        configuration_hash = self._configuration_hash(
            implementation, request.implementation.parameters
        )
        if policy.processing_allowed:
            input_hash = _canonical_hash(payload.model_dump(mode="json"))
        else:
            # A denied payload is not hashed or retained; only a safe marker is recorded.
            input_hash = _canonical_hash({"policy_denied": True})
        recorder = InMemoryTraceRecorder()
        cancellation = Event()
        dependencies: list[DependencyRecord] = []
        sequence = DependencySequence()
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
        replay_cassette = None
        replay_of = replay_source.stored.run_id if replay_source is not None else None
        if replay_source is None:
            context.dependency_gateway = ControlledDependencyGateway(
                definitions=self._registry.dependencies,
                declared_ids=implementation.dependency_ids,
                context=context,
                policy=policy,
                on_record=dependencies.append,
                sequence=sequence,
            )
            context.domain_clock = RecordingDomainClock(
                context=context,
                policy=policy,
                sequence=sequence,
                on_record=dependencies.append,
            )
        else:
            replay_cassette = ReplayCassette(
                source_run_id=replay_of,
                entries=replay_source.stored.record.dependencies,
                context=context,
                policy=policy,
                sequence=sequence,
                on_record=dependencies.append,
            )
            context.dependency_gateway = ReplayDependencyGateway(
                definitions=self._registry.dependencies,
                declared_ids=implementation.dependency_ids,
                context=context,
                cassette=replay_cassette,
                sequence=sequence,
                on_record=dependencies.append,
            )
            context.domain_clock = ReplayDomainClock(
                context=context,
                cassette=replay_cassette,
                sequence=sequence,
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
            payload=payload,
            scenario_id=(
                request.implementation.parameters.scenario.value
                if isinstance(request.implementation.parameters, MockParameters)
                else None
            ),
            execution_mode=execution_mode,
            replay_of=replay_of,
            sequence=sequence,
            replay_cassette=replay_cassette,
            expected_output=replay_source.output if replay_source is not None else None,
            expected_error=(
                replay_source.expected_error if replay_source is not None else None
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

    @staticmethod
    def _terminal_dependency_error(
        dependencies: list[DependencyRecord],
    ) -> ErrorInfo | None:
        if not dependencies:
            return None
        error = dependencies[-1].error
        if (
            error is None
            or error.code != "DEPENDENCY_FAILED"
            or error.category != "dependency"
            or error.outcome not in {"unknown", "not_applied"}
        ):
            return None
        return error

    def _recording_supports_replay(
        self,
        state: _RunState,
        output: BaseModel | None,
        *,
        error: SafeExecutionError | None = None,
    ) -> bool:
        if not state.policy.full_recording_allowed:
            return False
        if output is None:
            expected_error = self._terminal_dependency_error(state.dependencies)
            if (
                error is None
                or expected_error is None
                or error.code != expected_error.code
                or error.category != expected_error.category
                or error.retryable != expected_error.retryable
                or error.outcome != expected_error.outcome
            ):
                return False
        values = [state.payload.model_dump(mode="json")]
        if output is not None:
            values.append(output.model_dump(mode="json"))
        for value in values:
            if (
                len(_canonical_json(value).encode("utf-8"))
                > MAX_ARTIFACT_RESPONSE_BYTES
            ):
                return False
        profile = self._registry.contract(state.operation_id).descriptor.replay_profile
        profile_value = getattr(profile, "value", profile)
        if profile_value not in {"fixed_input", "recorded_dependencies"}:
            return False
        if not self._dependencies_have_replayable_model_identities(state.dependencies):
            return False
        return cassette_replayable(
            state.dependencies, self._dependency_sensitive_values_by_port()
        )

    def _model_identities_for_dependencies(
        self, dependencies: list[DependencyRecord]
    ) -> list[ModelIdentity]:
        identities: dict[str, ModelIdentity] = {}
        for dependency in dependencies:
            if dependency.kind != "model":
                continue
            definition = self._registry.dependencies.get(dependency.port_id)
            identity = definition.model_identity if definition is not None else None
            if identity is not None:
                identities[_canonical_json(identity.model_dump(mode="json"))] = identity
        return [identities[key] for key in sorted(identities)]

    def _dependencies_have_replayable_model_identities(
        self, dependencies: list[DependencyRecord]
    ) -> bool:
        for dependency in dependencies:
            if dependency.kind != "model":
                continue
            definition = self._registry.dependencies.get(dependency.port_id)
            identity = definition.model_identity if definition is not None else None
            if (
                identity is None
                or identity.provider_revision is None
                or identity.unknown_revision_reason is not None
            ):
                return False
        return True

    def _dependency_sensitive_values_by_port(
        self,
    ) -> dict[str, tuple[str, ...] | None]:
        values: dict[str, tuple[str, ...] | None] = {
            dependency_id: (
                definition.sensitive_values
                if definition.secret_inventory_complete
                else None
            )
            for dependency_id, definition in self._registry.dependencies.items()
        }
        values["clock.domain.now"] = ()
        return values

    def _build_meta(
        self, state: _RunState, *, elapsed_ns: int, completed: bool = True
    ) -> ExecutionMeta:
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
            execution_mode=state.execution_mode,
            environment=self._environment,
            configuration_hash=state.configuration_hash,
            duration_ms=max(0, elapsed_ns // 1_000_000),
            lineage=LineageSummary(
                synthetic_source=state.policy.decision.classification == "synthetic",
                mock_derivation=state.implementation.kind == "mock",
                unknown_origin=state.policy.decision.classification == "unknown",
                source_refs=[],
            ),
            trace_status=(
                TraceStatus.metadata_only
                if not (
                    state.policy.decision.classification in {"synthetic", "public"}
                    and state.policy.decision.processing_allowed
                    and state.policy.decision.recording == "full"
                )
                else TraceStatus.complete
                if completed
                else TraceStatus.partial
            ),
            replay_status=(
                "available"
                if state.recording_complete
                else "incomplete"
                if not completed and state.policy.full_recording_allowed
                else "unavailable"
            ),
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
            hash=hash_text(configuration_json),
            schema_id="RuntimeConfiguration",
            schema_version="1.0.0",
            size_bytes=len(configuration_json.encode("utf-8")),
            classification=state.policy.decision.classification,
            media_type="application/json",
        )
        configuration_view = ArtifactView(
            ref=configuration_ref,
            content_json=(
                configuration_json if state.policy.full_recording_allowed else None
            ),
            availability=(
                "available" if state.policy.full_recording_allowed else "metadata_only"
            ),
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
            models=self._model_identities_for_dependencies(state.dependencies),
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
            replay_of=state.replay_of,
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
