"""Trusted tenant/sandbox scope policy for Documents owner access."""

from __future__ import annotations

from typing import Protocol

from .context import OperationContext, TrustedScope, validate_scope
from .errors import ScopeDenied

DOCUMENTS_REGISTER_PERMISSION = "documents.register"
DOCUMENTS_READ_PERMISSION = "documents.read"


class ScopePolicy(Protocol):
    """Resolve a caller-selected sandbox only within trusted principal scope."""

    def resolve(self, context: OperationContext) -> TrustedScope: ...


class PrincipalScopePolicy:
    """Allow only the authenticated tenant and explicitly allowed sandboxes."""

    def resolve(self, context: OperationContext) -> TrustedScope:
        scope = TrustedScope(context.tenant_id, context.sandbox_id, context.environment)
        try:
            validate_scope(scope)
        except ValueError as exc:
            raise ScopeDenied("requested owner scope is invalid") from exc
        principal = context.principal
        if principal.tenant_id != scope.tenant_id or scope.sandbox_id not in principal.allowed_sandboxes:
            raise ScopeDenied("principal is not authorized for this tenant and sandbox")
        return scope


def require_permission(context: OperationContext, permission: str) -> None:
    """Require an operation permission from the trusted principal context."""

    if permission not in context.principal.permissions:
        raise ScopeDenied("principal lacks permission for this Documents operation")


DEFAULT_SCOPE_POLICY = PrincipalScopePolicy()
