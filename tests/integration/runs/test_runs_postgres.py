from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Event

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
from alfalab.execution.policy import TrustedDataPolicyResolver, TrustedSource
from alfalab.execution.recording import canonical_hash
from alfalab.modules.runs.storage.database import create_runs_engine
from alfalab.modules.runs.storage.postgres import PostgresRunsRepository
from alfalab.modules.runs.storage.repository import StoredRun
from alfalab_contracts import (
    DependencyRecord,
    ErrorInfo,
    ModelIdentity,
    QueryRunsInput,
    SpanRecord,
)
from alfalab_contracts._generated import Availability, Status3
from pydantic import BaseModel
from sqlalchemy import create_engine, event, text

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


def _concurrently_updated_run(stored: StoredRun) -> StoredRun:
    record = stored.record.model_copy(deep=True)
    configuration = record.manifest.configuration
    next_sequence = max((span.sequence for span in record.spans), default=-1) + 1
    if record.spans:
        updated_span = record.spans[-1].model_copy(
            update={
                "sequence": next_sequence,
                "span_id": f"race-{uuid.uuid4().hex}",
                "name": "concurrent.trace.update",
            }
        )
    else:
        updated_span = SpanRecord(
            sequence=next_sequence,
            span_id=f"race-{uuid.uuid4().hex}",
            parent_span_id=None,
            name="concurrent.trace.update",
            kind="operation",
            started_at=record.analytical_time,
            duration_ms=7,
            status="error",
            safe_detail="Concurrent test update.",
        )
    dependency = DependencyRecord(
        sequence=0,
        port_id="model.private",
        kind="model",
        request=configuration.model_copy(deep=True),
        response=None,
        error=ErrorInfo(
            code="DEPENDENCY_FAILED",
            category="dependency",
            retryable=False,
            safe_message="The declared dependency could not be completed.",
            field_paths=[],
            dependency_id="model.private",
            outcome="unknown",
        ),
        duration_ms=7,
        request_hash=configuration.ref.hash,
        substitution="live",
        original_run_id=None,
    )
    record = record.model_copy(
        update={
            "status": Status3.failed,
            "spans": [*record.spans, updated_span],
            "dependencies": [dependency],
        }
    )
    return StoredRun(
        tenant_id=stored.tenant_id,
        sandbox_id=stored.sandbox_id,
        record=record,
        input_hash=stored.input_hash,
        started_at=stored.started_at,
        updated_at=datetime.now(UTC),
        writer_status="error",
    )


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


def test_postgres_preserves_failed_runs_and_partial_history_after_final_write_failure(
    runs_database_url: str,
    runs_artifact_root: Path,
    runs_test_database,
) -> None:
    settings = _settings(runs_database_url, runs_artifact_root)
    app = create_app(settings)
    repository = app.state.execution_runtime.runs_repository
    admin_engine = create_engine(
        str(runs_test_database.admin_url), pool_pre_ping=True, echo=False
    )
    trigger_created = False
    try:
        runtime = app.state.execution_runtime
        implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
        original = runtime.registry.implementations[implementation_key]
        dependency_calls = []
        runtime.registry.dependencies["model.private"] = DependencyDefinition(
            dependency_id="model.private",
            kind="model",
            request_type=DependencyRequest,
            response_type=DependencyResponse,
            invoke=lambda _request, _context: (
                dependency_calls.append(True) or DependencyResponse(value="blocked")
            ),
        )

        def call_policy_blocked_dependency(payload, context, /):
            context.dependency_gateway.invoke(
                "model.private", DependencyRequest(value="T05_EGRESS_PRIVATE_CANARY")
            )
            return original.execute(payload, context)

        runtime.registry.implementations[implementation_key] = RegisteredImplementation(
            id=original.id,
            version=original.version,
            kind=original.kind,
            parameter_type=original.parameter_type,
            payload_type=original.payload_type,
            output_type=original.output_type,
            execute=call_policy_blocked_dependency,
            configuration=original.configuration,
            dependency_ids=frozenset({"model.private"}),
        )
        failed_body = _prepare_request("t05-pg-failed-operation")
        failed_response = _post(app, "/api/v1/documents/prepare", failed_body)
        assert failed_response.status_code == 403, failed_response.text
        assert "T05_PRIVATE_CANARY_t05-pg-failed-operation" not in failed_response.text
        assert "T05_EGRESS_PRIVATE_CANARY" not in failed_response.text
        assert dependency_calls == []
        failed_payload = failed_response.json()
        failed_run_id = failed_payload["meta"]["run_id"]
        failed_run = repository.get(
            failed_run_id,
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
        )
        assert failed_run is not None
        assert failed_run.record.status == "failed"
        assert failed_run.record.spans
        assert all(span.duration_ms >= 0 for span in failed_run.record.spans)
        assert failed_run.record.dependencies
        assert failed_run.record.dependencies[0].error is not None
        assert failed_run.record.dependencies[0].error.code == "DATA_POLICY_DENIED"
        assert all(
            attempt.duration_ms >= 0 for attempt in failed_run.record.dependencies
        )

        runtime.registry.implementations[implementation_key] = original

        with admin_engine.begin() as connection:
            connection.exec_driver_sql(
                """CREATE FUNCTION runs.t05_fail_success_transition()
                RETURNS trigger LANGUAGE plpgsql AS $function$
                BEGIN
                    IF OLD.status = 'running' AND NEW.status = 'success' THEN
                        RAISE EXCEPTION 'injected final Runs write failure';
                    END IF;
                    RETURN NEW;
                END
                $function$"""
            )
            connection.exec_driver_sql(
                """CREATE TRIGGER t05_fail_success_transition
                BEFORE UPDATE ON runs.runs
                FOR EACH ROW EXECUTE FUNCTION runs.t05_fail_success_transition()"""
            )
        trigger_created = True

        response = _post(
            app,
            "/api/v1/documents/prepare",
            _prepare_request("t05-pg-final-history-failure"),
        )
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "HISTORY_UNAVAILABLE"
        assert response.json()["meta"]["trace_status"] == "partial"
        assert "injected final Runs write failure" not in response.text
        partial_run_id = response.json()["meta"]["run_id"]
        partial_run = repository.get(
            partial_run_id,
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
        )
        assert partial_run is not None
        assert partial_run.status == "unknown"
        assert partial_run.record.trace_status == "partial"
        assert partial_run.record.spans
        assert all(span.status == "success" for span in partial_run.record.spans)
    finally:
        if trigger_created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(
                    "DROP TRIGGER IF EXISTS t05_fail_success_transition ON runs.runs"
                )
                connection.exec_driver_sql(
                    "DROP FUNCTION IF EXISTS runs.t05_fail_success_transition()"
                )
        admin_engine.dispose()
        app.state.execution_runtime.close()


def test_runs_query_persists_http_and_cli_runs_and_does_not_record_unknown_content(
    runs_database_url: str,
    runs_artifact_root: Path,
    caplog,
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
        assert "T05_PRIVATE_CANARY" not in query_result.text
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
        assert "T05_PRIVATE_CANARY" not in caplog.text
        assert "T05_EGRESS_PRIVATE_CANARY" not in caplog.text
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
        assert prepared.json()["meta"]["trace_status"] == "complete"

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
        assert full_record["trace_status"] == "complete"
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


def test_runs_query_keeps_one_snapshot_during_concurrent_updates_and_new_runs(
    runs_database_url: str,
    runs_artifact_root: Path,
) -> None:
    settings = _settings(runs_database_url, runs_artifact_root)
    app = create_app(settings)
    repository = PostgresRunsRepository(
        create_runs_engine(runs_database_url),
        environment="testing",
        artifact_root=runs_artifact_root,
    )
    try:
        created_ids = []
        for request_id in ("t05-snapshot-first", "t05-snapshot-second"):
            created = _post(
                app,
                "/api/v1/documents/prepare",
                _prepare_request(request_id),
            )
            assert created.status_code == 200, created.text
            created_ids.append(created.json()["meta"]["run_id"])

        originals = {
            run_id: repository.get(
                run_id,
                tenant_id="t05-test-tenant",
                sandbox_id="t05-sandbox",
            )
            for run_id in created_ids
        }
        assert all(item is not None for item in originals.values())
        original_span_counts = {
            run_id: len(item.record.spans)
            for run_id, item in originals.items()
            if item is not None
        }
        replacements = {
            run_id: _concurrently_updated_run(item)
            for run_id, item in originals.items()
            if item is not None
        }

        updated_during_read = Event()

        def update_after_parent_rows(
            connection, cursor, statement, parameters, context, executemany
        ):
            del connection, cursor, parameters, context, executemany
            if (
                not updated_during_read.is_set()
                and "SELECT run_id, record_json FROM runs.runs" in statement
            ):
                updated_during_read.set()
                for replacement in replacements.values():
                    repository.write(replacement)

        event.listen(
            repository._engine, "after_cursor_execute", update_after_parent_rows
        )
        query_payload = QueryRunsInput.model_validate(
            _query_request(created_ids)["payload"]
        ).model_copy(update={"limit": 1, "include_artifacts": False})
        try:
            first_page, cursor = repository.query(
                query_payload,
                tenant_id="t05-test-tenant",
                sandbox_id="t05-sandbox",
                exclude_run_id="t05-current-query-run",
                include_artifacts=False,
            )
        finally:
            event.remove(
                repository._engine, "after_cursor_execute", update_after_parent_rows
            )
        assert updated_during_read.is_set()
        assert cursor is not None
        assert len(first_page) == 1
        first = first_page[0]
        assert first.status == "success"
        assert len(first.spans) == original_span_counts[first.run_id]
        assert first.dependencies == []

        late = _post(
            app,
            "/api/v1/documents/prepare",
            _prepare_request("t05-snapshot-late-run"),
        )
        assert late.status_code == 200, late.text
        late_run_id = late.json()["meta"]["run_id"]

        second_page, next_cursor = repository.query(
            query_payload.model_copy(update={"cursor": cursor}),
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
            exclude_run_id="t05-current-query-run",
            include_artifacts=False,
        )
        assert next_cursor is None
        assert len(second_page) == 1
        second = second_page[0]
        assert second.run_id in created_ids
        assert second.run_id != first.run_id
        assert second.status == "success"
        assert len(second.spans) == original_span_counts[second.run_id]
        assert second.dependencies == []
        assert late_run_id not in {first.run_id, second.run_id}

        current = repository.get(
            second.run_id,
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
        )
        assert current is not None
        assert current.record.status == "failed"
        assert len(current.record.spans) == original_span_counts[second.run_id] + 1
        assert len(current.record.dependencies) == 1

        isolated, _ = repository.query(
            query_payload,
            tenant_id="t05-test-tenant",
            sandbox_id="other-sandbox",
            exclude_run_id="t05-current-query-run",
            include_artifacts=False,
        )
        assert isolated == []

        self_query_body = _query_request([])
        self_query_body["payload"]["operation_id"] = None
        self_query_body["payload"]["include_artifacts"] = False
        self_query = _post(app, "/api/v1/runs/query", self_query_body)
        assert self_query.status_code == 200, self_query.text
        returned_ids = {item["run_id"] for item in self_query.json()["payload"]["runs"]}
        assert self_query.json()["meta"]["run_id"] not in returned_ids
    finally:
        repository.close()
        app.state.execution_runtime.close()


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


def test_runs_query_checks_aggregate_artifact_budget_before_any_file_read(
    runs_database_url: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(runs_database_url, tmp_path)
    fixture = json.loads(
        (
            ROOT / "fixtures/approved/Documents.prepare/normalize/manifest.json"
        ).read_text(encoding="utf-8")
    )
    body = fixture["request"]
    body["request_id"] = "t05-aggregate-large-source"
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
        artifact_root=tmp_path,
    )
    try:
        source = repository.get(
            source_run_id,
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
        )
        assert source is not None and source.record.input is not None
        content_json = json.dumps(
            {"large": "x" * 900_000},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = content_json.encode("utf-8")
        assert len(encoded) < 2 * 1024 * 1024

        requested_run_ids = []
        for index in range(2):
            record = source.record.model_copy(deep=True)
            artifact_hash = "sha256:" + hashlib.sha256(encoded).hexdigest()
            input_view = record.input
            record.input = input_view.model_copy(
                update={
                    "ref": input_view.ref.model_copy(
                        update={
                            "artifact_id": f"t05-aggregate-artifact-{index}",
                            "hash": artifact_hash,
                            "size_bytes": len(encoded),
                        }
                    ),
                    "content_json": content_json,
                    "availability": Availability.available,
                }
            )
            configuration = record.manifest.configuration.model_copy(
                update={
                    "content_json": None,
                    "availability": Availability.metadata_only,
                }
            )
            record.manifest = record.manifest.model_copy(
                update={"configuration": configuration}
            )
            record.output = None
            record.run_id = f"t05-aggregate-over-budget-{index}"
            requested_run_ids.append(record.run_id)
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
            return original_read(self, scope, artifact_hash, **kwargs)

        monkeypatch.setattr(ArtifactStore, "read_json", tracked_read)
        payload = QueryRunsInput.model_validate(
            _query_request(requested_run_ids)["payload"]
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


def test_t06_postgres_artifacts_support_strict_replay_and_detect_tampering(
    runs_database_url: str,
    runs_artifact_root: Path,
) -> None:
    settings = _settings(runs_database_url, runs_artifact_root)
    fixture = json.loads(
        (
            ROOT / "fixtures/approved/Documents.prepare/normalize/manifest.json"
        ).read_text(encoding="utf-8")
    )
    live = fixture["request"]
    live["request_id"] = f"t06-pg-live-{uuid.uuid4().hex}"
    live["sandbox_id"] = "t05-sandbox"
    live["implementation"] = {
        "id": "real.prepare",
        "version": "1.0.0",
        "parameters": {},
    }
    app = create_app(settings)
    try:
        first = _post(app, "/api/v1/documents/prepare", live)
        assert first.status_code == 200, first.text
        source_run_id = first.json()["meta"]["run_id"]
        assert first.json()["meta"]["replay_status"] == "available"

        replay = json.loads(json.dumps(live))
        replay["request_id"] = f"t06-pg-replay-{uuid.uuid4().hex}"
        replay["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": source_run_id,
            "strict": True,
            "timeout_ms": 30_000,
        }
        replay_response = _post(app, "/api/v1/documents/prepare", replay)
        assert replay_response.status_code == 200, replay_response.text
        replay_body = replay_response.json()
        assert replay_body["meta"]["execution_mode"] == "replay"
        assert replay_body["meta"]["run_id"] != source_run_id
        assert replay_body["payload"] == first.json()["payload"]

        source = app.state.runs_writer.get(
            source_run_id,
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
        )
        assert source is not None and source.record.input is not None
        input_ref = source.record.input.ref
        artifact_path = (
            runs_artifact_root
            / "testing"
            / "t05-test-tenant"
            / "t05-sandbox"
            / f"{input_ref.hash.removeprefix('sha256:')}.json"
        )
        artifact_path.write_bytes(b'{"tampered":true}')

        denied = _post(app, "/api/v1/documents/prepare", replay)
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "REPLAY_MISS"
        assert live["payload"]["material"]["text"] not in denied.text
    finally:
        app.state.execution_runtime.close()


def test_t06_postgres_secret_dependency_response_is_not_persisted(
    runs_database_url: str,
    runs_artifact_root: Path,
    caplog,
) -> None:
    canary = "T06_POSTGRES_DEPENDENCY_RESPONSE_CANARY"
    app = create_app(_settings(runs_database_url, runs_artifact_root))
    runtime = app.state.execution_runtime
    implementation_key = ("Documents.prepare", "real.prepare", "1.0.0")
    implementation = runtime.registry.implementations[implementation_key]
    body = _prepare_request(f"t06-pg-secret-{uuid.uuid4().hex}")
    material_id = body["payload"]["material"]["material_id"]
    payload_hash = canonical_hash(body["payload"])
    runtime.execution_service._policy_resolver = TrustedDataPolicyResolver(
        {
            material_id: TrustedSource(
                classification="synthetic",
                processing_allowed=True,
                egress_allowed=True,
                recording="full",
                export_allowed=True,
                approved_payload_hashes=frozenset({payload_hash}),
            )
        }
    )
    runtime.registry.dependencies["model.canary"] = DependencyDefinition(
        dependency_id="model.canary",
        kind="model",
        request_type=DependencyRequest,
        response_type=DependencyResponse,
        invoke=lambda _request, _context: DependencyResponse(
            value=f"private response: {canary}"
        ),
        sensitive_values=(canary,),
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

    def execute_with_canary(payload, context, /):
        context.dependency_gateway.invoke(
            "model.canary", DependencyRequest(value="approved")
        )
        return implementation.execute(payload, context)

    runtime.registry.implementations[implementation_key] = RegisteredImplementation(
        id=implementation.id,
        version=implementation.version,
        kind=implementation.kind,
        parameter_type=implementation.parameter_type,
        payload_type=implementation.payload_type,
        output_type=implementation.output_type,
        execute=execute_with_canary,
        configuration=implementation.configuration,
        dependency_ids=frozenset({"model.canary"}),
    )

    try:
        response = _post(app, "/api/v1/documents/prepare", body)
        assert response.status_code == 502, response.text
        assert response.json()["error"]["code"] == "DEPENDENCY_FAILED"
        assert canary not in response.text
        assert canary not in caplog.text

        run_id = response.json()["meta"]["run_id"]
        stored = runtime.runs_writer.get(
            run_id,
            tenant_id="t05-test-tenant",
            sandbox_id="t05-sandbox",
        )
        assert stored is not None
        assert stored.record.dependencies[0].response is None
        assert canary not in stored.record.model_dump_json()

        with runtime.runs_repository._engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT set_config('alfalab.tenant_id', :tenant_id, true), "
                    "set_config('alfalab.sandbox_id', :sandbox_id, true)"
                ),
                {"tenant_id": "t05-test-tenant", "sandbox_id": "t05-sandbox"},
            )
            persisted_dependencies = (
                connection.execute(
                    text(
                        "SELECT dependency_json::text FROM runs.dependencies "
                        "WHERE tenant_id=:tenant_id AND sandbox_id=:sandbox_id "
                        "AND run_id=:run_id"
                    ),
                    {
                        "tenant_id": "t05-test-tenant",
                        "sandbox_id": "t05-sandbox",
                        "run_id": run_id,
                    },
                )
                .scalars()
                .all()
            )
        assert persisted_dependencies
        assert canary not in "".join(persisted_dependencies)

        persisted_files = [
            path for path in runs_artifact_root.rglob("*") if path.is_file()
        ]
        assert persisted_files
        assert all(canary.encode() not in path.read_bytes() for path in persisted_files)
    finally:
        runtime.close()
