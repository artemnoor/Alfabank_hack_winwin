"""CLI conformance tests for the shared Documents.prepare execution path."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

from alfalab.bootstrap.app import ApiSettings, create_app
from alfalab.bootstrap.runtime import create_execution_runtime
from alfalab.cli import run_cli


EXAMPLES = Path(__file__).parents[2] / "docs/specs/framework-v1/contracts/examples.json"
TOKEN = "test-secret"


def _request(implementation_id: str = "real.prepare") -> dict[str, object]:
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))["examples"]
    body = next(item["request"] for item in examples if item["operation_id"] == "Documents.prepare")
    body["sandbox_id"] = "demo-a"
    text = "  CLI and HTTP share the same deterministic input.\r\n"
    body["payload"]["material"]["text"] = text
    body["payload"]["material"]["content_hash"] = "sha256:" + hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()
    if implementation_id == "real.prepare":
        body["implementation"] = {
            "id": "real.prepare",
            "version": "1.0.0",
            "parameters": {},
        }
    return body


def _settings() -> ApiSettings:
    return ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id="test-actor",
        tenant_id="test-tenant",
        allowed_sandboxes=frozenset({"demo-a"}),
        playground_origins=("http://127.0.0.1:5173",),
    )


def _post_http(body: object):
    app = create_app(_settings())

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/v1/documents/prepare",
                json=body,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    return asyncio.run(send())


def test_cli_and_http_share_semantic_result_and_actual_metadata() -> None:
    request = _request()
    runtime = create_execution_runtime("testing")
    stdout = io.StringIO()

    exit_code = run_cli(
        ["prepare"],
        stdin=io.StringIO(json.dumps(request, ensure_ascii=False)),
        stdout=stdout,
        settings=_settings(),
        runtime=runtime,
    )

    cli_response = json.loads(stdout.getvalue())
    http_response = _post_http(request)
    http_body = http_response.json()

    assert exit_code == 0
    assert http_response.status_code == 200
    assert cli_response["status"] == http_body["status"] == "success"
    assert cli_response["payload"] == http_body["payload"]
    semantic_metadata = (
        "operation_id",
        "contract_version",
        "implementation",
        "execution_mode",
        "environment",
        "configuration_hash",
        "lineage",
        "trace_status",
        "replay_status",
        "data_policy",
    )
    for key in semantic_metadata:
        assert cli_response["meta"][key] == http_body["meta"][key]

    meta = cli_response["meta"]
    assert meta["measurements"][0]["basis"] == "measured"
    assert meta["trace_status"] == "metadata_only"
    assert meta["replay_status"] == "unavailable"
    cli_run = runtime.runs_writer.get(meta["run_id"])
    assert cli_run is not None
    assert cli_run.status == "success"
    assert len(cli_run.spans) == 2
    assert all(span.status == "success" and span.duration_ms >= 0 for span in cli_run.spans)


def test_cli_failure_uses_sanitized_execution_error_and_records_run() -> None:
    request = _request("mock.baseline")
    private_canary = "PRIVATE_CLI_FAILURE_INPUT"
    text = f"  {private_canary}\r\n"
    request["payload"]["material"]["text"] = text
    request["payload"]["material"]["content_hash"] = "sha256:" + hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()
    request["implementation"]["parameters"]["scenario"] = "retryable_error"
    runtime = create_execution_runtime("testing")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = run_cli(
        ["prepare"],
        stdin=io.StringIO(json.dumps(request, ensure_ascii=False)),
        stdout=stdout,
        stderr=stderr,
        settings=_settings(),
        runtime=runtime,
    )

    response = json.loads(stderr.getvalue())

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert response["error"]["code"] == "DEPENDENCY_FAILED"
    assert response["error"]["category"] == "dependency"
    assert response["error"]["retryable"] is True
    assert private_canary not in stderr.getvalue()
    run = runtime.runs_writer.get(response["meta"]["run_id"])
    assert run is not None
    assert run.status == "error"
    assert len(run.spans) == 2
    assert all(span.status == "error" for span in run.spans)


def test_cli_schema_error_does_not_echo_rejected_input() -> None:
    request = _request()
    request["untrusted_extra"] = "CLI_DTO_CANARY"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = run_cli(
        ["prepare"],
        stdin=io.StringIO(json.dumps(request, ensure_ascii=False)),
        stdout=stdout,
        stderr=stderr,
        settings=_settings(),
        runtime=create_execution_runtime("testing"),
    )

    response = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert response["error"]["code"] == "INVALID_INPUT"
    assert "CLI_DTO_CANARY" not in stderr.getvalue()


def test_python_module_entrypoint_executes_prepare_as_json_cli(tmp_path: Path) -> None:
    request = _request()
    environment = os.environ.copy()
    environment["ALFALAB_ENVIRONMENT"] = "testing"
    environment["ALFALAB_ALLOWED_SANDBOXES"] = "demo-a"
    request_path = tmp_path / "prepare-request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "alfalab.cli", "prepare", "--request", str(request_path)],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[2],
        env=environment,
    )

    assert result.returncode == 0
    assert result.stderr == b""
    response = json.loads(result.stdout)
    assert response["status"] == "success"
    assert response["payload"]["prepared"]["material"]["text"] == (
        "CLI and HTTP share the same deterministic input."
    )
    assert response["meta"]["measurements"][0]["basis"] == "measured"
    assert response["meta"]["trace_status"] == "metadata_only"


def test_python_module_entrypoint_writes_sanitized_errors_only_to_stderr() -> None:
    request = _request()
    request["untrusted_extra"] = "CLI_PROCESS_CANARY"
    environment = os.environ.copy()
    environment["ALFALAB_ENVIRONMENT"] = "testing"
    environment["ALFALAB_ALLOWED_SANDBOXES"] = "demo-a"

    result = subprocess.run(
        [sys.executable, "-m", "alfalab.cli", "prepare"],
        input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[2],
        env=environment,
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert b"CLI_PROCESS_CANARY" not in result.stderr
    response = json.loads(result.stderr)
    assert response["error"]["code"] == "INVALID_INPUT"
    assert response["error"]["category"] == "validation"
