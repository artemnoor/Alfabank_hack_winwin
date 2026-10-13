from __future__ import annotations

import json
import random
from datetime import UTC, datetime

import pytest
from alfalab.execution.context import (
    DISABLED_ARTIFACT_READER,
    DISABLED_DEPENDENCY_GATEWAY,
    DISABLED_EVIDENCE_READER,
    ExecutionLimits,
    FixedAnalyticalClock,
    OperationContext,
    TrustedPrincipal,
)
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.gateway import ControlledDependencyGateway, DependencyDefinition
from alfalab.execution.policy import TrustedDataPolicyResolver, TrustedSource
from alfalab.execution.tracing import InMemoryTraceRecorder
from alfalab.modules.runs.storage.postgres import _reserve_artifact_response_bytes
from alfalab_contracts import ModelIdentity
from pydantic import BaseModel


class Request(BaseModel):
    value: str


class Response(BaseModel):
    result: str


def _context() -> OperationContext:
    principal = TrustedPrincipal(
        actor_id="test-actor",
        tenant_id="test-tenant",
        role="developer",
        allowed_sandboxes=frozenset({"test-sandbox"}),
        permissions=frozenset({"Documents.prepare"}),
    )
    return OperationContext(
        principal=principal,
        tenant_id=principal.tenant_id,
        sandbox_id="test-sandbox",
        environment="testing",
        run_id="run-test-001",
        operation_id="Documents.prepare",
        request_id="request-test-001",
        contract_version="1.0.0",
        idempotency_key=None,
        implementation_id="real.prepare",
        implementation_version="1.0.0",
        implementation_configuration_hash="sha256:" + "1" * 64,
        analytical_clock=FixedAnalyticalClock(datetime.now(UTC)),
        rng=random.Random(1),
        artifact_reader=DISABLED_ARTIFACT_READER,
        evidence_reader=DISABLED_EVIDENCE_READER,
        dependency_gateway=DISABLED_DEPENDENCY_GATEWAY,
        trace_recorder=InMemoryTraceRecorder(),
        cancellation_event=__import__("threading").Event(),
        limits=ExecutionLimits(),
    )


def test_client_declaration_does_not_grant_full_recording_or_dependency_egress() -> (
    None
):
    resolver = TrustedDataPolicyResolver()
    policy = resolver.resolve(
        "client-claimed-public", payload_hash="sha256:" + "a" * 64
    )
    assert policy.decision.classification == "unknown"
    assert policy.decision.recording == "metadata_only"
    assert policy.egress_allowed is False
    assert policy.full_recording_allowed is False


def test_policy_denial_precedes_dependency_call_and_records_only_safe_metadata() -> (
    None
):
    called = False
    records = []

    def invoke(_request: BaseModel, _context: OperationContext) -> BaseModel:
        nonlocal called
        called = True
        return Response(result="unexpected")

    context = _context()
    policy = TrustedDataPolicyResolver().resolve(None)
    gateway = ControlledDependencyGateway(
        definitions={
            "model.registered": DependencyDefinition(
                dependency_id="model.registered",
                kind="model",
                request_type=Request,
                response_type=Response,
                invoke=invoke,
            )
        },
        declared_ids=frozenset({"model.registered"}),
        context=context,
        policy=policy,
        on_record=records.append,
        sleep_fn=lambda _seconds: None,
    )

    with pytest.raises(SafeExecutionError) as denied:
        gateway.invoke("model.registered", Request(value="SECRET_CONTENT_CANARY"))

    assert denied.value.code == "DATA_POLICY_DENIED"
    assert called is False
    assert len(records) == 1
    record_json = json.dumps(records[0].model_dump(mode="json"))
    assert "SECRET_CONTENT_CANARY" not in record_json
    assert records[0].request.content_json is None
    assert records[0].request.availability == "policy_denied"
    assert records[0].error is not None
    assert records[0].error.code == "DATA_POLICY_DENIED"


def test_gateway_accepts_only_declared_dependencies_and_records_retry_outcomes() -> (
    None
):
    attempts = 0
    records = []
    approved_hash = "sha256:" + "b" * 64
    policy = TrustedDataPolicyResolver(
        {
            "approved-source": TrustedSource(
                classification="synthetic",
                processing_allowed=True,
                egress_allowed=True,
                recording="full",
                export_allowed=True,
                approved_payload_hashes=frozenset({approved_hash}),
            )
        }
    ).resolve("approved-source", payload_hash=approved_hash)

    def invoke(_request: BaseModel, _context: OperationContext) -> BaseModel:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise SafeExecutionError(
                status_code=502,
                code="UPSTREAM_PRIVATE_ERROR",
                category="dependency",
                safe_message="PRIVATE_PROVIDER_BODY_CANARY",
                retryable=True,
                outcome="unknown",
            )
        return Response(result="approved result")

    context = _context()
    gateway = ControlledDependencyGateway(
        definitions={
            "model.declared": DependencyDefinition(
                dependency_id="model.declared",
                kind="model",
                request_type=Request,
                response_type=Response,
                invoke=invoke,
                max_attempts=2,
                sensitive_values=(),
                secret_inventory_complete=True,
                model_identity=ModelIdentity(
                    provider_id="test-provider",
                    model_id="test-model",
                    provider_revision="test-r1",
                    unknown_revision_reason=None,
                    configuration_hash="sha256:" + "e" * 64,
                    prompt=None,
                ),
            )
        },
        declared_ids=frozenset({"model.declared"}),
        context=context,
        policy=policy,
        on_record=records.append,
        sleep_fn=lambda _seconds: None,
    )

    with pytest.raises(SafeExecutionError) as undeclared:
        gateway.invoke("https://arbitrary.example/path", Request(value="x"))
    assert undeclared.value.code == "ACCESS_DENIED"
    assert attempts == 0

    result = gateway.invoke("model.declared", Request(value="approved input"))
    assert result == Response(result="approved result")
    assert attempts == 2
    assert [record.sequence for record in records] == [0, 1]
    assert records[0].error is not None and records[0].error.retryable is True
    assert (
        records[0].error.safe_message
        == "The declared dependency could not be completed."
    )
    assert records[1].response is not None
    assert records[1].duration_ms >= 0
    assert "PRIVATE_PROVIDER_BODY_CANARY" not in json.dumps(
        [record.model_dump(mode="json") for record in records]
    )
    assert len(context.trace_recorder.spans) == 2


def test_runs_query_reserves_response_budget_before_artifact_materialization() -> None:
    reserved = _reserve_artifact_response_bytes(1_000, 8_000)
    assert reserved == 17_002

    with pytest.raises(SafeExecutionError) as oversized:
        _reserve_artifact_response_bytes(1_000, 1_100_000)

    assert oversized.value.code == "LIMIT_EXCEEDED"
    assert oversized.value.status_code == 429
