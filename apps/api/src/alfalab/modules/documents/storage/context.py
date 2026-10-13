"""Trusted owner scope values used by storage boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from alfalab_contracts import Identifier
from pydantic import TypeAdapter

from alfalab.common.canonical import canonical_hash
from alfalab.common.protocols import DomainClockPort
from alfalab.common.scope import TrustedScope, validate_scope

from .errors import ScopeDenied

if TYPE_CHECKING:
    from .policy import ScopePolicy


_IDENTIFIER = TypeAdapter(Identifier)

__all__ = ["TrustedScope", "validate_scope"]


class TrustedPrincipal(Protocol):
    """Authentication facts that are never taken from an operation payload."""

    tenant_id: str
    actor_id: str
    role: str
    permissions: frozenset[str]
    allowed_sandboxes: frozenset[str]


class OperationContext(Protocol):
    """Structural subset of the shared T02 execution context."""

    principal: TrustedPrincipal
    tenant_id: str
    sandbox_id: str
    environment: str
    run_id: str
    operation_id: str
    request_id: str
    contract_version: str
    idempotency_key: str | None
    implementation_id: str
    implementation_version: str
    implementation_configuration_hash: str
    domain_clock: DomainClockPort


@dataclass(frozen=True, slots=True)
class OwnerCommandContext:
    """Trusted command facts used for authorization and idempotency hashing.

    ``run_id`` is recorded in the receipt but deliberately excluded from the
    semantic command hash. Request IDs, run IDs, timeout and retry metadata do
    not change the meaning of a command.
    """

    scope: TrustedScope
    actor_id: str
    permissions: frozenset[str]
    run_id: str
    operation_id: str
    contract_major: int
    idempotency_key: str
    implementation_fingerprint: str


def owner_command_context(
    context: OperationContext,
    *,
    scope_policy: ScopePolicy | None = None,
) -> OwnerCommandContext:
    """Validate shared trusted scope and adapt it to the transaction helper."""

    if scope_policy is None:
        from .policy import DEFAULT_SCOPE_POLICY

        scope_policy = DEFAULT_SCOPE_POLICY
    scope = scope_policy.resolve(context)
    principal = context.principal
    if not principal.actor_id:
        raise ScopeDenied(
            "trusted principal identity or permission scope is unavailable"
        )
    if not context.idempotency_key:
        raise ScopeDenied("trusted idempotency key is unavailable")
    if not context.operation_id or not context.contract_version:
        raise ScopeDenied("trusted operation metadata is unavailable")
    _IDENTIFIER.validate_python(principal.actor_id, strict=True)
    _IDENTIFIER.validate_python(context.run_id, strict=True)
    _IDENTIFIER.validate_python(context.idempotency_key, strict=True)
    _IDENTIFIER.validate_python(context.operation_id, strict=True)
    try:
        contract_major = int(context.contract_version.split(".", 1)[0])
    except (AttributeError, ValueError) as exc:
        raise ScopeDenied("trusted contract version is invalid") from exc
    if contract_major < 1:
        raise ScopeDenied("trusted contract version is invalid")
    implementation_fingerprint = canonical_hash(
        {
            "implementation_id": context.implementation_id,
            "implementation_version": context.implementation_version,
            "configuration_hash": context.implementation_configuration_hash,
        }
    )
    return OwnerCommandContext(
        scope=scope,
        actor_id=principal.actor_id,
        permissions=principal.permissions,
        run_id=context.run_id,
        operation_id=context.operation_id,
        contract_major=contract_major,
        idempotency_key=context.idempotency_key,
        implementation_fingerprint=implementation_fingerprint,
    )
