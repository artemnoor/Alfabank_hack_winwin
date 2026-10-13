from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alfalab.bootstrap.app import ApiSettings, create_app, get_trusted_principal
from alfalab.bootstrap.registry import RegisteredImplementation
from alfalab.cli import run_cli
from alfalab.execution.context import TrustedPrincipal
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.gateway import DependencyDefinition
from alfalab.execution.policy import TrustedDataPolicyResolver, TrustedSource
from alfalab.execution.recording import canonical_hash
from alfalab_contracts import ModelIdentity
from pydantic import BaseModel

EXAMPLES = (
    Path(__file__).parents[2]
    / "fixtures/approved/Documents.prepare/normalize/manifest.json"
)
RUN_QUERY = (
    Path(__file__).parents[2]
    / "fixtures/approved/Runs.query/successful-run/manifest.json"
)
TOKEN = "test-secret"
CANARY = "T06_REPLAY_INPUT_CANARY"
DEPENDENCY_CANARY = "T06_DEPENDENCY_RESPONSE_CANARY"


class CredentialRequest(BaseModel):
    query: str


class CredentialResponse(BaseModel):
    answer: str


def _settings() -> ApiSettings:
    return ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id="t06-test-actor",
        tenant_id="t06-test-tenant",
        allowed_sandboxes=frozenset({"demo-a", "demo-b"}),
        playground_origins=("http://127.0.0.1:5173",),
    )


def _approved_request() -> dict[str, object]:
    body = json.loads(EXAMPLES.read_text(encoding="utf-8"))["request"]
    body["sandbox_id"] = "demo-a"
    body["request_id"] = f"t06-live-{uuid4().hex}"
    body["implementation"] = {
        "id": "real.prepare",
        "version": "1.0.0",
        "parameters": {},
    }
    return body


def _replay_request(live: dict[str, object], source_run_id: str) -> dict[str, object]:
    body = json.loads(json.dumps(live))
    body["request_id"] = f"t06-replay-{uuid4().hex}"
    body["execution"] = {
        "mode": "replay",
        "recording": "full",
        "source_run_id": source_run_id,
        "strict": True,
        "timeout_ms": 30_000,
    }
    return body


def _post(app, body: object, *, path: str = "/api/v1/documents/prepare"):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                path,
                json=body,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    return asyncio.run(send())


def _install_model_dependency(
    app,
    monkeypatch: pytest.MonkeyPatch,
    *,
    model_identity: ModelIdentity,
) -> list[bool]:
    calls: list[bool] = []
    definition = DependencyDefinition(
        dependency_id="model.replay-probe",
        kind="model",
        request_type=CredentialRequest,
        response_type=CredentialResponse,
        invoke=lambda request, _context: (
            calls.append(True) or CredentialResponse(answer=f"answer:{request.query}")
        ),
        sensitive_values=(),
        secret_inventory_complete=True,
        model_identity=model_identity,
    )
    app.state.registry.dependencies[definition.dependency_id] = definition
    implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
    implementation = app.state.registry.implementations[implementation_key]

    def execute_with_model(payload, context, /):
        context.dependency_gateway.invoke(
            definition.dependency_id, CredentialRequest(query="replay probe")
        )
        return implementation.execute(payload, context)

    monkeypatch.setitem(
        app.state.registry.implementations,
        implementation_key,
        RegisteredImplementation(
            id=implementation.id,
            version=implementation.version,
            kind=implementation.kind,
            parameter_type=implementation.parameter_type,
            payload_type=implementation.payload_type,
            output_type=implementation.output_type,
            execute=execute_with_model,
            configuration=implementation.configuration,
            dependency_ids=frozenset({definition.dependency_id}),
        ),
    )
    return calls


def test_http_live_cli_replay_and_runs_query_share_actual_execution_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live_request = _approved_request()
    live_response = _post(app, live_request)

    assert live_response.status_code == 200
    live_body = live_response.json()
    source_run_id = live_body["meta"]["run_id"]
    source = app.state.runs_writer.get(
        source_run_id, tenant_id="t06-test-tenant", sandbox_id="demo-a"
    )
    assert source is not None
    assert source.record.replay_status == "available"
    original_record_json = source.record.model_dump_json()

    implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
    implementation = app.state.registry.implementations[implementation_key]
    implementation_calls = 0

    def counted_execute(payload, context, /):
        nonlocal implementation_calls
        implementation_calls += 1
        return implementation.execute(payload, context)

    monkeypatch.setitem(
        app.state.registry.implementations,
        implementation_key,
        RegisteredImplementation(
            id=implementation.id,
            version=implementation.version,
            kind=implementation.kind,
            parameter_type=implementation.parameter_type,
            payload_type=implementation.payload_type,
            output_type=implementation.output_type,
            execute=counted_execute,
            configuration=implementation.configuration,
            dependency_ids=implementation.dependency_ids,
        ),
    )

    replay_request = _replay_request(live_request, source_run_id)
    cli_stdout = io.StringIO()
    exit_code = run_cli(
        ["prepare"],
        stdin=io.StringIO(json.dumps(replay_request, ensure_ascii=False)),
        stdout=cli_stdout,
        settings=_settings(),
        runtime=app.state.execution_runtime,
    )

    assert exit_code == 0
    assert implementation_calls == 1
    replay_body = json.loads(cli_stdout.getvalue())
    replay_run_id = replay_body["meta"]["run_id"]
    assert replay_body["meta"]["execution_mode"] == "replay"
    assert replay_run_id != source_run_id
    assert replay_body["payload"] == live_body["payload"]

    replayed = app.state.runs_writer.get(
        replay_run_id, tenant_id="t06-test-tenant", sandbox_id="demo-a"
    )
    assert replayed is not None
    assert replayed.record.manifest.replay_of == source_run_id
    assert replayed.record.replay_status == "available"
    assert source.record.model_dump_json() == original_record_json

    query_manifest = json.loads(RUN_QUERY.read_text(encoding="utf-8"))
    query_request = query_manifest["request"]
    query_request["sandbox_id"] = "demo-a"
    query_request["request_id"] = f"t06-history-{uuid4().hex}"
    query_request["payload"].update(
        {
            "run_ids": [source_run_id, replay_run_id],
            "operation_id": None,
            "scenario_id": None,
            "include_artifacts": False,
            "limit": 10,
            "cursor": None,
        }
    )
    history = _post(app, query_request, path="/api/v1/runs/query")
    assert history.status_code == 200
    history_ids = {row["run_id"] for row in history.json()["payload"]["runs"]}
    assert history_ids == {source_run_id, replay_run_id}
    assert history.json()["meta"]["run_id"] not in history_ids


def test_replay_restores_rng_seed_and_recorded_domain_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live = _approved_request()
    live["execution"]["random_seed"] = 8128
    implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
    implementation = app.state.registry.implementations[implementation_key]
    observations: list[tuple[float, str]] = []

    def observes_deterministic_inputs(payload, context, /):
        observations.append(
            (context.rng.random(), context.domain_clock.now().isoformat())
        )
        return implementation.execute(payload, context)

    monkeypatch.setitem(
        app.state.registry.implementations,
        implementation_key,
        RegisteredImplementation(
            id=implementation.id,
            version=implementation.version,
            kind=implementation.kind,
            parameter_type=implementation.parameter_type,
            payload_type=implementation.payload_type,
            output_type=implementation.output_type,
            execute=observes_deterministic_inputs,
            configuration=implementation.configuration,
            dependency_ids=implementation.dependency_ids,
        ),
    )

    live_response = _post(app, live)
    assert live_response.status_code == 200, live_response.text
    source_run_id = live_response.json()["meta"]["run_id"]
    replay_response = _post(app, _replay_request(live, source_run_id))
    assert replay_response.status_code == 200, replay_response.text
    assert len(observations) == 2
    assert observations[0] == observations[1]

    source = app.state.runs_writer.get(
        source_run_id, tenant_id="t06-test-tenant", sandbox_id="demo-a"
    )
    replayed = app.state.runs_writer.get(
        replay_response.json()["meta"]["run_id"],
        tenant_id="t06-test-tenant",
        sandbox_id="demo-a",
    )
    assert source is not None and replayed is not None
    assert source.record.dependencies[0].port_id == "clock.domain.now"
    assert replayed.record.dependencies[0].substitution == "replay"


def test_secret_dependency_response_never_reaches_http_or_run_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live = _approved_request()
    source_hash = canonical_hash(live["payload"])
    source_id = live["payload"]["material"]["material_id"]
    app.state.execution_runtime.execution_service._policy_resolver = (
        TrustedDataPolicyResolver(
            {
                source_id: TrustedSource(
                    classification="synthetic",
                    processing_allowed=True,
                    egress_allowed=True,
                    recording="full",
                    export_allowed=True,
                    approved_payload_hashes=frozenset({source_hash}),
                )
            }
        )
    )
    implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
    implementation = app.state.registry.implementations[implementation_key]

    adapter_calls = 0

    def secret_adapter(request, _context):
        nonlocal adapter_calls
        adapter_calls += 1
        return CredentialResponse(answer=f"private response: {DEPENDENCY_CANARY}")

    app.state.registry.dependencies["model.credentials"] = DependencyDefinition(
        dependency_id="model.credentials",
        kind="model",
        request_type=CredentialRequest,
        response_type=CredentialResponse,
        invoke=secret_adapter,
        sensitive_values=(DEPENDENCY_CANARY,),
        secret_inventory_complete=True,
        model_identity=ModelIdentity(
            provider_id="test-provider",
            model_id="test-model",
            provider_revision="test-r1",
            unknown_revision_reason=None,
            configuration_hash="sha256:" + "d" * 64,
            prompt=None,
        ),
    )

    def invokes_secret_dependency(payload, context, /):
        context.dependency_gateway.invoke(
            "model.credentials", CredentialRequest(query="test query")
        )
        return implementation.execute(payload, context)

    monkeypatch.setitem(
        app.state.registry.implementations,
        implementation_key,
        RegisteredImplementation(
            id=implementation.id,
            version=implementation.version,
            kind=implementation.kind,
            parameter_type=implementation.parameter_type,
            payload_type=implementation.payload_type,
            output_type=implementation.output_type,
            execute=invokes_secret_dependency,
            configuration=implementation.configuration,
            dependency_ids=frozenset({"model.credentials"}),
        ),
    )

    response = _post(app, live)
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "DEPENDENCY_FAILED"
    assert DEPENDENCY_CANARY not in response.text
    assert response.json()["meta"]["replay_status"] == "available"
    run_id = response.json()["meta"]["run_id"]
    run = app.state.runs_writer.get(
        run_id, tenant_id="t06-test-tenant", sandbox_id="demo-a"
    )
    assert run is not None
    assert run.record.output is None
    assert len(run.record.dependencies) == 1
    assert run.record.dependencies[0].response is None
    assert DEPENDENCY_CANARY not in run.record.model_dump_json()

    replayed_response = _post(app, _replay_request(live, run_id))
    assert replayed_response.status_code == 502, replayed_response.text
    assert replayed_response.json()["error"]["code"] == "DEPENDENCY_FAILED"
    assert replayed_response.json()["meta"]["execution_mode"] == "replay"
    assert DEPENDENCY_CANARY not in replayed_response.text
    assert adapter_calls == 1
    replayed = app.state.runs_writer.get(
        replayed_response.json()["meta"]["run_id"],
        tenant_id="t06-test-tenant",
        sandbox_id="demo-a",
    )
    assert replayed is not None
    assert replayed.record.run_id != run_id
    assert replayed.record.manifest.replay_of == run_id
    assert replayed.record.dependencies[0].substitution == "replay"


def test_changed_model_configuration_rejects_replay_before_adapter_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live = _approved_request()
    source_hash = canonical_hash(live["payload"])
    source_id = live["payload"]["material"]["material_id"]
    app.state.execution_runtime.execution_service._policy_resolver = (
        TrustedDataPolicyResolver(
            {
                source_id: TrustedSource(
                    classification="synthetic",
                    processing_allowed=True,
                    egress_allowed=True,
                    recording="full",
                    export_allowed=True,
                    approved_payload_hashes=frozenset({source_hash}),
                )
            }
        )
    )
    identity = ModelIdentity(
        provider_id="test-provider",
        model_id="test-model",
        provider_revision="test-r1",
        unknown_revision_reason=None,
        configuration_hash="sha256:" + "f" * 64,
        prompt=None,
    )
    calls = _install_model_dependency(app, monkeypatch, model_identity=identity)

    recorded = _post(app, live)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["meta"]["replay_status"] == "available"
    source_run = app.state.runs_writer.get(
        recorded.json()["meta"]["run_id"],
        tenant_id="t06-test-tenant",
        sandbox_id="demo-a",
    )
    assert source_run is not None
    assert source_run.record.manifest.models == [identity]

    definition = app.state.registry.dependencies["model.replay-probe"]
    app.state.registry.dependencies["model.replay-probe"] = DependencyDefinition(
        dependency_id=definition.dependency_id,
        kind=definition.kind,
        request_type=definition.request_type,
        response_type=definition.response_type,
        invoke=definition.invoke,
        sensitive_values=definition.sensitive_values,
        secret_inventory_complete=definition.secret_inventory_complete,
        model_identity=identity.model_copy(
            update={"configuration_hash": "sha256:" + "a" * 64}
        ),
    )
    replayed = _post(app, _replay_request(live, source_run.run_id))

    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"
    assert calls == [True]


def test_unknown_model_revision_is_recorded_but_not_declared_replayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live = _approved_request()
    source_hash = canonical_hash(live["payload"])
    source_id = live["payload"]["material"]["material_id"]
    app.state.execution_runtime.execution_service._policy_resolver = (
        TrustedDataPolicyResolver(
            {
                source_id: TrustedSource(
                    classification="synthetic",
                    processing_allowed=True,
                    egress_allowed=True,
                    recording="full",
                    export_allowed=True,
                    approved_payload_hashes=frozenset({source_hash}),
                )
            }
        )
    )
    identity = ModelIdentity(
        provider_id="test-provider",
        model_id="test-model",
        provider_revision=None,
        unknown_revision_reason="provider does not expose a pinned revision",
        configuration_hash="sha256:" + "f" * 64,
        prompt=None,
    )
    calls = _install_model_dependency(app, monkeypatch, model_identity=identity)

    recorded = _post(app, live)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["meta"]["replay_status"] == "unavailable"
    source_run = app.state.runs_writer.get(
        recorded.json()["meta"]["run_id"],
        tenant_id="t06-test-tenant",
        sandbox_id="demo-a",
    )
    assert source_run is not None
    assert source_run.record.manifest.models == [identity]

    replayed = _post(app, _replay_request(live, source_run.run_id))
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"
    assert calls == [True]


def test_replay_rejects_unknown_metadata_only_t05_style_input() -> None:
    app = create_app(_settings())
    live = _approved_request()
    text = CANARY
    live["payload"]["material"]["text"] = text
    live["payload"]["material"]["content_hash"] = (
        "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    )
    response = _post(app, live)
    assert response.status_code == 200
    source_id = response.json()["meta"]["run_id"]
    assert response.json()["meta"]["replay_status"] == "unavailable"

    replay = _post(app, _replay_request(live, source_id))
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"
    assert CANARY not in replay.text


def test_replay_rejects_changed_input_configuration_scope_and_tampered_artifact() -> (
    None
):
    app = create_app(_settings())
    live = _approved_request()
    response = _post(app, live)
    assert response.status_code == 200
    source_id = response.json()["meta"]["run_id"]

    changed_input = _replay_request(live, source_id)
    changed_text = "different but valid replay payload"
    changed_input["payload"]["material"]["text"] = changed_text
    changed_input["payload"]["material"]["content_hash"] = (
        "sha256:" + hashlib.sha256(changed_text.encode("utf-8")).hexdigest()
    )
    changed_response = _post(app, changed_input)
    assert changed_response.status_code == 409
    assert changed_response.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"

    changed_config = _replay_request(live, source_id)
    changed_config["implementation"] = {
        "id": "mock.baseline",
        "version": "1.0.0",
        "parameters": {"scenario": "default"},
    }
    config_response = _post(app, changed_config)
    assert config_response.status_code == 409
    assert config_response.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"

    wrong_scope = _replay_request(live, source_id)
    wrong_scope["sandbox_id"] = "demo-b"
    scope_response = _post(app, wrong_scope)
    assert scope_response.status_code == 409
    assert scope_response.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"

    source = app.state.runs_writer.get(
        source_id, tenant_id="t06-test-tenant", sandbox_id="demo-a"
    )
    assert source is not None and source.record.input is not None
    source.record.input.content_json = '{"tampered":"' + CANARY + '"}'
    tampered_response = _post(app, _replay_request(live, source_id))
    assert tampered_response.status_code == 409
    assert tampered_response.json()["error"]["code"] == "REPLAY_MISS"
    assert CANARY not in tampered_response.text


@pytest.mark.parametrize("field", ["analytical_time", "random_seed"])
def test_replay_rejects_manifest_time_or_seed_disagreement(field: str) -> None:
    app = create_app(_settings())
    live = _approved_request()
    recorded = _post(app, live)
    assert recorded.status_code == 200, recorded.text
    source_id = recorded.json()["meta"]["run_id"]
    source = app.state.runs_writer.get(
        source_id, tenant_id="t06-test-tenant", sandbox_id="demo-a"
    )
    assert source is not None
    if field == "analytical_time":
        source.record.analytical_time = "2026-10-13T09:41:00Z"
    else:
        source.record.random_seed += 1

    replayed = _post(app, _replay_request(live, source_id))
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"


def test_replay_rejects_unused_cassette_when_implementation_fails_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live = _approved_request()
    source_hash = canonical_hash(live["payload"])
    source_id = live["payload"]["material"]["material_id"]
    app.state.execution_runtime.execution_service._policy_resolver = (
        TrustedDataPolicyResolver(
            {
                source_id: TrustedSource(
                    classification="synthetic",
                    processing_allowed=True,
                    egress_allowed=True,
                    recording="full",
                    export_allowed=True,
                    approved_payload_hashes=frozenset({source_hash}),
                )
            }
        )
    )
    adapter_calls = _install_model_dependency(
        app,
        monkeypatch,
        model_identity=ModelIdentity(
            provider_id="test-provider",
            model_id="test-model",
            provider_revision="test-r1",
            unknown_revision_reason=None,
            configuration_hash="sha256:" + "e" * 64,
            prompt=None,
        ),
    )
    recorded = _post(app, live)
    assert recorded.status_code == 200, recorded.text
    source_run_id = recorded.json()["meta"]["run_id"]

    implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
    implementation = app.state.registry.implementations[implementation_key]

    def fail_before_dependency_call(_payload, _context, /):
        raise SafeExecutionError(
            status_code=502,
            code="DEPENDENCY_FAILED",
            category="dependency",
            safe_message="Recorded execution diverged.",
        )

    monkeypatch.setitem(
        app.state.registry.implementations,
        implementation_key,
        RegisteredImplementation(
            id=implementation.id,
            version=implementation.version,
            kind=implementation.kind,
            parameter_type=implementation.parameter_type,
            payload_type=implementation.payload_type,
            output_type=implementation.output_type,
            execute=fail_before_dependency_call,
            configuration=implementation.configuration,
            dependency_ids=implementation.dependency_ids,
        ),
    )

    replayed = _post(app, _replay_request(live, source_run_id))
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "REPLAY_MISS"
    assert adapter_calls == [True]


def test_replay_policy_is_checked_before_artifact_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live = _approved_request()
    recorded = _post(app, live)
    assert recorded.status_code == 200, recorded.text
    source_id = recorded.json()["meta"]["run_id"]

    artifact_reads = 0
    read_artifacts = app.state.runs_writer.read_replay_artifacts

    def count_reads(*args, **kwargs):
        nonlocal artifact_reads
        artifact_reads += 1
        return read_artifacts(*args, **kwargs)

    monkeypatch.setattr(app.state.runs_writer, "read_replay_artifacts", count_reads)
    app.state.execution_runtime.execution_service._policy_resolver = (
        TrustedDataPolicyResolver()
    )

    replayed = _post(app, _replay_request(live, source_id))
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"
    assert artifact_reads == 0


def test_replay_rejects_cross_tenant_source_before_artifact_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    live = _approved_request()
    recorded = _post(app, live)
    assert recorded.status_code == 200, recorded.text
    source_id = recorded.json()["meta"]["run_id"]

    artifact_reads = 0
    read_artifacts = app.state.runs_writer.read_replay_artifacts

    def count_reads(*args, **kwargs):
        nonlocal artifact_reads
        artifact_reads += 1
        return read_artifacts(*args, **kwargs)

    monkeypatch.setattr(app.state.runs_writer, "read_replay_artifacts", count_reads)
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        actor_id="different-tenant-actor",
        tenant_id="different-tenant",
        role="developer",
        allowed_sandboxes=frozenset({"demo-a"}),
        permissions=frozenset({"Documents.prepare", "Runs.query"}),
    )

    replayed = _post(app, _replay_request(live, source_id))
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"
    assert artifact_reads == 0


def test_runs_query_replay_fails_closed_without_owner_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(_settings())
    query = json.loads(RUN_QUERY.read_text(encoding="utf-8"))["request"]
    query["sandbox_id"] = "demo-a"
    query["request_id"] = f"t06-query-replay-{uuid4().hex}"
    query["execution"] = {
        "mode": "replay",
        "recording": "full",
        "source_run_id": uuid4().hex,
        "strict": True,
        "timeout_ms": 30_000,
    }

    source_lookups = 0
    get_run = app.state.runs_writer.get

    def count_source_lookups(*args, **kwargs):
        nonlocal source_lookups
        source_lookups += 1
        return get_run(*args, **kwargs)

    monkeypatch.setattr(app.state.runs_writer, "get", count_source_lookups)
    response = _post(app, query, path="/api/v1/runs/query")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"
    assert source_lookups == 0


def test_policy_resolves_processing_egress_recording_and_export_independently() -> None:
    approved_hash = "sha256:" + "1" * 64
    public = TrustedDataPolicyResolver(
        {
            "public-source": TrustedSource(
                classification="public",
                processing_allowed=True,
                egress_allowed=False,
                recording="full",
                export_allowed=False,
                approved_payload_hashes=frozenset({approved_hash}),
            )
        }
    ).resolve("public-source", payload_hash=approved_hash)
    assert public.processing_allowed is True
    assert public.egress_allowed is False
    assert public.full_recording_allowed is True
    assert public.export_allowed is False

    export_without_recording = TrustedDataPolicyResolver(
        {
            "metadata-source": TrustedSource(
                classification="public",
                processing_allowed=True,
                egress_allowed=False,
                recording="metadata_only",
                export_allowed=True,
                approved_payload_hashes=frozenset({approved_hash}),
            )
        }
    ).resolve("metadata-source", payload_hash=approved_hash)
    assert export_without_recording.full_recording_allowed is False
    assert export_without_recording.export_allowed is True

    secret = TrustedDataPolicyResolver(
        {
            "secret-source": TrustedSource(
                classification="secret",
                processing_allowed=True,
                egress_allowed=True,
                recording="full",
                export_allowed=True,
                approved_payload_hashes=frozenset({approved_hash}),
            )
        }
    ).resolve("secret-source", payload_hash=approved_hash)
    assert secret.processing_allowed is False
    assert secret.egress_allowed is False
    assert secret.full_recording_allowed is False
    assert secret.export_allowed is False
    assert secret.decision.classification == "unknown"
    assert secret.decision.reason_codes == ["SECRET_DATA_DENIED"]

    closed = TrustedDataPolicyResolver(
        {
            "closed-source": TrustedSource(
                classification="closed",
                processing_allowed=True,
                egress_allowed=True,
                recording="full",
                export_allowed=True,
                approved_payload_hashes=frozenset({approved_hash}),
            )
        }
    ).resolve("closed-source", payload_hash=approved_hash)
    assert closed.processing_allowed is False
    assert closed.egress_allowed is False
    assert closed.full_recording_allowed is False
    assert closed.export_allowed is False
    assert closed.decision.classification == "unknown"
    assert closed.decision.reason_codes == ["CLOSED_DATA_DENIED"]
