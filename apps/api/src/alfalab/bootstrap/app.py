"""FastAPI application factory for the T03 Documents.prepare slice."""

from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from alfalab_contracts import CatalogOutput, HealthOutput
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from alfalab.bootstrap.registry import (
    RuntimeRegistry,
    repository_root,
    runtime_build_hash,
)
from alfalab.bootstrap.runtime import create_execution_runtime
from alfalab.bootstrap.settings import ApiSettings
from alfalab.execution.context import TrustedPrincipal
from alfalab.execution.errors import SafeExecutionError
from alfalab.execution.service import ExecutionService
from alfalab.transport.http.errors import (
    safe_execution_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from alfalab.transport.http.middleware import BodySizeLimitMiddleware

bearer_scheme = HTTPBearer(auto_error=False)


def get_trusted_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TrustedPrincipal:
    settings: ApiSettings = request.app.state.settings
    if settings.developer_token is None:
        raise SafeExecutionError(
            status_code=503,
            code="IMPLEMENTATION_UNAVAILABLE",
            category="unavailable",
            safe_message="The local developer token is not configured on this server.",
            retryable=True,
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        settings.developer_token.encode("utf-8"),
    ):
        raise SafeExecutionError(
            status_code=401,
            code="UNAUTHENTICATED",
            category="access",
            safe_message="A valid local developer token is required.",
        )
    return TrustedPrincipal(
        actor_id=settings.actor_id,
        tenant_id=settings.tenant_id,
        role="developer",
        allowed_sandboxes=settings.allowed_sandboxes,
        permissions=frozenset({"Documents.prepare", "Runs.query", "catalog.read"}),
    )


CurrentPrincipal = Annotated[TrustedPrincipal, Depends(get_trusted_principal)]


def _runtime_openapi(registry: RuntimeRegistry) -> dict[str, object]:
    path = repository_root() / "docs/specs/framework-v1/contracts/openapi.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    available_paths = {descriptor.path for descriptor in registry.available_routes()}
    available_paths.update({"/system/catalog", "/health/live", "/health/ready"})
    snapshot["paths"] = {
        key: value for key, value in snapshot["paths"].items() if key in available_paths
    }
    snapshot["info"]["description"] = (
        "Runtime API surface for this local build. Operation schemas remain bound to "
        "the normative OpenAPI contract snapshot."
    )
    return snapshot


def _install_operation_routes(
    app: FastAPI,
    registry: RuntimeRegistry,
    service: ExecutionService,
) -> None:
    for descriptor in registry.available_routes():
        contract = registry.contract(descriptor.operation_id)

        def endpoint(request_body, principal, *, _descriptor=descriptor):
            return service.invoke(_descriptor, request_body, principal)

        endpoint.__name__ = f"execute_{descriptor.operation_id.replace('.', '_')}"
        endpoint.__qualname__ = endpoint.__name__
        endpoint.__annotations__ = {
            "request_body": contract.request_type,
            "principal": CurrentPrincipal,
            "return": contract.response_type,
        }
        app.add_api_route(
            descriptor.path,
            endpoint,
            methods=[descriptor.method],
            name=descriptor.operation_id,
            operation_id=descriptor.operation_id,
            response_model=contract.response_type,
            status_code=200,
        )


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings.from_environment()
    runtime = create_execution_runtime(
        settings.environment,
        runs_database_url=settings.runs_database_url,
        artifact_root=settings.artifact_root,
    )
    limits = runtime.limits
    registry = runtime.registry

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(
        title="AlfaLab API",
        version="1.0.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.runs_writer = runtime.runs_writer
    app.state.execution_service = runtime.execution_service
    app.state.execution_runtime = runtime
    app.add_middleware(BodySizeLimitMiddleware, maximum_bytes=limits.request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.playground_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(SafeExecutionError, safe_execution_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    def openapi() -> dict[str, object]:
        if app.openapi_schema is None:
            app.openapi_schema = _runtime_openapi(registry)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    _install_operation_routes(app, registry, runtime.execution_service)

    @app.get("/system/catalog", response_model=CatalogOutput)
    def system_catalog(principal: CurrentPrincipal) -> CatalogOutput:
        return CatalogOutput(
            operations=list(registry.descriptors.values()),
            environment=settings.environment,
            allowed_sandboxes=sorted(principal.allowed_sandboxes),
            build_hash=runtime_build_hash(),
            readiness_report_hash=None,
        )

    @app.get("/health/live", response_model=HealthOutput)
    def health_live() -> HealthOutput:
        return HealthOutput(status="ok", build_hash=runtime_build_hash())

    @app.get("/health/ready", response_model=HealthOutput)
    def health_ready() -> HealthOutput:
        return HealthOutput(status="ok", build_hash=runtime_build_hash())

    return app


app = create_app()
