"""Safe execution failures mapped to the public error envelope."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SafeExecutionError(Exception):
    status_code: int
    code: str
    category: str
    safe_message: str
    retryable: bool = False
    field_paths: tuple[str, ...] = ()
    outcome: str = "not_applied"
    meta: object | None = None


def invalid_input(*field_paths: str) -> SafeExecutionError:
    return SafeExecutionError(
        status_code=422,
        code="INVALID_INPUT",
        category="validation",
        safe_message="The request does not satisfy the operation contract.",
        field_paths=tuple(field_paths),
    )
