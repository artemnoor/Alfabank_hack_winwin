"""Shared constructors for safe API error envelopes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from alfalab_contracts import ErrorInfo, ErrorResponse


def safe_error_body(
    *,
    code: str,
    category: str,
    safe_message: str,
    retryable: bool = False,
    field_paths: Iterable[str] = (),
    outcome: str = "not_applied",
    meta: Any = None,
) -> ErrorResponse:
    """Build the same typed, sanitized wire error for every adapter."""
    return ErrorResponse(
        meta=meta,
        error=ErrorInfo(
            code=code,
            category=category,
            retryable=retryable,
            safe_message=safe_message,
            field_paths=list(field_paths),
            dependency_id=None,
            outcome=outcome,
        ),
    )
