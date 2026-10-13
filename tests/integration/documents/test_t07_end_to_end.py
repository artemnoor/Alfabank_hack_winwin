from __future__ import annotations

import asyncio
import copy
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alfalab.bootstrap.app import ApiSettings, create_app
from alfalab.bootstrap.registry import RegisteredImplementation
from alfalab.bootstrap.runtime import create_execution_runtime
from alfalab.cli import run_cli
from alfalab.execution.gateway import DependencyDefinition
from alfalab.modules.documents.storage.schema import (
    command_receipts,
    documents,
    versions,
)
from alfalab.modules.runs.storage.memory import InMemoryRunsRepository
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_PATH = ROOT / "docs/specs/framework-v1/contracts/examples.json"
TOKEN = "t07-integration-token"


def _example(operation_id: str) -> dict:
    examples = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))["examples"]
    return copy.deepcopy(
        next(
            item["request"] for item in examples if item["operation_id"] == operation_id
        )
    )


def _live_request(operation_id: str, sandbox: str, payload: dict | None = None) -> dict:
    body = _example(operation_id)
    body["request_id"] = f"t07-{uuid4().hex}"
    body["sandbox_id"] = sandbox
    if payload is not None:
        body["payload"] = payload
    return body


def _invoke_http(app, request: dict, path: str) -> dict:
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                path,
                json=request,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    response = asyncio.run(send())
    assert response.status_code == 200, response.text
    return response.json()


def _http_response(app, request: dict, path: str):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                path,
                json=request,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    return asyncio.run(send())


def _invoke_cli(runtime, settings, operation_id: str, request: dict) -> dict:
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = run_cli(
        ["run", operation_id],
        stdin=io.StringIO(json.dumps(request, ensure_ascii=False)),
        stdout=stdout,
        stderr=stderr,
        settings=settings,
        runtime=runtime,
    )
    assert exit_code == 0, stderr.getvalue()
    return json.loads(stdout.getvalue())


def _semantic_fetch_payload(response: dict) -> dict:
    payload = copy.deepcopy(response["payload"])
    for material in payload["materials"]:
        material["provenance"]["producer_run_id"] = None
    return payload


@pytest.mark.parametrize("transport", ["http", "cli"])
def test_sources_prepare_register_read_and_runs_query_share_one_runtime(
    transport: str,
    admin_dsn: str,
    documents_migrated: bool,
    tmp_path: Path,
) -> None:
    del documents_migrated
    settings = ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id=f"t07-actor-{uuid4().hex}",
        tenant_id=f"t07-tenant-{uuid4().hex}",
        allowed_sandboxes=frozenset({"demo-a", "replay-b"}),
        playground_origins=("http://127.0.0.1:5173",),
    )
    runtime = create_execution_runtime(
        "testing",
        runs_repository=InMemoryRunsRepository(),
        documents_database_url=admin_dsn,
        artifact_root=tmp_path / "artifacts",
    )
    app = create_app(settings, execution_runtime=runtime)
    if transport == "http":
        invoke = lambda operation, request, path: _invoke_http(app, request, path)
    else:
        invoke = lambda operation, request, _path: _invoke_cli(
            runtime, settings, operation, request
        )
    try:
        fetch_response = invoke(
            "Sources.fetch",
            _live_request(
                "Sources.fetch",
                "demo-a",
                {
                    "source_id": "synthetic-example",
                    "cursor": None,
                    "since": None,
                    "limit": 2,
                },
            ),
            "/api/v1/sources/fetch",
        )
        fetch_payload = fetch_response["payload"]
        assert len(fetch_payload["materials"]) == 2
        raw = fetch_payload["materials"][0]
        assert raw["provenance"]["producer_run_id"] == fetch_response["meta"]["run_id"]

        prepare_response = invoke(
            "Documents.prepare",
            _live_request(
                "Documents.prepare",
                "demo-a",
                {
                    "material": raw,
                    "normalize_newlines": True,
                    "trim_outer_whitespace": True,
                },
            ),
            "/api/v1/documents/prepare",
        )
        prepared = prepare_response["payload"]["prepared"]
        assert prepared["raw_hash"] == raw["content_hash"]
        assert prepared["material"]["text"] == raw["text"]

        document_id = f"t07-doc-{uuid4().hex}"
        idempotency_key = f"t07-key-{uuid4().hex}"
        register_request = _live_request(
            "Documents.register",
            "demo-a",
            {
                "document_id": document_id,
                "expected_revision": 0,
                "raw": raw,
                "prepared": prepared,
            },
        )
        register_request["idempotency_key"] = idempotency_key
        register_response = invoke(
            "Documents.register", register_request, "/api/v1/documents/register"
        )
        version = register_response["payload"]["version"]
        assert version["ref"]["revision"] == 1
        assert version["raw"]["content_hash"] == raw["content_hash"]
        assert version["prepared"]["prepared_hash"] == prepared["prepared_hash"]
        assert register_response["meta"]["data_policy"]["classification"] == "synthetic"

        read_response = invoke(
            "Documents.read",
            _live_request(
                "Documents.read",
                "demo-a",
                {
                    "query": {
                        "kind": "documents",
                        "document_ids": [document_id],
                        "revision": None,
                        "as_of": None,
                    }
                },
            ),
            "/api/v1/documents/read",
        )
        assert read_response["payload"]["versions"][0]["ref"] == version["ref"]
        assert read_response["payload"]["missing_ids"] == []

        receipt_response = invoke(
            "Documents.read",
            _live_request(
                "Documents.read",
                "demo-a",
                {
                    "query": {
                        "kind": "receipt",
                        "operation_id": "Documents.register",
                        "idempotency_key": idempotency_key,
                    }
                },
            ),
            "/api/v1/documents/read",
        )
        assert (
            receipt_response["payload"]["receipt"]["idempotency_key"] == idempotency_key
        )

        history_response = invoke(
            "Runs.query",
            _live_request(
                "Runs.query",
                "demo-a",
                {
                    "run_ids": [],
                    "operation_id": None,
                    "scenario_id": None,
                    "include_artifacts": False,
                    "limit": 20,
                    "cursor": None,
                },
            ),
            "/api/v1/runs/query",
        )
        history = history_response["payload"]["runs"]
        assert {
            "Sources.fetch",
            "Documents.prepare",
            "Documents.register",
            "Documents.read",
        }.issubset({run["operation_id"] for run in history})
        assert all(run["trace_status"] == "complete" for run in history)
        assert history_response["meta"]["run_id"] not in {
            run["run_id"] for run in history
        }
    finally:
        runtime.close()


def test_sources_fetch_and_prepare_replay_execute_without_live_source_fallback(
    admin_dsn: str,
    documents_migrated: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del documents_migrated
    tenant = f"t07-replay-tenant-{uuid4().hex}"
    settings = ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id=f"t07-actor-{uuid4().hex}",
        tenant_id=tenant,
        allowed_sandboxes=frozenset({"demo-a", "replay-b", "replay-c"}),
        playground_origins=("http://127.0.0.1:5173",),
    )
    runtime = create_execution_runtime(
        "testing",
        runs_repository=InMemoryRunsRepository(),
        documents_database_url=admin_dsn,
        artifact_root=tmp_path / "artifacts",
    )
    app = create_app(settings, execution_runtime=runtime)
    try:
        fetch_request = _live_request(
            "Sources.fetch",
            "demo-a",
            {
                "source_id": "synthetic-example",
                "cursor": None,
                "since": None,
                "limit": 2,
            },
        )
        fetch_live = _invoke_http(app, fetch_request, "/api/v1/sources/fetch")
        source_id = fetch_live["meta"]["run_id"]
        fetch_port = runtime.registry.dependencies["sources.fixture"]
        source_calls: list[bool] = []
        monkeypatch.setitem(
            runtime.registry.dependencies,
            "sources.fixture",
            DependencyDefinition(
                dependency_id=fetch_port.dependency_id,
                kind=fetch_port.kind,
                request_type=fetch_port.request_type,
                response_type=fetch_port.response_type,
                invoke=lambda *_: source_calls.append(True),
                sensitive_values=(),
                secret_inventory_complete=True,
                requires_egress=False,
            ),
        )
        fetch_replay = copy.deepcopy(fetch_request)
        fetch_replay["request_id"] = f"t07-replay-{uuid4().hex}"
        fetch_replay["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": source_id,
            "strict": True,
            "timeout_ms": 30_000,
        }
        replayed_fetch = _invoke_http(app, fetch_replay, "/api/v1/sources/fetch")
        assert source_calls == []
        assert (
            replayed_fetch["payload"]["materials"][0]["text"]
            == fetch_live["payload"]["materials"][0]["text"]
        )
        assert replayed_fetch["meta"]["run_id"] != source_id
        replayed_fetch_run = runtime.runs_repository.get(
            replayed_fetch["meta"]["run_id"], tenant_id=tenant, sandbox_id="demo-a"
        )
        assert replayed_fetch_run.record.manifest.replay_of == source_id

        fetch_cli_replay = copy.deepcopy(fetch_replay)
        fetch_cli_replay["request_id"] = f"t07-cli-replay-{uuid4().hex}"
        cli_replayed_fetch = _invoke_cli(
            runtime, settings, "Sources.fetch", fetch_cli_replay
        )
        assert source_calls == []
        assert _semantic_fetch_payload(cli_replayed_fetch) == _semantic_fetch_payload(
            fetch_live
        )
        assert cli_replayed_fetch["meta"]["run_id"] != source_id
        assert (
            cli_replayed_fetch["payload"]["materials"][0]["provenance"][
                "producer_run_id"
            ]
            == cli_replayed_fetch["meta"]["run_id"]
        )
        cli_replayed_fetch_run = runtime.runs_repository.get(
            cli_replayed_fetch["meta"]["run_id"], tenant_id=tenant, sandbox_id="demo-a"
        )
        assert cli_replayed_fetch_run.record.manifest.replay_of == source_id

        raw, raw_revision_two = fetch_live["payload"]["materials"]
        prepare_request = _live_request(
            "Documents.prepare",
            "demo-a",
            {
                "material": raw,
                "normalize_newlines": True,
                "trim_outer_whitespace": True,
            },
        )
        prepare_request["implementation"] = {
            "id": "real.prepare",
            "version": "1.0.0",
            "parameters": {},
        }
        prepare_live = _invoke_http(app, prepare_request, "/api/v1/documents/prepare")
        prepare_source_id = prepare_live["meta"]["run_id"]
        implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
        implementation = runtime.registry.implementations[implementation_key]
        calls = 0

        def counted(payload, context, /):
            nonlocal calls
            calls += 1
            return implementation.execute(payload, context)

        monkeypatch.setitem(
            runtime.registry.implementations,
            implementation_key,
            RegisteredImplementation(
                id=implementation.id,
                version=implementation.version,
                kind=implementation.kind,
                parameter_type=implementation.parameter_type,
                payload_type=implementation.payload_type,
                output_type=implementation.output_type,
                execute=counted,
                configuration=implementation.configuration,
                dependency_ids=implementation.dependency_ids,
            ),
        )
        prepare_replay = copy.deepcopy(prepare_request)
        prepare_replay["request_id"] = f"t07-replay-{uuid4().hex}"
        prepare_replay["implementation"] = {
            "id": "real.prepare",
            "version": "1.0.0",
            "parameters": {},
        }
        prepare_replay["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": prepare_source_id,
            "strict": True,
            "timeout_ms": 30_000,
        }
        replayed_prepare = _invoke_http(
            app, prepare_replay, "/api/v1/documents/prepare"
        )
        assert calls == 1
        assert replayed_prepare["payload"] == prepare_live["payload"]
        assert replayed_prepare["meta"]["run_id"] != prepare_source_id
        replayed_prepare_run = runtime.runs_repository.get(
            replayed_prepare["meta"]["run_id"], tenant_id=tenant, sandbox_id="demo-a"
        )
        assert replayed_prepare_run.record.manifest.replay_of == prepare_source_id

        prepare_cli_replay = copy.deepcopy(prepare_replay)
        prepare_cli_replay["request_id"] = f"t07-cli-replay-{uuid4().hex}"
        cli_replayed_prepare = _invoke_cli(
            runtime, settings, "Documents.prepare", prepare_cli_replay
        )
        assert calls == 2
        assert cli_replayed_prepare["payload"] == prepare_live["payload"]
        assert cli_replayed_prepare["meta"]["run_id"] != prepare_source_id
        cli_replayed_prepare_run = runtime.runs_repository.get(
            cli_replayed_prepare["meta"]["run_id"],
            tenant_id=tenant,
            sandbox_id="demo-a",
        )
        assert cli_replayed_prepare_run.record.manifest.replay_of == prepare_source_id

        document_id = f"t07-replay-doc-{uuid4().hex}"
        command_key = f"t07-replay-key-{uuid4().hex}"
        register_request = _live_request(
            "Documents.register",
            "demo-a",
            {
                "document_id": document_id,
                "expected_revision": 0,
                "raw": raw,
                "prepared": prepare_live["payload"]["prepared"],
            },
        )
        register_request["idempotency_key"] = command_key
        register_live = _invoke_http(
            app, register_request, "/api/v1/documents/register"
        )
        register_source_id = register_live["meta"]["run_id"]
        assert register_live["meta"]["replay_status"] == "available"

        register_replay_request = copy.deepcopy(register_request)
        register_replay_request["request_id"] = f"t07-replay-{uuid4().hex}"
        register_replay_request["sandbox_id"] = "replay-b"
        register_replay_request["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": register_source_id,
            "strict": True,
            "timeout_ms": 30_000,
        }
        register_replayed = _invoke_http(
            app, register_replay_request, "/api/v1/documents/register"
        )
        assert (
            register_replayed["payload"]["version"]
            == register_live["payload"]["version"]
        )
        register_replayed_run = runtime.runs_repository.get(
            register_replayed["meta"]["run_id"], tenant_id=tenant, sandbox_id="replay-b"
        )
        assert register_replayed_run.record.manifest.replay_of == register_source_id

        revision_two_prepare = _live_request(
            "Documents.prepare",
            "demo-a",
            {
                "material": raw_revision_two,
                "normalize_newlines": True,
                "trim_outer_whitespace": True,
            },
        )
        revision_two_prepare["implementation"] = {
            "id": "real.prepare",
            "version": "1.0.0",
            "parameters": {},
        }
        prepared_revision_two = _invoke_http(
            app, revision_two_prepare, "/api/v1/documents/prepare"
        )["payload"]["prepared"]
        revision_two_key = f"t07-replay-key-{uuid4().hex}"
        revision_two_register = _live_request(
            "Documents.register",
            "demo-a",
            {
                "document_id": document_id,
                "expected_revision": 1,
                "raw": raw_revision_two,
                "prepared": prepared_revision_two,
            },
        )
        revision_two_register["idempotency_key"] = revision_two_key
        revision_two_live = _invoke_http(
            app, revision_two_register, "/api/v1/documents/register"
        )
        assert revision_two_live["payload"]["version"]["ref"]["revision"] == 2

        revision_two_replay = copy.deepcopy(revision_two_register)
        revision_two_replay["request_id"] = f"t07-replay-{uuid4().hex}"
        revision_two_replay["sandbox_id"] = "replay-c"
        revision_two_replay["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": revision_two_live["meta"]["run_id"],
            "strict": True,
            "timeout_ms": 30_000,
        }
        revision_two_replayed = _invoke_http(
            app, revision_two_replay, "/api/v1/documents/register"
        )
        assert (
            revision_two_replayed["payload"]["version"]
            == revision_two_live["payload"]["version"]
        )
        revision_two_replayed_run = runtime.runs_repository.get(
            revision_two_replayed["meta"]["run_id"],
            tenant_id=tenant,
            sandbox_id="replay-c",
        )
        assert (
            revision_two_replayed_run.record.manifest.replay_of
            == revision_two_live["meta"]["run_id"]
        )
        restored_latest = _invoke_http(
            app,
            _live_request(
                "Documents.read",
                "replay-c",
                {
                    "query": {
                        "kind": "documents",
                        "document_ids": [document_id],
                        "revision": None,
                        "as_of": None,
                    }
                },
            ),
            "/api/v1/documents/read",
        )["payload"]["versions"][0]
        assert restored_latest["ref"]["revision"] == 2
        assert restored_latest["parent_ref"]["revision"] == 1
        restored_parent = _invoke_http(
            app,
            _live_request(
                "Documents.read",
                "replay-c",
                {
                    "query": {
                        "kind": "documents",
                        "document_ids": [document_id],
                        "revision": 1,
                        "as_of": None,
                    }
                },
            ),
            "/api/v1/documents/read",
        )["payload"]["versions"][0]
        assert restored_parent["ref"]["revision"] == 1

        read_target_request = _live_request(
            "Documents.read",
            "replay-b",
            {
                "query": {
                    "kind": "documents",
                    "document_ids": [document_id],
                    "revision": None,
                    "as_of": None,
                }
            },
        )
        read_live = _invoke_http(app, read_target_request, "/api/v1/documents/read")
        assert (
            read_live["payload"]["versions"][0]["ref"]
            == register_live["payload"]["version"]["ref"]
        )
        read_source_id = read_live["meta"]["run_id"]

        read_port = runtime.registry.dependencies["documents.read.versions"]
        read_calls: list[bool] = []
        monkeypatch.setitem(
            runtime.registry.dependencies,
            "documents.read.versions",
            DependencyDefinition(
                dependency_id=read_port.dependency_id,
                kind=read_port.kind,
                request_type=read_port.request_type,
                response_type=read_port.response_type,
                invoke=lambda *_: read_calls.append(True),
                sensitive_values=(),
                secret_inventory_complete=True,
                requires_egress=False,
            ),
        )
        read_replay_request = copy.deepcopy(read_target_request)
        read_replay_request["request_id"] = f"t07-replay-{uuid4().hex}"
        read_replay_request["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": read_source_id,
            "strict": True,
            "timeout_ms": 30_000,
        }
        read_replayed = _invoke_http(app, read_replay_request, "/api/v1/documents/read")
        assert read_calls == []
        assert read_replayed["payload"] == read_live["payload"]
        read_replayed_run = runtime.runs_repository.get(
            read_replayed["meta"]["run_id"], tenant_id=tenant, sandbox_id="replay-b"
        )
        assert read_replayed_run.record.manifest.replay_of == read_source_id
    finally:
        runtime.close()


def test_postgres_runs_register_replay_restores_state_and_domain_time(
    documents_runs_database: str,
    tmp_path: Path,
) -> None:
    from datetime import datetime

    from alfalab.common.postgres import psycopg_url
    from alfalab.modules.documents.storage.service import DocumentsStorage
    from alfalab.modules.runs.storage.postgres import PostgresRunsRepository
    from sqlalchemy import create_engine

    tenant = f"t07-pg-replay-tenant-{uuid4().hex}"
    settings = ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id=f"t07-actor-{uuid4().hex}",
        tenant_id=tenant,
        allowed_sandboxes=frozenset({"source-a", "replay-b"}),
        playground_origins=("http://127.0.0.1:5173",),
    )
    runtime = create_execution_runtime(
        "testing",
        runs_database_url=documents_runs_database,
        documents_database_url=documents_runs_database,
        artifact_root=tmp_path / "artifacts",
    )
    assert isinstance(runtime.runs_repository, PostgresRunsRepository)
    assert isinstance(runtime.documents_storage, DocumentsStorage)
    app = create_app(settings, execution_runtime=runtime)
    inspection_engine = create_engine(
        psycopg_url(documents_runs_database), pool_pre_ping=True, echo=False
    )

    def scoped_versions(sandbox_id: str) -> tuple[tuple[object, ...], ...]:
        with inspection_engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        versions.c.revision,
                        versions.c.kind,
                        versions.c.raw_content_hash,
                        versions.c.semantic_hash,
                        versions.c.version_hash,
                        versions.c.parent_revision,
                        versions.c.recorded_at,
                    )
                    .where(
                        versions.c.tenant_id == tenant,
                        versions.c.sandbox_id == sandbox_id,
                    )
                    .order_by(versions.c.revision)
                )
                .mappings()
                .all()
            )
        return tuple(tuple(row.values()) for row in rows)

    def scoped_receipts(sandbox_id: str) -> tuple[tuple[object, ...], ...]:
        with inspection_engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        command_receipts.c.idempotency_key,
                        command_receipts.c.original_run_id,
                        command_receipts.c.receipt_json,
                    )
                    .where(
                        command_receipts.c.tenant_id == tenant,
                        command_receipts.c.sandbox_id == sandbox_id,
                    )
                    .order_by(command_receipts.c.idempotency_key)
                )
                .mappings()
                .all()
            )
        return tuple(tuple(row.values()) for row in rows)

    def recorded_clock(run_id: str, sandbox_id: str) -> datetime:
        stored = runtime.runs_repository.get(
            run_id, tenant_id=tenant, sandbox_id=sandbox_id
        )
        assert stored is not None
        clock_entries = [
            dependency
            for dependency in stored.record.dependencies
            if dependency.port_id == "clock.domain.now"
        ]
        assert len(clock_entries) == 1
        response = clock_entries[0].response
        assert response is not None
        content = runtime.runs_repository.read_replay_artifacts(
            run_id,
            (response.ref,),
            tenant_id=tenant,
            sandbox_id=sandbox_id,
        )
        assert content is not None
        return datetime.fromisoformat(
            json.loads(content[response.ref.artifact_id])["timestamp"]
        )

    try:
        fetch = _invoke_http(
            app,
            _live_request(
                "Sources.fetch",
                "source-a",
                {
                    "source_id": "synthetic-example",
                    "cursor": None,
                    "since": None,
                    "limit": 2,
                },
            ),
            "/api/v1/sources/fetch",
        )
        raw_one, raw_two = fetch["payload"]["materials"]
        prepared = []
        for raw in (raw_one, raw_two):
            prepare_request = _live_request(
                "Documents.prepare",
                "source-a",
                {
                    "material": raw,
                    "normalize_newlines": True,
                    "trim_outer_whitespace": True,
                },
            )
            prepared.append(
                _invoke_http(
                    app,
                    prepare_request,
                    "/api/v1/documents/prepare",
                )["payload"]["prepared"]
            )

        document_id = f"t07-pg-replay-doc-{uuid4().hex}"
        key_one = f"t07-pg-replay-key-one-{uuid4().hex}"
        request_one = _live_request(
            "Documents.register",
            "source-a",
            {
                "document_id": document_id,
                "expected_revision": 0,
                "raw": raw_one,
                "prepared": prepared[0],
            },
        )
        request_one["idempotency_key"] = key_one
        result_one = _invoke_http(app, request_one, "/api/v1/documents/register")
        run_one_id = result_one["meta"]["run_id"]
        source_one = scoped_versions("source-a")
        assert len(source_one) == 1
        assert source_one[0][-1] == recorded_clock(run_one_id, "source-a")

        key_two = f"t07-pg-replay-key-two-{uuid4().hex}"
        request_two = _live_request(
            "Documents.register",
            "source-a",
            {
                "document_id": document_id,
                "expected_revision": 1,
                "raw": raw_two,
                "prepared": prepared[1],
            },
        )
        request_two["idempotency_key"] = key_two
        result_two = _invoke_http(app, request_two, "/api/v1/documents/register")
        source_run_id = result_two["meta"]["run_id"]
        source_before_replay = scoped_versions("source-a")
        source_receipts_before_replay = scoped_receipts("source-a")
        assert [row[0] for row in source_before_replay] == [1, 2]
        assert source_before_replay[1][-1] == recorded_clock(source_run_id, "source-a")
        assert {row[0] for row in source_receipts_before_replay} == {key_one, key_two}

        replay_request = copy.deepcopy(request_two)
        replay_request["request_id"] = f"t07-pg-replay-{uuid4().hex}"
        replay_request["sandbox_id"] = "replay-b"
        replay_request["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": source_run_id,
            "strict": True,
            "timeout_ms": 30_000,
        }
        replayed = _invoke_http(app, replay_request, "/api/v1/documents/register")
        assert replayed["payload"]["version"] == result_two["payload"]["version"]
        replay_run = runtime.runs_repository.get(
            replayed["meta"]["run_id"],
            tenant_id=tenant,
            sandbox_id="replay-b",
        )
        assert replay_run is not None
        assert replay_run.record.manifest.replay_of == source_run_id

        target_latest = _invoke_http(
            app,
            _live_request(
                "Documents.read",
                "replay-b",
                {
                    "query": {
                        "kind": "documents",
                        "document_ids": [document_id],
                        "revision": None,
                        "as_of": None,
                    }
                },
            ),
            "/api/v1/documents/read",
        )["payload"]["versions"][0]
        target_previous = _invoke_http(
            app,
            _live_request(
                "Documents.read",
                "replay-b",
                {
                    "query": {
                        "kind": "documents",
                        "document_ids": [document_id],
                        "revision": 1,
                        "as_of": None,
                    }
                },
            ),
            "/api/v1/documents/read",
        )["payload"]["versions"][0]
        assert target_latest["ref"]["revision"] == 2
        assert target_latest["parent_ref"]["revision"] == 1
        assert target_previous["ref"]["revision"] == 1

        target_rows = scoped_versions("replay-b")
        assert target_rows == source_before_replay
        target_receipts = scoped_receipts("replay-b")
        assert [row[0] for row in target_receipts] == [key_two]
        assert target_receipts[0][1] == replayed["meta"]["run_id"]
        assert scoped_versions("source-a") == source_before_replay
        assert scoped_receipts("source-a") == source_receipts_before_replay

        inaccessible_settings = ApiSettings(
            developer_token=TOKEN,
            environment="testing",
            actor_id=f"t07-actor-{uuid4().hex}",
            tenant_id=tenant,
            allowed_sandboxes=frozenset({"replay-b"}),
            playground_origins=("http://127.0.0.1:5173",),
        )
        inaccessible_app = create_app(inaccessible_settings, execution_runtime=runtime)
        denied = _http_response(
            inaccessible_app, replay_request, "/api/v1/documents/register"
        )
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "REPLAY_INCOMPATIBLE"
        assert scoped_versions("source-a") == source_before_replay
        assert scoped_versions("replay-b") == target_rows
    finally:
        inspection_engine.dispose()
        runtime.close()


def test_register_is_gated_by_history_and_owner_receipt_survives_final_history_failure(
    admin_dsn: str,
    documents_migrated: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del documents_migrated
    tenant = f"t07-history-tenant-{uuid4().hex}"
    settings = ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id=f"t07-actor-{uuid4().hex}",
        tenant_id=tenant,
        allowed_sandboxes=frozenset({"demo-a"}),
        playground_origins=("http://127.0.0.1:5173",),
    )
    runtime = create_execution_runtime(
        "testing",
        runs_repository=InMemoryRunsRepository(),
        documents_database_url=admin_dsn,
        artifact_root=tmp_path / "artifacts",
    )
    app = create_app(settings, execution_runtime=runtime)
    try:
        source = _invoke_http(
            app,
            _live_request(
                "Sources.fetch",
                "demo-a",
                {
                    "source_id": "synthetic-example",
                    "cursor": None,
                    "since": None,
                    "limit": 1,
                },
            ),
            "/api/v1/sources/fetch",
        )
        raw = source["payload"]["materials"][0]
        prepared = _invoke_http(
            app,
            _live_request(
                "Documents.prepare",
                "demo-a",
                {
                    "material": raw,
                    "normalize_newlines": True,
                    "trim_outer_whitespace": True,
                },
            ),
            "/api/v1/documents/prepare",
        )["payload"]["prepared"]
        document_id = f"t07-history-doc-{uuid4().hex}"
        idempotency_key = f"t07-history-key-{uuid4().hex}"
        register_request = _live_request(
            "Documents.register",
            "demo-a",
            {
                "document_id": document_id,
                "expected_revision": 0,
                "raw": raw,
                "prepared": prepared,
            },
        )
        register_request["idempotency_key"] = idempotency_key
        repository = runtime.runs_writer
        original_write = repository.write

        def fail_all_history(record):
            del record
            raise OSError("private history failure")

        monkeypatch.setattr(repository, "write", fail_all_history)
        before = _http_response(app, register_request, "/api/v1/documents/register")
        assert before.status_code == 503
        assert before.json()["error"]["code"] == "HISTORY_UNAVAILABLE"
        assert "private history failure" not in before.text
        with runtime.documents_engine.connect() as connection:
            assert (
                connection.execute(
                    select(documents.c.document_id).where(
                        documents.c.tenant_id == tenant,
                        documents.c.sandbox_id == "demo-a",
                        documents.c.document_id == document_id,
                    )
                ).first()
                is None
            )

        def fail_final_history(record):
            if record.writer_status == "success":
                raise OSError("private final history failure")
            original_write(record)

        monkeypatch.setattr(repository, "write", fail_final_history)
        committed = _http_response(app, register_request, "/api/v1/documents/register")
        assert committed.status_code == 200
        committed_body = committed.json()
        assert committed_body["status"] == "success"
        assert committed_body["meta"]["trace_status"] == "partial"
        original_run_id = committed_body["payload"]["receipt"]["original_run_id"]

        monkeypatch.setattr(repository, "write", original_write)
        retry_request = copy.deepcopy(register_request)
        retry_request["request_id"] = f"t07-retry-{uuid4().hex}"
        recovered = _invoke_http(app, retry_request, "/api/v1/documents/register")
        assert recovered["payload"]["receipt"]["original_run_id"] == original_run_id
        with runtime.documents_engine.connect() as connection:
            assert connection.execute(
                select(versions.c.revision).where(
                    versions.c.tenant_id == tenant,
                    versions.c.sandbox_id == "demo-a",
                    versions.c.document_id == document_id,
                )
            ).all() == [(1,)]
            assert connection.execute(
                select(command_receipts.c.idempotency_key).where(
                    command_receipts.c.tenant_id == tenant,
                    command_receipts.c.sandbox_id == "demo-a",
                    command_receipts.c.idempotency_key == idempotency_key,
                )
            ).all() == [(idempotency_key,)]
    finally:
        runtime.close()
