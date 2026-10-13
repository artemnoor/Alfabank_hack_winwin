"""Validated storage scope shared by owner modules."""

from __future__ import annotations

from dataclasses import dataclass

from alfalab_contracts import Identifier
from pydantic import TypeAdapter

_IDENTIFIER = TypeAdapter(Identifier)


@dataclass(frozen=True, slots=True)
class TrustedScope:
    """Tenant and sandbox resolved by authentication and server policy."""

    tenant_id: str
    sandbox_id: str
    environment: str


def validate_scope(scope: TrustedScope) -> None:
    """Reject values that could escape a scoped storage root."""

    if scope.environment not in {"development", "testing"}:
        raise ValueError("only development and testing storage profiles are supported")
    for name, value in (
        ("tenant_id", scope.tenant_id),
        ("sandbox_id", scope.sandbox_id),
    ):
        if (
            not value
            or value in {".", ".."}
            or any(char in value for char in "/\\\x00")
        ):
            raise ValueError(f"invalid trusted {name}")
        _IDENTIFIER.validate_python(value, strict=True)
