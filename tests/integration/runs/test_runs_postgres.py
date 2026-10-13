from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath

import httpx
import pytest
from alembic import command
from alfalab.bootstrap.app import ApiSettings, create_app
from alfalab.bootstrap.registry import RegisteredImplementation
from alfalab.bootstrap.runtime import create_execution_runtime
from alfalab.cli import run_cli
from alfalab.common.artifacts import ArtifactStore
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.gateway import DependencyDefinition
from alfalab.modules.runs.storage.database import create_runs_engine
from alfalab.modules.runs.storage.postgres import PostgresRunsRepository
from alfalab.modules.runs.storage.repository import StoredRun
from alfalab_contracts import QueryRunsInput
from alfalab_contracts._generated import Availability
from pydantic import BaseModel
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[3]
TOKEN = "t05-test-token"


class DependencyRequest(BaseModel):
    value: str


class DependencyResponse(BaseModel):
    value: str


def _prepare_request(
    request_id: str, sandbox: str = "t05-sandbox"
) -> dict[str, object]:
    examples = json.loads(
        (ROOT / "docs/specs/framework-v1/contracts/examples.json").read_text(
            encoding="utf-8"
        )
    )["examples"]
    body = next(
        item["request"]
        for item in examples
        if item["operation_id"] == "Documents.prepare"
    )
    text_value = f"T05_PRIVATE_CANARY_{request_id}"
    body["request_id"] = request_id
    body["sandbox_id"] = sandbox
    body["implementation"] = {
        "id": "real.prepare",
        "version": "1.0.0",
        "parameters": {},
    }
    body["payload"]["material"]["text"] = text_value
    body["payload"]["material"]["content_hash"] = (
        "sha256:" + hashlib.sha256(text_value.encode()).hexdigest()
    )
    return body


def _query_request(
    run_ids: list[str], sandbox: str = "t05-sandbox"
) -> dict[str, object]:
    fixture = json.loads(
        (ROOT / "fixtures/approved/Runs.query/successful-run/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    body = fixture["request"]
    body["request_id"] = "t05-runs-query"
    body["sandbox_id"] = sandbox
    body["payload"].update(
        {
            "run_ids": run_ids,
            "operation_id": "Documents.prepare",
            "scenario_id": None,
            "include_artifacts": True,
            "limit": 100,
            "cursor": None,
        }
    )
    return body


def _settings(database_url: str, artifact_root: Path) -> ApiSettings:
    return ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id="t05-test-actor",
        tenant_id="t05-test-tenant",
        allowed_sandboxes=frozenset({"t05-sandbox"}),
        playground_origins=("http://127.0.0.1:5173",),
        runs_database_url=database_url,
        artifact_root=artifact_root,
    )


def _post(app, path: str, body: object):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                path,
                json=body,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    return asyncio.run(send())


def test_runs_migrations_upgrade_downgrade_upgrade(runs_migration_config) -> None:
    command.downgrade(runs_migration_config, "base")
    command.upgrade(runs_migration_config, "head")
    admin_dsn = os.environ["ALFALAB_RUNS_MIGRATION_DATABASE_URL"]
    engine = create_engine(admin_dsn, pool_pre_ping=True, echo=False)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT to_regclass('runs.runs')")).scalar_one()
                == "runs.runs"
            )
    finally:
        engine.dispose()


def test_runs_query_persists_http_and_cli_runs_and_does_not_record_unknown_content(
    runs_database_url: str,
    runs_artifact_root: Path,
) -> None:
    settings = _settings(runs_database_url, runs_artifact_root)
    runtime = create_execution_runtime(
        "testing",
        runs_database_url=runs_database_url,
        artifact_root=runs_artifact_root,
    )
    cli_body = _prepare_request("t05-cli-run")
    external_call: list[bool] = []
    runtime.registry.dependencies["model.private"] = DependencyDefinition(
        dependency_id="model.private",
        kind="model",
        request_type=DependencyRequest,
        response_type=DependencyResponse,
        invoke=lambda _request, _context: (
            external_call.append(True) or DependencyResponse(value="unexpected")
        ),
    )
    original = runtime.registry.implementations[
        ("Documents.prepare", "real.prepare", "1.0.0")
    ]

    def execute_with_policy_probe(payload, context, /):
        try:
            context.dependency_gateway.invoke(
                "model.private",
                DependencyRequest(value="T05_EGRESS_PRIVATE_CANARY"),
            )
        except SafeExecutionError as exc:
            assert exc.code == "DATA_POLICY_DENIED"
        return original.execute(payload, context)

    runtime.registry.implementations[("Documents.prepare", "real.prepare", "1.0.0")] = (
        RegisteredImplementation(
            id=original.id,
            version=original.version,
            kind=original.kind,
            parameter_type=original.parameter_type,
            payload_type=original.payload_type,
            output_type=original.output_type,
            execute=execute_with_policy_probe,
            configuration=original.configuration,
            dependency_ids=frozenset({"model.private"}),
        )
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        exit_code = run_cli(
            ["prepare"],
            stdin=io.StringIO(json.dumps(cli_body, ensure_ascii=False)),
            stdout=stdout,
            stderr=stderr,
            settings=settings,
            runtime=runtime,
        )
        assert exit_code == 0, stderr.getvalue()
        cli_run_id = json.loads(stdout.getvalue())["meta"]["run_id"]
        assert external_call == []
    finally:
        runtime.close()

    app = create_app(settings)
    try:
        http_result = _post(
            app, "/api/v1/documents/prepare", _prepare_request("t05-http-run")
        )
        assert http_result.status_code == 200, http_result.text
        http_run_id = http_result.json()["meta"]["run_id"]

        query_result = _post(
            app,
            "/api/v1/runs/query",
            _query_request([cli_run_id, http_run_id]),
        )
        assert query_result.status_code == 200, query_result.text
        records = query_result.json()["payload"]["runs"]
        assert {record["run_id"] for record in records} == {cli_run_id, http_run_id}
        assert all(record["status"] == "success" for record in records)
        assert all(record["input"]["content_json"] is None for record in records)
        assert all(record["output"]["content_json"] is None for record in records)
        assert all(
            record["input"]["availability"] == "metadata_only" for record in records
        )
        cli_record = next(
            record for record in records if record["run_id"] == cli_run_id
        )
        assert cli_record["dependencies"][0]["error"]["code"] == "DATA_POLICY_DENIED"
    finally:
        app.state.execution_runtime.close()

    # Inspect using the scoped owner role. Raw canaries are absent from JSONB and artifact storage.
    engine = create_runs_engine(runs_database_url)
    repository = PostgresRunsRepository(
        engine, environment="testing", artifact_root=runs_artifact_root
    )
    try:
        assert (
            repository.get(
                http_run_id, tenant_id="t05-test-tenant", sandbox_id="t05-sandbox"
            )
            is not None
        )
        assert (
            repository.get(
                http_run_id, tenant_id="another-tenant", sandbox_id="t05-sandbox"
            )
            is None
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT set_config('alfalab.tenant_id', :tenant_id, true), set_config('alfalab.sandbox_id', :sandbox_id, true)"
                ),
                {"tenant_id": "t05-test-tenant", "sandbox_id": "t05-sandbox"},
            )
            artifacts = (
                connection.execute(
                    text(
                        "SELECT storage_key FROM runs.artifacts WHERE tenant_id=:tenant_id AND sandbox_id=:sandbox_id"
                    ),
                    {"tenant_id": "t05-test-tenant", "sandbox_id": "t05-sandbox"},
                )
                .scalars()
                .all()
            )
            records_json = (
                connection.execute(
                    text(
                        "SELECT record_json::text FROM runs.runs WHERE tenant_id=:tenant_id AND sandbox_id=:sandbox_id"
                    ),
                    {"tenant_id": "t05-test-tenant", "sandbox_id": "t05-sandbox"},
                )
                .scalars()
                .all()
            )
            dependency_json = (
                connection.execute(
                    text(
                        "SELECT dependency_json::text FROM runs.dependencies WHERE tenant_id=:tenant_id AND sandbox_id=:sandbox_id"
                    ),
                    {"tenant_id": "t05-test-tenant", "sandbox_id": "t05-sandbox"},
                )
                .scalars()
                .all()
            )
        assert all(storage_key is None for storage_key in artifacts)
        serialized = "".join([*records_json, *dependency_json])
        assert "T05_PRIVATE_CANARY" not in serialized
        assert "T05_EGRESS_PRIVATE_CANARY" not in serialized
    finally:
        repository.close()


def test_approved_fixture_artifacts_are_local_and_query_is_metadata_only_by_default(
    runs_database_url: str,
    runs_artifact_root: Path,
) -> None:
    settings = _settings(runs_database_url, runs_artifact_root)
    fixture = json.loads(
        (
            ROOT / "fixtures/approved/Documents.prepare/normalize/manifest.json"
        ).read_text(encoding="utf-8")
    )
    body = fixture["request"]
    body["request_id"] = "t05-approved-run"
    body["sandbox_id"] = "t05-sandbox"
    assert body["payload"]["material"]["material_id"] == "fixture-radio-news"

    app = create_app(settings)
    try:
        prepared = _post(app, "/api/v1/documents/prepare", body)
        assert prepared.status_code == 200, prepared.text
        run_id = prepared.json()["meta"]["run_id"]
        assert prepared.json()["meta"]["data_policy"]["classification"] == "synthetic"

        query_body = _query_request([run_id])
        query_body["payload"]["include_artifacts"] = False
        metadata = _post(app, "/api/v1/runs/query", query_body)
        assert metadata.status_code == 200, metadata.text
        metadata_record = metadata.json()["payload"]["runs"][0]
        assert metadata_record["input"]["content_json"] is None
        assert metadata_record["input"]["availability"] == "metadata_only"

        query_body["payload"]["include_artifacts"] = True
        full = _post(app, "/api/v1/runs/query", query_body)
        assert full.status_code == 200, full.text
        full_record = full.json()["payload"]["runs"][0]
        assert full_record["input"]["availability"] == "available"
        assert full_record["input"]["content_json"] is not None
        assert full_record["input"]["content_json"] == json.dumps(
            body["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    finally:
        app.state.execution_runtime.close()

    engine = create_runs_engine(runs_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT set_config('alfalab.tenant_id', :tenant_id, true), set_config('alfalab.sandbox_id', :sandbox_id, true)"
                ),
                {"tenant_id": "t05-test-tenant", "sandbox_id": "t05-sandbox"},
            )
            rows = (
                connection.execute(
                    text(
                        "SELECT artifact_hash, storage_key FROM runs.artifacts WHERE run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .all()
            )
            columns = (
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema='runs' AND table_name='artifacts'"
                    )
                )
                .scalars()
                .all()
            )
        assert "content_json" not in columns
        content_keys = [
            row["storage_key"] for row in rows if row["storage_key"] is not None
        ]
        assert content_keys
        for key in content_keys:
            path = runs_artifact_root.joinpath(*PurePosixPath(key).parts)
            assert path.is_file()
            assert "T05_PRIVATE_CANARY" not in path.read_text(encoding="utf-8")
    finally:
        engine.dispose()


def test_runs_query_rejects_over_budget_before_reading_artifact_files(
    runs_database_url: str,
    runs_artifact_root: Path,
    monkeypatch,
) -> None:
    settings = _settings(runs_database_url, runs_artifact_root)
    fixture = json.loads(
        (
            ROOT / "fixtures/approved/Documents.prepare/normalize/manifest.json"
        ).read_text(encoding="utf-8")
    )
    body = fixture["request"]
    body["request_id"] = "t05-large-source"
    body["sandbox_id"] = "t05-sandbox"
    app = create_app(settings)
    try:
        response = _post(app, "/api/v1/documents/prepare", body)
        assert response.status_code == 200, response.text
        source_run_id = response.json()["meta"]["run_id"]
    finally:
        app.state.execution_runtime.close()

    repository = PostgresRunsRepository(
        create_runs_engine(runs_database_url),
        environment="testing",
        artifact_root=runs_artifact_root,
    )
    try:
        source = repository.get(
            source_run_id,
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
        )
        assert source is not None and source.record.input is not None
        record = source.record.model_copy(deep=True)
        content_json = json.dumps(
            {"large": "x" * 1_100_000},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = content_json.encode("utf-8")
        artifact_hash = "sha256:" + hashlib.sha256(encoded).hexdigest()
        input_view = record.input
        record.input = input_view.model_copy(
            update={
                "ref": input_view.ref.model_copy(
                    update={
                        "artifact_id": "t05-over-budget-artifact",
                        "hash": artifact_hash,
                        "size_bytes": len(encoded),
                    }
                ),
                "content_json": content_json,
                "availability": Availability.available,
            }
        )
        record.run_id = "t05-over-budget-run"
        repository.write(
            StoredRun(
                tenant_id=source.tenant_id,
                sandbox_id=source.sandbox_id,
                record=record,
                input_hash=source.input_hash,
                started_at=source.started_at,
                updated_at=source.updated_at,
                writer_status=source.writer_status,
            )
        )

        read_calls: list[str] = []
        original_read = ArtifactStore.read_json

        def tracked_read(self, scope, artifact_hash, **kwargs):
            read_calls.append(artifact_hash)
            return original_read(
                self,
                scope,
                artifact_hash,
                **kwargs,
            )

        monkeypatch.setattr(ArtifactStore, "read_json", tracked_read)
        payload = QueryRunsInput.model_validate(
            _query_request(["t05-over-budget-run"])["payload"]
        )
        with pytest.raises(SafeExecutionError) as oversized:
            repository.query(
                payload,
                tenant_id="t05-test-tenant",
                sandbox_id="t05-sandbox",
                exclude_run_id="t05-query-run",
                include_artifacts=True,
            )
        assert oversized.value.code == "LIMIT_EXCEEDED"
        assert read_calls == []
    finally:
        repository.close()
