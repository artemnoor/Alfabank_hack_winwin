from __future__ import annotations

from types import SimpleNamespace

import pytest

from alfalab.modules.documents.storage.errors import ScopeDenied
from alfalab.modules.documents.storage.policy import PrincipalScopePolicy
from alfalab.modules.documents.storage.database import psycopg_url


def _context(*, tenant_id: str = "tenant-a", sandbox_id: str = "sandbox-a"):
    return SimpleNamespace(
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        environment="testing",
        principal=SimpleNamespace(
            tenant_id="tenant-a",
            actor_id="actor-1",
            role="developer",
            permissions=frozenset({"documents.register"}),
            allowed_sandboxes=frozenset({"sandbox-a"}),
        ),
    )


def test_scope_policy_resolves_only_authenticated_tenant_and_sandbox() -> None:
    scope = PrincipalScopePolicy().resolve(_context())
    assert (scope.tenant_id, scope.sandbox_id, scope.environment) == (
        "tenant-a",
        "sandbox-a",
        "testing",
    )


@pytest.mark.parametrize(
    "context",
    [
        _context(tenant_id="tenant-b"),
        _context(sandbox_id="sandbox-b"),
        SimpleNamespace(
            tenant_id="tenant-a",
            sandbox_id="sandbox-a",
            environment="production",
            principal=_context().principal,
        ),
    ],
)
def test_scope_policy_denies_untrusted_scope(context) -> None:
    with pytest.raises(ScopeDenied):
        PrincipalScopePolicy().resolve(context)


def test_database_url_uses_the_pinned_psycopg_driver() -> None:
    assert psycopg_url("postgresql://app@db.local/testing") == (
        "postgresql+psycopg://app@db.local/testing"
    )
    with pytest.raises(ValueError):
        psycopg_url("sqlite:///not-postgres.db")
