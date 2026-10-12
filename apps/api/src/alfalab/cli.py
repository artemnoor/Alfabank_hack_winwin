"""Local CLI adapter for the shared Documents.prepare execution service."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from alfalab.bootstrap.runtime import ExecutionRuntime, create_execution_runtime
from alfalab.bootstrap.settings import ApiSettings
from alfalab.execution.context import TrustedPrincipal
from alfalab.execution.errors import SafeExecutionError
from alfalab.transport.errors import safe_error_body
from alfalab_contracts import ErrorResponse


def _write_json(stream: TextIO, value: object) -> None:
    if isinstance(value, ErrorResponse):
        serialized = value.model_dump_json(indent=2)
    else:
        serialized = json.dumps(value, ensure_ascii=False, indent=2)
    stream.write(serialized)
    stream.write("\n")


def _read_bounded_input(
    stream: TextIO,
    maximum_bytes: int,
    request_path: Path | None,
) -> bytes:
    if request_path is not None:
        with request_path.open("rb") as request_file:
            raw = request_file.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            raise _InputTooLarge
        return raw

    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is not None:
        raw = binary_stream.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            raise _InputTooLarge
        return raw
    raw = stream.read(maximum_bytes + 1).encode("utf-8")
    if len(raw) > maximum_bytes:
        raise _InputTooLarge
    return raw


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alfalab")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="execute Documents.prepare from JSON")
    prepare_parser.add_argument(
        "--request",
        type=Path,
        help="read one request DTO from this UTF-8 JSON file; default: stdin",
    )
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    settings: ApiSettings | None = None,
    runtime: ExecutionRuntime | None = None,
) -> int:
    """Execute one validated operation request and write only its JSON envelope."""
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    args = _build_parser().parse_args(argv)
    if args.operation != "prepare":
        _write_json(
            error_stream,
            safe_error_body(
                code="INVALID_INPUT",
                category="validation",
                safe_message="The requested CLI operation is not available.",
            ),
        )
        return 2

    try:
        runtime_settings = settings or ApiSettings.from_environment()
        execution_runtime = runtime or create_execution_runtime(runtime_settings.environment)
    except (OSError, ValueError, ValidationError):
        _write_json(
            error_stream,
            safe_error_body(
                code="IMPLEMENTATION_UNAVAILABLE",
                category="unavailable",
                safe_message="The local execution runtime is unavailable.",
                retryable=True,
            ),
        )
        return 1

    try:
        raw_request = _read_bounded_input(
            input_stream,
            execution_runtime.limits.request_body_bytes,
            args.request,
        )
    except _InputTooLarge:
        _write_json(
            error_stream,
            safe_error_body(
                code="REQUEST_TOO_LARGE",
                category="validation",
                safe_message="The request body exceeds the configured size limit.",
            ),
        )
        return 2
    except (OSError, UnicodeError):
        _write_json(
            error_stream,
            safe_error_body(
                code="INVALID_INPUT",
                category="validation",
                safe_message="The JSON request could not be read.",
            ),
        )
        return 2

    try:
        request_value = json.loads(raw_request.decode("utf-8"))
        contract = execution_runtime.registry.contract("Documents.prepare")
        request = contract.request_type.model_validate(request_value)
    except (UnicodeDecodeError, ValueError, ValidationError, RecursionError):
        _write_json(
            error_stream,
            safe_error_body(
                code="INVALID_INPUT",
                category="validation",
                safe_message="The request does not satisfy the operation contract.",
            ),
        )
        return 2

    principal = TrustedPrincipal(
        actor_id=runtime_settings.actor_id,
        tenant_id=runtime_settings.tenant_id,
        role="developer",
        allowed_sandboxes=runtime_settings.allowed_sandboxes,
        permissions=frozenset({"documents.prepare", "catalog.read"}),
    )
    try:
        response = execution_runtime.execution_service.invoke(
            execution_runtime.registry.descriptor("Documents.prepare"),
            request,
            principal,
        )
    except SafeExecutionError as exc:
        _write_json(
            error_stream,
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
        return 1

    _write_json(output_stream, response.model_dump(mode="json"))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    return run_cli(argv)


class _InputTooLarge(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
