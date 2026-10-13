from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from uuid import uuid4

import httpx
from alfalab.bootstrap.app import ApiSettings, create_app
from alfalab.bootstrap.runtime import create_execution_runtime
from alfalab.execution.gateway import DependencyDefinition
from alfalab.modules.runs.storage.memory import InMemoryRunsRepository

EXAMPLES = Path(__file__).parents[2] / "docs/specs/framework-v1/contracts/examples.json"
TOKEN = "t07-source-test-token"


def _request() -> dict:
    values = json.loads(EXAMPLES.read_text(encoding="utf-8"))["examples"]
    body = copy.deepcopy(
        next(
            item["request"]
            for item in values
            if item["operation_id"] == "Sources.fetch"
        )
    )
    body["request_id"] = f"t07-source-{uuid4().hex}"
    body["sandbox_id"] = "demo-a"
    return body


def _app():
    runtime = create_execution_runtime(
        "testing", runs_repository=InMemoryRunsRepository()
    )
    settings = ApiSettings(
        developer_token=TOKEN,
        environment="testing",
        actor_id="t07-source-test-actor",
        tenant_id="t07-source-test-tenant",
        allowed_sandboxes=frozenset({"demo-a"}),
        playground_origins=(),
    )
    return create_app(settings, execution_runtime=runtime)


def _post(app, body: object):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                "/api/v1/sources/fetch",
                json=body,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    return asyncio.run(send())


def test_fetch_pages_are_stable_empty_filter_is_explicit_and_no_document_is_created() -> (
    None
):
    app = _app()
    first_request = _request()
    first_request["payload"]["limit"] = 2
    first = _post(app, first_request)
    assert first.status_code == 200
    first_payload = first.json()["payload"]
    assert [item["material_id"] for item in first_payload["materials"]] == [
        "fixture-radio-news",
        "fixture-radio-duplicate",
    ]
    assert first_payload["next_cursor"]

    second_request = copy.deepcopy(first_request)
    second_request["request_id"] = f"t07-source-{uuid4().hex}"
    second_request["payload"]["cursor"] = first_payload["next_cursor"]
    second = _post(app, second_request)
    assert second.status_code == 200
    assert [item["material_id"] for item in second.json()["payload"]["materials"]] == [
        "fixture-radio-contradiction"
    ]
    assert second.json()["payload"]["next_cursor"] is None

    repeated = _post(app, first_request)
    assert [
        item["material_id"] for item in repeated.json()["payload"]["materials"]
    ] == [
        "fixture-radio-news",
        "fixture-radio-duplicate",
    ]
    assert (
        repeated.json()["payload"]["materials"][0]["provenance"]["producer_run_id"]
        != first.json()["payload"]["materials"][0]["provenance"]["producer_run_id"]
    )

    empty_request = _request()
    empty_request["payload"]["since"] = "2099-01-01T00:00:00Z"
    empty = _post(app, empty_request)
    assert empty.status_code == 200
    assert empty.json()["payload"]["materials"] == []
    assert (
        "source_item_without_published_at_excluded"
        in empty.json()["payload"]["warnings"]
    )
    assert len(app.state.runs_writer) == 4


def test_unregistered_source_and_client_url_are_rejected_before_adapter_call() -> None:
    app = _app()
    calls: list[bool] = []
    definition = app.state.registry.dependencies["sources.fixture"]
    app.state.registry.dependencies["sources.fixture"] = DependencyDefinition(
        dependency_id=definition.dependency_id,
        kind=definition.kind,
        request_type=definition.request_type,
        response_type=definition.response_type,
        invoke=lambda *_: calls.append(True),
        sensitive_values=(),
        secret_inventory_complete=True,
        requires_egress=False,
    )

    unregistered = _request()
    unregistered["payload"]["source_id"] = "https://127.0.0.1/private"
    denied = _post(app, unregistered)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "DATA_POLICY_DENIED"
    assert calls == []

    with_url = _request()
    with_url["payload"]["url"] = "http://127.0.0.1/private"
    invalid = _post(app, with_url)
    assert invalid.status_code == 422
    assert "http://127.0.0.1/private" not in invalid.text
    assert calls == []


def test_malformed_source_response_and_controlled_timeout_are_safe() -> None:
    app = _app()
    definition = app.state.registry.dependencies["sources.fixture"]
    app.state.registry.dependencies["sources.fixture"] = DependencyDefinition(
        dependency_id=definition.dependency_id,
        kind=definition.kind,
        request_type=definition.request_type,
        response_type=definition.response_type,
        invoke=lambda *_: object(),
        sensitive_values=(),
        secret_inventory_complete=True,
        requires_egress=False,
    )
    malformed = _post(app, _request())
    assert malformed.status_code == 502
    assert malformed.json()["error"]["code"] == "DEPENDENCY_FAILED"

    timeout_request = _request()
    timeout_request["implementation"]["parameters"]["scenario"] = "timeout"
    timeout = _post(app, timeout_request)
    assert timeout.status_code == 504
    assert timeout.json()["error"]["code"] == "TIMEOUT"
    assert "fixture-radio" not in timeout.text
