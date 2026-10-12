from __future__ import annotations

from types import SimpleNamespace

import pytest

from alfalab.common.protocols import TrustedContextError, validate_trusted_scope
from fixtures.validate import (
    _require_non_empty_success_result,
    canonical_hash,
    validate_fixture_set,
)


def test_all_approved_fixtures_and_consumer_bindings_validate() -> None:
    counts = validate_fixture_set()

    assert counts["operations"] == 25
    assert counts["bindings"] == 25
    assert counts["datasets"] == 2
    assert counts["fixtures"] >= 25


def test_canonical_hash_is_order_independent_and_unicode_safe() -> None:
    assert canonical_hash({"текст": "учебный", "a": [1, True]}) == canonical_hash(
        {"a": [1, True], "текст": "учебный"}
    )
    assert canonical_hash({"value": "ё"}) != canonical_hash({"value": "е"})


def test_operation_requires_non_empty_success_result_case() -> None:
    with pytest.raises(ValueError, match="non-empty successful result fixture missing"):
        _require_non_empty_success_result(
            "Documents.prepare",
            {
                "empty": "result",
                "invalid-request": "schema_rejection",
                "controlled-failure": "safe_error",
            },
        )

    _require_non_empty_success_result(
        "Documents.prepare",
        {"empty": "result", "normalize": "result"},
    )


def test_context_scope_must_match_authenticated_principal() -> None:
    principal = SimpleNamespace(
        actor_id="actor-fixture-runner",
        tenant_id="tenant-fixtures-t02",
        role="fixture-runner",
        allowed_sandboxes=frozenset({"fixtures-t02"}),
        permissions=frozenset({"operation:execute"}),
    )
    context = SimpleNamespace(
        principal=principal,
        tenant_id="tenant-fixtures-t02",
        sandbox_id="fixtures-t02",
    )

    validate_trusted_scope(context)

    context.sandbox_id = "foreign-sandbox"
    with pytest.raises(TrustedContextError, match="sandbox is not authorized"):
        validate_trusted_scope(context)

    context.sandbox_id = "fixtures-t02"
    context.tenant_id = "another-tenant"
    with pytest.raises(TrustedContextError, match="tenant does not match"):
        validate_trusted_scope(context)
