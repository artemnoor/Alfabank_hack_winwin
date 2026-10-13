"""HTTP and execution tests for the T03 Documents.prepare slice."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alfalab.bootstrap.app import ApiSettings, create_app
from alfalab.bootstrap.registry import RegisteredImplementation
from alfalab.bootstrap.runtime import create_execution_runtime
from alfalab.execution.context import TrustedPrincipal
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.policy import TrustedSource
from alfalab.execution.service import ExecutionService
from alfalab.modules.documents.implementations.prepare import prepare

EXAMPLES = Path(__file__).parents[2] / "docs/specs/framework-v1/contracts/examples.json"
TOKEN = "test-secret"


def _request(implementation_id: str = "mock.baseline") -> dict[str, object]:
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))["examples"]
    body = next(
        item["request"]
        for item in examples
        if item["operation_id"] == "Documents.prepare"
    )
    body["sandbox_id"] = "demo-a"
    if implementation_id == "real.prepare":
        body["implementation"] = {
            "id": "real.prepare",
            "version": "1.0.0",
            "parameters": {},
        }
    return body


def _runs_query_request(
    *, limit: int = 100, cursor: str | None = None
) -> dict[str, object]:
    manifest = json.loads(
        (
            Path(__file__).parents[2]
            / "fixtures/approved/Runs.query/successful-run/manifest.json"
        ).read_text(encoding="utf-8")
    )
    body = manifest["request"]
    body["sandbox_id"] = "demo-a"
    body["request_id"] = f"query-{uuid4().hex}"
    body["payload"].update(
        {
            "run_ids": [],
            "operation_id": "Documents.prepare",
            "scenario_id": None,
            "include_artifacts": False,
            "limit": limit,
            "cursor": cursor,
        }
    )
    return body


def _app(*, sandboxes: frozenset[str] = frozenset({"demo-a"})):
    return create_app(
        ApiSettings(
            developer_token=TOKEN,
            environment="testing",
            actor_id="test-actor",
            tenant_id="test-tenant",
            allowed_sandboxes=sandboxes,
            playground_origins=("http://127.0.0.1:5173",),
        )
    )


def _post(
    app,
    body: object,
    *,
    path: str = "/api/v1/documents/prepare",
    token: str | None = TOKEN,
    headers: dict[str, str] | None = None,
):
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post(path, json=body, headers=request_headers)

    return asyncio.run(send())


def _replace_text(body: dict[str, object], text: str) -> None:
    payload = body["payload"]
    material = payload["material"]
    material["text"] = text
    material["content_hash"] = (
        "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    )


@pytest.mark.parametrize("implementation_id", ["mock.baseline", "real.prepare"])
def test_prepare_normalizes_newlines_and_outer_unicode_whitespace(
    implementation_id: str,
) -> None:
    app = _app()
    body = _request(implementation_id)
    _replace_text(body, " \tПривет\r\n😀\r мир  \n")

    response = _post(app, body)

    assert response.status_code == 200
    prepared = response.json()["payload"]["prepared"]
    assert prepared["material"]["text"] == "Привет\n😀\n мир"
    assert prepared["quality"] == "valid"
    assert prepared["raw_hash"] == body["payload"]["material"]["content_hash"]
    assert prepared["prepared_hash"] == prepared["material"]["content_hash"]
    assert prepared["span_map"] == [
        {"prepared_start": 0, "prepared_end": 6, "raw_start": 2, "raw_end": 8},
        {"prepared_start": 6, "prepared_end": 7, "raw_start": 8, "raw_end": 10},
        {"prepared_start": 7, "prepared_end": 13, "raw_start": 10, "raw_end": 16},
    ]


def test_empty_prepared_text_is_rejected_with_empty_map_and_warning() -> None:
    app = _app()
    body = _request("real.prepare")
    _replace_text(body, " \r\n\t")

    response = _post(app, body)

    assert response.status_code == 200
    prepared = response.json()["payload"]["prepared"]
    assert prepared["material"]["text"] == ""
    assert prepared["quality"] == "rejected"
    assert prepared["span_map"] == []
    assert prepared["warnings"] == ["empty_text"]


def test_success_records_measured_metadata_and_actual_spans_without_payload() -> None:
    app = _app()
    body = _request("real.prepare")
    _replace_text(body, "manual unknown content stays ephemeral")
    response = _post(app, body, headers={"X-Request-ID": "request-safe-42"})

    assert response.status_code == 200
    payload = response.json()
    meta = payload["meta"]
    run = app.state.runs_writer.get(meta["run_id"])
    assert run is not None
    assert run.status == "success"
    assert run.input_hash.startswith("sha256:")
    assert "fixture-radio-news" not in run.input_hash
    assert run.spans[0].name == "Documents.prepare"
    assert run.spans[1].name == "real.prepare.execute"
    assert all(
        span.duration_ms >= 0 and span.started_at.endswith("Z") for span in run.spans
    )
    assert meta["measurements"][0]["basis"] == "measured"
    assert meta["trace_status"] == "metadata_only"
    assert meta["replay_status"] == "unavailable"
    assert meta["data_policy"]["classification"] == "unknown"
    assert meta["data_policy"]["egress_allowed"] is False


def test_runs_query_reads_persistent_shape_and_excludes_its_own_run() -> None:
    app = _app()
    prepared = _post(app, _request("real.prepare"))
    assert prepared.status_code == 200
    prepared_id = prepared.json()["meta"]["run_id"]

    queried = _post(app, _runs_query_request(), path="/api/v1/runs/query")

    assert queried.status_code == 200
    response = queried.json()
    assert [run["run_id"] for run in response["payload"]["runs"]] == [prepared_id]
    record = response["payload"]["runs"][0]
    assert record["status"] == "success"
    assert [span["name"] for span in record["spans"]] == [
        "Documents.prepare",
        "real.prepare.execute",
    ]
    assert record["input"]["content_json"] is None
    assert record["output"]["content_json"] is None
    assert queried.json()["meta"]["run_id"] not in {
        item["run_id"] for item in response["payload"]["runs"]
    }


def test_runs_query_returns_failed_runs_and_metadata_only_when_requested() -> None:
    app = _app()
    failed = _request("mock.baseline")
    failed["implementation"]["parameters"]["scenario"] = "retryable_error"
    _replace_text(failed, "manual failed content stays ephemeral")
    result = _post(app, failed)
    assert result.status_code == 502
    failed_id = result.json()["meta"]["run_id"]

    query = _runs_query_request()
    query["payload"]["run_ids"] = [failed_id]
    query["payload"]["include_artifacts"] = True
    queried = _post(app, query, path="/api/v1/runs/query")

    assert queried.status_code == 200
    record = queried.json()["payload"]["runs"][0]
    assert record["run_id"] == failed_id
    assert record["status"] == "failed"
    assert record["input"]["availability"] == "metadata_only"
    assert record["input"]["content_json"] is None


def test_runs_query_cursor_is_stable_and_bound_to_scope_and_filters() -> None:
    app = _app()
    first = _post(app, _request("prepare-page-first"))
    second = _post(app, _request("prepare-page-second"))
    assert first.status_code == second.status_code == 200
    initial_ids = {first.json()["meta"]["run_id"], second.json()["meta"]["run_id"]}

    page_one = _runs_query_request(limit=1)
    first_page = _post(app, page_one, path="/api/v1/runs/query")
    assert first_page.status_code == 200
    cursor = first_page.json()["payload"]["next_cursor"]
    assert cursor is not None
    first_page_id = first_page.json()["payload"]["runs"][0]["run_id"]

    inserted_after_snapshot = _post(app, _request("prepare-after-snapshot"))
    assert inserted_after_snapshot.status_code == 200
    late_id = inserted_after_snapshot.json()["meta"]["run_id"]

    page_two = _runs_query_request(limit=1, cursor=cursor)
    second_page = _post(app, page_two, path="/api/v1/runs/query")
    assert second_page.status_code == 200
    second_page_id = second_page.json()["payload"]["runs"][0]["run_id"]
    assert first_page_id != second_page_id
    assert {first_page_id, second_page_id} == initial_ids
    assert late_id not in {first_page_id, second_page_id}

    changed_filter = _runs_query_request(limit=1, cursor=cursor)
    changed_filter["payload"]["operation_id"] = "Runs.query"
    mismatch = _post(app, changed_filter, path="/api/v1/runs/query")
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "INVALID_INPUT"


def test_runs_query_enforces_two_mib_on_the_complete_artifact_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    prepared = _post(app, _request("real.prepare"))
    run_id = prepared.json()["meta"]["run_id"]
    stored = app.state.runs_writer.get(run_id)
    assert stored is not None
    oversized_span = stored.record.spans[0].model_copy(
        update={"safe_detail": "x" * 400}
    )
    oversized_record = stored.record.model_copy(
        update={"spans": [oversized_span] * 10_000}
    )
    original_query = app.state.runs_writer.query

    def oversized_query(*args, **kwargs):
        _records, next_cursor = original_query(*args, **kwargs)
        return [oversized_record], next_cursor

    monkeypatch.setattr(app.state.runs_writer, "query", oversized_query)
    query = _runs_query_request()
    query["payload"]["include_artifacts"] = True
    query["payload"]["run_ids"] = [run_id]

    response = _post(app, query, path="/api/v1/runs/query")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "LIMIT_EXCEEDED"
    assert "include_artifacts=false" in response.json()["error"]["safe_message"]


def test_restricted_source_is_denied_before_content_history_or_operation() -> None:
    runtime = create_execution_runtime(
        "testing",
        trusted_sources={
            "restricted": TrustedSource(
                classification="secret",
                processing_allowed=False,
                egress_allowed=False,
                recording="metadata_only",
                export_allowed=False,
            )
        },
    )
    body = _request("real.prepare")
    canary = "CLOSED_CONTENT_NEVER_PERSIST"
    body["payload"]["material"]["source_id"] = "restricted"
    _replace_text(body, canary)
    contract = runtime.registry.contract("Documents.prepare")
    request = contract.request_type.model_validate(body)
    principal = TrustedPrincipal(
        actor_id="test-actor",
        tenant_id="test-tenant",
        role="developer",
        allowed_sandboxes=frozenset({"demo-a"}),
        permissions=frozenset({"Documents.prepare"}),
    )

    denied_run_id = None
    try:
        runtime.execution_service.invoke(
            runtime.registry.descriptor("Documents.prepare"),
            request,
            principal,
        )
        pytest.fail("restricted data unexpectedly executed")
    except SafeExecutionError as error:
        assert error.status_code == 403
        assert error.code == "DATA_POLICY_DENIED"
        assert canary not in error.safe_message
        denied_run_id = error.meta.run_id

    assert denied_run_id is not None
    stored = runtime.runs_repository.get(
        denied_run_id, tenant_id="test-tenant", sandbox_id="demo-a"
    )
    assert stored is not None
    serialized = stored.record.model_dump_json()
    assert canary not in serialized
    assert canary not in stored.input_hash
    assert stored.record.input is not None
    assert stored.record.input.content_json is None
    assert stored.record.manifest.data_policy.processing_allowed is False
    assert stored.record.status == "failed"


def test_initial_run_metadata_is_written_before_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    observed: dict[str, object] = {}
    original = app.state.registry.implementations[
        ("Documents.prepare", "real.prepare", "1.0.0")
    ]

    def execute(payload, context, /):
        initial_record = app.state.runs_writer.get(context.run_id)
        observed["initial_status"] = initial_record.status if initial_record else None
        observed["request_id"] = context.request_id
        observed["operation_id"] = context.operation_id
        observed["contract_version"] = context.contract_version
        observed["configuration_hash"] = context.implementation_configuration_hash
        observed["analytical_time"] = context.analytical_clock.now().isoformat()
        return prepare(payload)

    monkeypatch.setitem(
        app.state.registry.implementations,
        ("Documents.prepare", "real.prepare", "1.0.0"),
        RegisteredImplementation(
            id="real.prepare",
            version="1.0.0",
            kind="real",
            parameter_type=original.parameter_type,
            payload_type=original.payload_type,
            output_type=original.output_type,
            execute=execute,
            configuration={"algorithm": "test-spy"},
        ),
    )

    response = _post(app, _request("real.prepare"))

    assert response.status_code == 200
    assert observed["initial_status"] == "in_progress"
    assert observed["request_id"] == "example-2"
    assert observed["operation_id"] == "Documents.prepare"
    assert observed["contract_version"] == "1.0.0"
    assert str(observed["configuration_hash"]).startswith("sha256:")
    assert observed["analytical_time"] == "2026-10-12T00:00:00+00:00"


def test_history_unavailable_prevents_operation_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    executed = False
    original = app.state.registry.implementations[
        ("Documents.prepare", "real.prepare", "1.0.0")
    ]

    def execute(payload, context, /):
        nonlocal executed
        executed = True
        return prepare(payload)

    monkeypatch.setitem(
        app.state.registry.implementations,
        ("Documents.prepare", "real.prepare", "1.0.0"),
        RegisteredImplementation(
            id="real.prepare",
            version="1.0.0",
            kind="real",
            parameter_type=original.parameter_type,
            payload_type=original.payload_type,
            output_type=original.output_type,
            execute=execute,
            configuration={"algorithm": "test-spy"},
        ),
    )

    def fail_write(record):
        raise OSError("private writer fault")

    monkeypatch.setattr(app.state.runs_writer, "write", fail_write)
    response = _post(app, _request("real.prepare"))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "HISTORY_UNAVAILABLE"
    assert executed is False
    assert "private writer fault" not in response.text


def test_committed_owner_result_survives_final_history_failure_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    repository = app.state.runs_writer
    original_write = repository.write

    def fail_success_write(record):
        if record.writer_status == "success":
            raise OSError("simulated final history outage")
        original_write(record)

    monkeypatch.setattr(repository, "write", fail_success_write)
    # T05 does not register a Documents command operation; this isolates the
    # existing owner-receipt branch with a typed successful result.
    monkeypatch.setattr(
        ExecutionService, "_contains_owner_receipt", staticmethod(lambda _value: True)
    )

    response = _post(app, _request("real.prepare"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["meta"]["trace_status"] == "partial"
    saved = repository.get(payload["meta"]["run_id"])
    assert saved is not None
    assert saved.status == "unknown"
    assert saved.record.trace_status == "partial"


def test_non_command_final_history_failure_returns_unknown_and_updates_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    repository = app.state.runs_writer
    original_write = repository.write

    def fail_success_write(record):
        if record.writer_status == "success":
            raise OSError("simulated final history outage")
        original_write(record)

    monkeypatch.setattr(repository, "write", fail_success_write)

    response = _post(app, _request("real.prepare"))

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["outcome"] == "unknown"
    assert payload["meta"]["trace_status"] == "partial"
    saved = repository.get(payload["meta"]["run_id"])
    assert saved is not None
    assert saved.status == "unknown"
    assert saved.record.trace_status == "partial"


@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_code", "expected_retryable"),
    [
        ("timeout", 504, "TIMEOUT", True),
        ("retryable_error", 502, "DEPENDENCY_FAILED", True),
    ],
)
def test_mock_fault_scenarios_record_completed_error_run_and_spans(
    scenario: str,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    app = _app()
    body = _request("mock.baseline")
    body["implementation"]["parameters"]["scenario"] = scenario
    body["payload"]["material"]["text"] = "FAULT_SCENARIO_PRIVATE_INPUT"
    _replace_text(body, "FAULT_SCENARIO_PRIVATE_INPUT")

    response = _post(app, body)

    assert response.status_code == expected_status
    result = response.json()
    assert result["error"]["code"] == expected_code
    assert result["error"]["retryable"] is expected_retryable
    assert "FAULT_SCENARIO_PRIVATE_INPUT" not in response.text
    meta = result["meta"]
    assert meta["run_id"]
    run = app.state.runs_writer.get(meta["run_id"])
    assert run is not None
    assert run.status == "error"
    assert len(run.spans) == 2
    assert [span.status for span in run.spans] == ["error", "error"]
    assert all(span.duration_ms >= 0 for span in run.spans)
    assert [span.name for span in run.spans] == [
        "Documents.prepare",
        "mock.baseline.execute",
    ]


def test_catalog_and_runtime_openapi_show_only_available_documents_prepare() -> None:
    app = _app()
    headers = {"Authorization": f"Bearer {TOKEN}"}

    async def get(path: str):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get(path, headers=headers)

    async def get_both():
        return await asyncio.gather(get("/system/catalog"), get("/openapi.json"))

    catalog, openapi = asyncio.run(get_both())
    operations = {
        entry["operation_id"]: entry for entry in catalog.json()["operations"]
    }
    assert [
        item["id"] for item in operations["Documents.prepare"]["implementations"]
    ] == [
        "mock.baseline",
        "real.prepare",
    ]
    assert [item["id"] for item in operations["Runs.query"]["implementations"]] == [
        "mock.baseline"
    ]
    assert all(
        not item["implementations"]
        for key, item in operations.items()
        if key not in {"Documents.prepare", "Runs.query"}
    )
    assert "/api/v1/documents/prepare" in openapi.json()["paths"]
    assert "/api/v1/runs/query" in openapi.json()["paths"]
    assert "/api/v1/documents/register" not in openapi.json()["paths"]


@pytest.mark.parametrize(
    ("token", "sandbox", "mode", "expected_status", "expected_code"),
    [
        (None, "demo-a", "live", 401, "UNAUTHENTICATED"),
        (TOKEN, "outside-scope", "live", 403, "ACCESS_DENIED"),
        (TOKEN, "demo-a", "replay", 409, "REPLAY_INCOMPATIBLE"),
    ],
)
def test_auth_scope_and_replay_errors_are_safe(
    token: str | None,
    sandbox: str,
    mode: str,
    expected_status: int,
    expected_code: str,
) -> None:
    body = _request()
    body["sandbox_id"] = sandbox
    if mode == "replay":
        body["execution"] = {
            "mode": "replay",
            "recording": "full",
            "source_run_id": "prior-run",
            "strict": True,
            "timeout_ms": 30_000,
        }

    response = _post(_app(), body, token=token)

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_invalid_json_fields_and_content_hash_canary_are_not_echoed() -> None:
    app = _app()
    body = _request()
    body["payload"]["untrusted_extra"] = "DO_NOT_ECHO_CANARY"

    invalid_shape = _post(app, body)
    assert invalid_shape.status_code == 422
    assert "DO_NOT_ECHO_CANARY" not in invalid_shape.text
    assert "untrusted_extra" not in invalid_shape.text

    body = _request()
    body["payload"]["material"]["content_hash"] = "sha256:" + "0" * 64
    bad_hash = _post(app, body)
    assert bad_hash.status_code == 422
    assert "0" * 64 not in bad_hash.text
    assert "Учебный источник" not in bad_hash.text


def test_body_limit_returns_sanitized_error() -> None:
    app = _app()
    large = b'{"private_payload":"' + b"x" * (2 * 1024 * 1024) + b'"}'

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/v1/documents/prepare",
                content=large,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
            )

    response = asyncio.run(send())
    assert response.status_code == 413
    assert "private_payload" not in response.text


def test_chunked_body_limit_returns_sanitized_error_before_json_parsing() -> None:
    app = _app()
    canary = b"CHUNKED_BODY_PRIVATE_CANARY"
    oversized_json = b'{"private_payload":"' + canary + b"x" * (2 * 1024 * 1024) + b'"}'

    async def chunks():
        for offset in range(0, len(oversized_json), 4096):
            yield oversized_json[offset : offset + 4096]

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            request = client.build_request(
                "POST",
                "/api/v1/documents/prepare",
                content=chunks(),
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
            )
            assert "content-length" not in request.headers
            return await client.send(request)

    response = asyncio.run(send())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert canary.decode() not in response.text
