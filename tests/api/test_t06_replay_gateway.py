from __future__ import annotations

import random
from datetime import UTC, datetime
from threading import Event

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
from alfalab.execution.recording import artifact_view, canonical_json, hash_text
from alfalab.execution.replay import (
    ReplayCassette,
    ReplayDependencyGateway,
    cassette_replayable,
)
from alfalab.execution.sequence import DependencySequence
from alfalab.execution.tracing import InMemoryTraceRecorder
from alfalab_contracts import DependencyRecord, ModelIdentity
from pydantic import BaseModel, create_model


class DependencyRequest(BaseModel):
    query: str


class DependencyResponse(BaseModel):
    answer: str


class CredentialRequest(BaseModel):
    query: str
    api_token: str


class CredentialResponse(BaseModel):
    answer: str
    access_token: str


class TokenListResponse(BaseModel):
    answer: str
    tokens: list[str]


def _context(run_id: str) -> OperationContext:
    principal = TrustedPrincipal(
        actor_id="replay-test-actor",
        tenant_id="replay-test-tenant",
        role="developer",
        allowed_sandboxes=frozenset({"replay-test-sandbox"}),
        permissions=frozenset({"Documents.prepare"}),
    )
    return OperationContext(
        principal=principal,
        tenant_id=principal.tenant_id,
        sandbox_id="replay-test-sandbox",
        environment="testing",
        run_id=run_id,
        operation_id="Documents.prepare",
        request_id=f"request-{run_id}",
        contract_version="1.0.0",
        idempotency_key=None,
        implementation_id="real.prepare",
        implementation_version="1.0.0",
        implementation_configuration_hash="sha256:" + "1" * 64,
        analytical_clock=FixedAnalyticalClock(datetime(2026, 10, 13, tzinfo=UTC)),
        rng=random.Random(73),
        artifact_reader=DISABLED_ARTIFACT_READER,
        evidence_reader=DISABLED_EVIDENCE_READER,
        dependency_gateway=DISABLED_DEPENDENCY_GATEWAY,
        trace_recorder=InMemoryTraceRecorder(),
        cancellation_event=Event(),
        limits=ExecutionLimits(max_attempts=3),
    )


def _policy():
    payload_hash = "sha256:" + "b" * 64
    return TrustedDataPolicyResolver(
        {
            "approved": TrustedSource(
                classification="synthetic",
                processing_allowed=True,
                egress_allowed=True,
                recording="full",
                export_allowed=True,
                approved_payload_hashes=frozenset({payload_hash}),
            )
        }
    ).resolve("approved", payload_hash=payload_hash)


def _definition(
    invoke, *, sensitive_values: tuple[str, ...] = ()
) -> DependencyDefinition:
    return DependencyDefinition(
        dependency_id="model.test",
        kind="model",
        request_type=DependencyRequest,
        response_type=DependencyResponse,
        invoke=invoke,
        max_attempts=2,
        sensitive_values=sensitive_values,
        secret_inventory_complete=True,
        model_identity=_model_identity(),
    )


def _model_identity(
    *, configuration_hash: str = "sha256:" + "c" * 64, revision: str | None = "test-r1"
) -> ModelIdentity:
    return ModelIdentity(
        provider_id="test-provider",
        model_id="test-model",
        provider_revision=revision,
        unknown_revision_reason=(
            "provider revision is not exposed" if revision is None else None
        ),
        configuration_hash=configuration_hash,
        prompt=None,
    )


def test_recorded_attempts_replay_in_order_without_invoking_live_adapter() -> None:
    live_attempts = 0
    live_records = []

    def live_invoke(
        request: DependencyRequest, _context: OperationContext
    ) -> DependencyResponse:
        nonlocal live_attempts
        live_attempts += 1
        if live_attempts == 1:
            raise SafeExecutionError(
                status_code=502,
                code="PRIVATE_PROVIDER_ERROR",
                category="dependency",
                safe_message="PRIVATE_PROVIDER_CANARY",
                retryable=True,
                outcome="unknown",
            )
        return DependencyResponse(answer=f"answered:{request.query}")

    live_context = _context("source-run")
    live_gateway = ControlledDependencyGateway(
        definitions={"model.test": _definition(live_invoke)},
        declared_ids=frozenset({"model.test"}),
        context=live_context,
        policy=_policy(),
        on_record=live_records.append,
        sleep_fn=lambda _delay: None,
        sequence=DependencySequence(),
    )
    original_result = live_gateway.invoke(
        "model.test", DependencyRequest(query="approved query")
    )

    assert original_result == DependencyResponse(answer="answered:approved query")
    assert len(live_records) == 2
    assert [item.sequence for item in live_records] == [0, 1]
    assert not cassette_replayable(
        live_records, {"model.test": None}
    )  # incomplete secret inventory
    assert (
        live_records[0].request.ref.artifact_id
        != live_records[1].request.ref.artifact_id
    )
    assert "PRIVATE_PROVIDER_CANARY" not in str(live_records[0].model_dump(mode="json"))

    replay_calls = 0

    def forbidden_live_invoke(
        _request: DependencyRequest, _context: OperationContext
    ) -> DependencyResponse:
        nonlocal replay_calls
        replay_calls += 1
        raise AssertionError("replay must never invoke the live dependency adapter")

    replay_context = _context("replay-run")
    replay_sequence = DependencySequence()
    replay_records = []
    cassette = ReplayCassette(
        source_run_id="source-run",
        entries=live_records,
        context=replay_context,
        policy=_policy(),
        sequence=replay_sequence,
        on_record=replay_records.append,
    )
    replay_gateway = ReplayDependencyGateway(
        definitions={"model.test": _definition(forbidden_live_invoke)},
        declared_ids=frozenset({"model.test"}),
        context=replay_context,
        cassette=cassette,
        sequence=replay_sequence,
        on_record=replay_records.append,
    )
    replay_result = replay_gateway.invoke(
        "model.test", DependencyRequest(query="approved query")
    )
    cassette.assert_consumed()

    assert replay_result == original_result
    assert replay_calls == 0
    assert [item.sequence for item in replay_records] == [0, 1]
    assert all(item.substitution == "replay" for item in replay_records)
    assert all(item.original_run_id == "source-run" for item in replay_records)


def test_terminal_retryable_dependency_error_replays_the_recorded_attempts() -> None:
    source_records = []
    live_calls = 0

    def retryable_failure(_request, _context):
        nonlocal live_calls
        live_calls += 1
        raise SafeExecutionError(
            status_code=502,
            code="PRIVATE_PROVIDER_ERROR",
            category="dependency",
            safe_message="provider response must not be exposed",
            retryable=True,
            outcome="not_applied",
        )

    live_context = _context("failed-source-run")
    live_gateway = ControlledDependencyGateway(
        definitions={"model.test": _definition(retryable_failure)},
        declared_ids=frozenset({"model.test"}),
        context=live_context,
        policy=_policy(),
        on_record=source_records.append,
        sleep_fn=lambda _delay: None,
    )

    with pytest.raises(SafeExecutionError) as live_failure:
        live_gateway.invoke("model.test", DependencyRequest(query="retry me"))

    assert live_failure.value.code == "DEPENDENCY_FAILED"
    assert live_failure.value.retryable is True
    assert live_failure.value.outcome == "not_applied"
    assert live_calls == 2
    assert len(source_records) == 2
    assert all(
        item.error is not None and item.error.retryable for item in source_records
    )
    assert all(item.error.outcome == "not_applied" for item in source_records)
    assert cassette_replayable(source_records, {"model.test": ()})

    replay_calls = 0

    def forbidden_live_invoke(_request, _context):
        nonlocal replay_calls
        replay_calls += 1
        raise AssertionError("strict replay must not call the live dependency")

    replay_context = _context("failed-replay-run")
    replay_sequence = DependencySequence()
    replay_records = []
    cassette = ReplayCassette(
        source_run_id="failed-source-run",
        entries=source_records,
        context=replay_context,
        policy=_policy(),
        sequence=replay_sequence,
        on_record=replay_records.append,
    )
    replay_gateway = ReplayDependencyGateway(
        definitions={"model.test": _definition(forbidden_live_invoke)},
        declared_ids=frozenset({"model.test"}),
        context=replay_context,
        cassette=cassette,
        sequence=replay_sequence,
        on_record=replay_records.append,
    )

    with pytest.raises(SafeExecutionError) as replay_failure:
        replay_gateway.invoke("model.test", DependencyRequest(query="retry me"))
    cassette.assert_consumed()

    assert replay_failure.value.code == "DEPENDENCY_FAILED"
    assert replay_failure.value.retryable is True
    assert replay_failure.value.outcome == "not_applied"
    assert replay_calls == 0
    assert [item.sequence for item in replay_records] == [0, 1]
    assert all(item.substitution == "replay" for item in replay_records)


@pytest.mark.parametrize("failure", ["missing", "changed_request", "tampered"])
def test_strict_cassette_misses_fail_closed(failure: str) -> None:
    calls = 0
    source_records = []

    def live_invoke(
        request: DependencyRequest, _context: OperationContext
    ) -> DependencyResponse:
        nonlocal calls
        calls += 1
        return DependencyResponse(answer=f"answer:{request.query}")

    live_context = _context("source-run")
    live_gateway = ControlledDependencyGateway(
        definitions={"model.test": _definition(live_invoke)},
        declared_ids=frozenset({"model.test"}),
        context=live_context,
        policy=_policy(),
        on_record=source_records.append,
        sleep_fn=lambda _delay: None,
    )
    live_gateway.invoke("model.test", DependencyRequest(query="approved"))
    entries = [item.model_copy(deep=True) for item in source_records]
    if failure == "missing":
        entries = []
    elif failure == "tampered":
        assert entries[0].response is not None
        entries[0].response.content_json = '{"answer":"tampered"}'

    replay_context = _context("replay-run")
    replay_sequence = DependencySequence()
    replay_records = []
    cassette = ReplayCassette(
        source_run_id="source-run",
        entries=entries,
        context=replay_context,
        policy=_policy(),
        sequence=replay_sequence,
        on_record=replay_records.append,
    )
    replay_gateway = ReplayDependencyGateway(
        definitions={"model.test": _definition(live_invoke)},
        declared_ids=frozenset({"model.test"}),
        context=replay_context,
        cassette=cassette,
        sequence=replay_sequence,
        on_record=replay_records.append,
    )
    request = DependencyRequest(
        query="changed" if failure == "changed_request" else "approved"
    )

    with pytest.raises(SafeExecutionError) as failed:
        replay_gateway.invoke("model.test", request)

    assert failed.value.code == "REPLAY_MISS"
    assert failed.value.category == "replay"
    assert calls == 1
    assert len(replay_records) == 1
    assert replay_records[0].error is not None
    assert replay_records[0].error.code == "REPLAY_MISS"


def test_strict_cassette_rejects_unexpected_unused_entries() -> None:
    source_records = []
    context = _context("source-run")
    gateway = ControlledDependencyGateway(
        definitions={
            "model.test": _definition(
                lambda request, _context: DependencyResponse(answer=request.query)
            )
        },
        declared_ids=frozenset({"model.test"}),
        context=context,
        policy=_policy(),
        on_record=source_records.append,
        sleep_fn=lambda _delay: None,
    )
    gateway.invoke("model.test", DependencyRequest(query="recorded"))

    cassette = ReplayCassette(
        source_run_id="source-run",
        entries=source_records,
        context=_context("replay-run"),
        policy=_policy(),
        sequence=DependencySequence(),
        on_record=lambda _record: None,
    )
    with pytest.raises(SafeExecutionError) as unused:
        cassette.assert_consumed()
    assert unused.value.code == "REPLAY_MISS"


def test_dependency_credentials_are_never_recorded_and_disable_replay() -> None:
    canary = "T06_DEPENDENCY_CREDENTIAL_CANARY"
    records = []
    adapter_calls = 0

    def invoke(request, _context):
        nonlocal adapter_calls
        adapter_calls += 1
        return CredentialResponse(answer=request.query, access_token="unused")

    gateway = ControlledDependencyGateway(
        definitions={
            "model.credentials": DependencyDefinition(
                dependency_id="model.credentials",
                kind="model",
                request_type=CredentialRequest,
                response_type=CredentialResponse,
                invoke=invoke,
                sensitive_values=(canary,),
                secret_inventory_complete=True,
                model_identity=_model_identity(),
            )
        },
        declared_ids=frozenset({"model.credentials"}),
        context=_context("credential-run"),
        policy=_policy(),
        on_record=records.append,
        sleep_fn=lambda _delay: None,
    )

    with pytest.raises(SafeExecutionError) as denied:
        gateway.invoke(
            "model.credentials",
            CredentialRequest(query="approved query", api_token=canary),
        )

    assert denied.value.code == "DATA_POLICY_DENIED"
    assert canary not in denied.value.safe_message
    assert adapter_calls == 0
    assert len(records) == 1
    assert records[0].request.content_json is None
    assert records[0].request.availability == "policy_denied"
    assert records[0].response is None
    assert records[0].error is not None
    assert records[0].error.code == "DATA_POLICY_DENIED"
    assert canary not in str(records[0].model_dump(mode="json"))
    assert not cassette_replayable(records)


def test_dependency_without_registered_secret_scanner_cannot_egress() -> None:
    adapter_calls = 0
    records = []

    def invoke(_request, _context):
        nonlocal adapter_calls
        adapter_calls += 1
        return DependencyResponse(answer="unexpected")

    definition = DependencyDefinition(
        dependency_id="model.test",
        kind="model",
        request_type=DependencyRequest,
        response_type=DependencyResponse,
        invoke=invoke,
    )
    gateway = ControlledDependencyGateway(
        definitions={"model.test": definition},
        declared_ids=frozenset({"model.test"}),
        context=_context("unregistered-secret-policy-run"),
        policy=_policy(),
        on_record=records.append,
        sleep_fn=lambda _delay: None,
    )

    with pytest.raises(SafeExecutionError) as denied:
        gateway.invoke("model.test", DependencyRequest(query="approved"))

    assert denied.value.code == "DATA_POLICY_DENIED"
    assert adapter_calls == 0
    assert len(records) == 1
    assert records[0].request.availability == "policy_denied"
    assert records[0].error is not None
    assert records[0].error.code == "DATA_POLICY_DENIED"


def test_empty_but_incomplete_secret_inventory_cannot_egress() -> None:
    adapter_calls = 0
    records = []

    def invoke(_request, _context):
        nonlocal adapter_calls
        adapter_calls += 1
        return DependencyResponse(answer="unexpected")

    definition = DependencyDefinition(
        dependency_id="model.test",
        kind="model",
        request_type=DependencyRequest,
        response_type=DependencyResponse,
        invoke=invoke,
        sensitive_values=(),
        secret_inventory_complete=False,
        model_identity=_model_identity(),
    )
    gateway = ControlledDependencyGateway(
        definitions={"model.test": definition},
        declared_ids=frozenset({"model.test"}),
        context=_context("incomplete-secret-inventory-run"),
        policy=_policy(),
        on_record=records.append,
        sleep_fn=lambda _delay: None,
    )

    with pytest.raises(SafeExecutionError) as denied:
        gateway.invoke("model.test", DependencyRequest(query="approved"))

    assert denied.value.code == "DATA_POLICY_DENIED"
    assert adapter_calls == 0
    assert len(records) == 1
    assert records[0].request.content_json is None
    assert records[0].request.availability == "policy_denied"


@pytest.mark.parametrize(
    "credential_field",
    [
        "cookie",
        "set_cookie",
        "bearer",
        "session_id",
        "auth",
        "auth_info",
        "auth_key",
        "auth_code",
        "signing_key",
        "encryption_key",
        "passphrase",
        "passcode",
        "pin_code",
    ],
)
def test_common_credential_field_names_block_dependency_egress(
    credential_field: str,
) -> None:
    canary = "T06_COMMON_CREDENTIAL_FIELD_CANARY"
    request_type = create_model(
        f"CredentialNamedRequest_{credential_field}",
        query=(str, ...),
        **{credential_field: (str | None, None)},
    )
    adapter_calls = 0
    records = []

    def invoke(_request, _context):
        nonlocal adapter_calls
        adapter_calls += 1
        return DependencyResponse(answer="unexpected")

    definition = DependencyDefinition(
        dependency_id="model.test",
        kind="model",
        request_type=request_type,
        response_type=DependencyResponse,
        invoke=invoke,
        sensitive_values=(),
        secret_inventory_complete=True,
        model_identity=_model_identity(),
    )
    gateway = ControlledDependencyGateway(
        definitions={"model.test": definition},
        declared_ids=frozenset({"model.test"}),
        context=_context(f"credential-name-{credential_field}-run"),
        policy=_policy(),
        on_record=records.append,
        sleep_fn=lambda _delay: None,
    )

    with pytest.raises(SafeExecutionError) as denied:
        gateway.invoke(
            "model.test",
            request_type(query="approved", **{credential_field: canary}),
        )

    assert denied.value.code == "DATA_POLICY_DENIED"
    assert adapter_calls == 0
    assert len(records) == 1
    assert records[0].request.content_json is None
    assert canary not in str(records[0].model_dump(mode="json"))


def test_author_field_is_not_misclassified_as_authentication_data() -> None:
    request_type = create_model("AuthorRequest", query=(str, ...), author=(str, ...))
    adapter_calls = 0

    def invoke(_request, _context):
        nonlocal adapter_calls
        adapter_calls += 1
        return DependencyResponse(answer="safe")

    gateway = ControlledDependencyGateway(
        definitions={
            "model.test": DependencyDefinition(
                dependency_id="model.test",
                kind="model",
                request_type=request_type,
                response_type=DependencyResponse,
                invoke=invoke,
                sensitive_values=(),
                secret_inventory_complete=True,
                model_identity=_model_identity(),
            )
        },
        declared_ids=frozenset({"model.test"}),
        context=_context("author-field-run"),
        policy=_policy(),
        on_record=lambda _record: None,
        sleep_fn=lambda _delay: None,
    )

    assert gateway.invoke(
        "model.test", request_type(query="approved", author="Ada")
    ) == DependencyResponse(answer="safe")
    assert adapter_calls == 1


def test_registered_secret_in_benign_response_field_is_not_exposed_or_recorded() -> (
    None
):
    canary = "T06_BENIGN_ANSWER_SECRET_CANARY"
    records = []
    adapter_calls = 0

    def invoke(request: DependencyRequest, _context: OperationContext):
        nonlocal adapter_calls
        adapter_calls += 1
        return DependencyResponse(answer=f"model output: {canary}")

    definition = _definition(invoke, sensitive_values=(canary,))
    gateway = ControlledDependencyGateway(
        definitions={"model.test": definition},
        declared_ids=frozenset({"model.test"}),
        context=_context("benign-answer-secret-run"),
        policy=_policy(),
        on_record=records.append,
        sleep_fn=lambda _delay: None,
    )

    with pytest.raises(SafeExecutionError) as denied:
        gateway.invoke("model.test", DependencyRequest(query="approved"))

    assert denied.value.code == "DEPENDENCY_FAILED"
    assert adapter_calls == 1
    assert len(records) == 1
    assert records[0].response is None
    assert records[0].error is not None
    assert canary not in denied.value.safe_message
    assert canary not in str(records[0].model_dump(mode="json"))


def test_tokens_collection_is_treated_as_sensitive_without_registry_value() -> None:
    canary = "T06_TOKENS_FIELD_CANARY"
    records = []
    gateway = ControlledDependencyGateway(
        definitions={
            "model.tokens": DependencyDefinition(
                dependency_id="model.tokens",
                kind="model",
                request_type=DependencyRequest,
                response_type=TokenListResponse,
                invoke=lambda _request, _context: TokenListResponse(
                    answer="safe", tokens=[canary]
                ),
                sensitive_values=(),
                secret_inventory_complete=True,
                model_identity=_model_identity(),
            )
        },
        declared_ids=frozenset({"model.tokens"}),
        context=_context("tokens-field-run"),
        policy=_policy(),
        on_record=records.append,
        sleep_fn=lambda _delay: None,
    )

    with pytest.raises(SafeExecutionError) as denied:
        gateway.invoke("model.tokens", DependencyRequest(query="approved"))

    assert denied.value.code == "DEPENDENCY_FAILED"
    assert len(records) == 1
    assert records[0].response is None
    assert canary not in denied.value.safe_message
    assert canary not in str(records[0].model_dump(mode="json"))


def test_replay_and_replayability_reject_registered_secret_in_answer_field() -> None:
    canary = "T06_LEGACY_BENIGN_FIELD_CANARY"
    request_json = canonical_json({"query": "approved"})
    response_json = canonical_json({"answer": f"output {canary}"})
    source_entry = DependencyRecord(
        sequence=0,
        port_id="model.test",
        kind="model",
        request=artifact_view(
            artifact_id="saved-request",
            schema_id="DependencyRequest",
            value_json=request_json,
            classification="synthetic",
            include_content=True,
        ),
        response=artifact_view(
            artifact_id="saved-response",
            schema_id="DependencyResponse",
            value_json=response_json,
            classification="synthetic",
            include_content=True,
        ),
        error=None,
        duration_ms=1,
        request_hash=hash_text(request_json),
        substitution="live",
        original_run_id=None,
    )
    sensitive_by_port = {"model.test": (canary,)}
    assert not cassette_replayable([source_entry], sensitive_by_port)

    context = _context("secret-answer-replay-run")
    sequence = DependencySequence()
    records = []
    cassette = ReplayCassette(
        source_run_id="source-run",
        entries=[source_entry],
        context=context,
        policy=_policy(),
        sequence=sequence,
        on_record=records.append,
    )
    gateway = ReplayDependencyGateway(
        definitions={
            "model.test": _definition(
                lambda _request, _context: pytest.fail(
                    "replay must never invoke a live adapter"
                ),
                sensitive_values=(canary,),
            )
        },
        declared_ids=frozenset({"model.test"}),
        context=context,
        cassette=cassette,
        sequence=sequence,
        on_record=records.append,
    )

    with pytest.raises(SafeExecutionError) as miss:
        gateway.invoke("model.test", DependencyRequest(query="approved"))

    assert miss.value.code == "REPLAY_MISS"
    assert len(records) == 1
    assert records[0].response is None
    assert canary not in str(records[0].model_dump(mode="json"))


def test_replay_miss_does_not_record_a_credential_bearing_request() -> None:
    canary = "T06_REPLAY_MISS_CREDENTIAL_CANARY"
    context = _context("replay-run")
    sequence = DependencySequence()
    records = []
    cassette = ReplayCassette(
        source_run_id="source-run",
        entries=[],
        context=context,
        policy=_policy(),
        sequence=sequence,
        on_record=records.append,
    )
    gateway = ReplayDependencyGateway(
        definitions={
            "model.credentials": DependencyDefinition(
                dependency_id="model.credentials",
                kind="model",
                request_type=CredentialRequest,
                response_type=CredentialResponse,
                invoke=lambda _request, _context: pytest.fail(
                    "replay must never invoke a live adapter"
                ),
                sensitive_values=(),
                secret_inventory_complete=True,
                model_identity=_model_identity(),
            )
        },
        declared_ids=frozenset({"model.credentials"}),
        context=context,
        cassette=cassette,
        sequence=sequence,
        on_record=records.append,
    )

    with pytest.raises(SafeExecutionError) as miss:
        gateway.invoke(
            "model.credentials",
            CredentialRequest(query="approved", api_token=canary),
        )

    assert miss.value.code == "REPLAY_MISS"
    assert len(records) == 1
    assert records[0].request.content_json is None
    assert records[0].request.availability == "metadata_only"
    assert canary not in str(records[0].model_dump(mode="json"))


def test_legacy_cassette_with_recorded_credentials_is_not_replayable() -> None:
    canary = "T06_LEGACY_CASSETTE_CREDENTIAL_CANARY"
    legacy_record = DependencyRecord(
        sequence=0,
        port_id="model.test",
        kind="model",
        request=artifact_view(
            artifact_id="legacy-request",
            schema_id="DependencyRequest",
            value_json=canonical_json({"query": "approved query"}),
            classification="synthetic",
            include_content=True,
        ),
        response=artifact_view(
            artifact_id="legacy-response",
            schema_id="CredentialResponse",
            value_json=canonical_json({"answer": "approved", "access_token": canary}),
            classification="synthetic",
            include_content=True,
        ),
        error=None,
        duration_ms=0,
        request_hash="sha256:" + "1" * 64,
        substitution="live",
        original_run_id=None,
    )

    assert not cassette_replayable([legacy_record])
