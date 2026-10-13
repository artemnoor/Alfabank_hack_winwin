"""Translate internal validation and execution failures to safe wire errors."""

from __future__ import annotations

from typing import get_args, get_origin

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from alfalab_contracts import ErrorResponse

from alfalab.execution.errors import SafeExecutionError
from alfalab.transport.errors import safe_error_body


def _json_response(status_code: int, body: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _model_for_union(annotation: object) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for option in get_args(annotation):
        nested = _model_for_union(option)
        if nested is not None:
            return nested
    return None


def _safe_field_path(model_type: type[BaseModel], location: tuple[object, ...]) -> str | None:
    parts = list(location)
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts.pop(0)
    current: object = model_type
    safe_parts: list[str] = []
    for part in parts:
        if isinstance(part, int):
            origin = get_origin(current)
            arguments = get_args(current)
            if origin in {list, tuple} and arguments:
                safe_parts.append(str(part))
                current = arguments[0]
            else:
                break
        elif isinstance(part, str):
            nested_model = _model_for_union(current)
            if nested_model is None or part not in nested_model.model_fields:
                break
            safe_parts.append(part)
            current = nested_model.model_fields[part].annotation
        else:
            break
    return ".".join(safe_parts) or None


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    body_field = getattr(request.scope.get("route"), "body_field", None)
    model_type = getattr(body_field, "type_", None)
    if not isinstance(model_type, type) or not issubclass(model_type, BaseModel):
        model_type = BaseModel
    paths = {
        path
        for error in exc.errors()
        if (path := _safe_field_path(model_type, tuple(error.get("loc", ())))) is not None
    }
    return _json_response(
        422,
        safe_error_body(
            code="INVALID_INPUT",
            category="validation",
            safe_message="The request does not satisfy the operation contract.",
            field_paths=sorted(paths),
        ),
    )


async def safe_execution_error_handler(request: Request, exc: SafeExecutionError) -> JSONResponse:
    del request
    return _json_response(
        exc.status_code,
        safe_error_body(
            code=exc.code,
            category=exc.category,
            safe_message=exc.safe_message,
            retryable=exc.retryable,
            field_paths=exc.field_paths,
            outcome=exc.outcome,
            meta=exc.meta,
        ),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Keep the exception itself out of both the response and application logs.
    del request, exc
    return _json_response(
        500,
        safe_error_body(
            code="INTERNAL_ERROR",
            category="internal",
            safe_message="The request could not be completed.",
            outcome="unknown",
        ),
    )
