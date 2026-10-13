from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from alfalab.modules.documents.storage.schema import (
    audit_entries,
    command_receipts,
    documents,
    versions,
)


_HASH = f"sha256:{'a' * 64}"


def _scope() -> tuple[str, str]:
    suffix = uuid.uuid4().hex
    return f"fk-tenant-{suffix}", f"fk-sandbox-{suffix}"


def _insert_document(connection, tenant_id: str, sandbox_id: str, document_id: str) -> None:
    connection.execute(
        insert(documents).values(
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            document_id=document_id,
            current_revision=2,
        )
    )


def _insert_version(
    connection,
    tenant_id: str,
    sandbox_id: str,
    document_id: str,
    revision: int,
    parent_revision: int | None,
) -> None:
    connection.execute(
        insert(versions).values(
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            document_id=document_id,
            revision=revision,
            kind="raw",
            raw_artifact_hash=_HASH,
            prepared_artifact_hash=None,
            raw_content_hash=_HASH,
            semantic_hash=_HASH,
            version_hash=_HASH,
            parent_revision=parent_revision,
            published_at=None,
            recorded_at=datetime.now(timezone.utc),
        )
    )


def _insert_audit(connection, tenant_id: str, sandbox_id: str, audit_id: str) -> None:
    connection.execute(
        insert(audit_entries).values(
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            audit_id=audit_id,
            actor_id="actor-test",
            operation_id="Documents.register",
            command_hash=_HASH,
            before_refs=[],
            after_refs=[],
            committed_at=datetime.now(timezone.utc),
        )
    )


def _insert_receipt(connection, tenant_id: str, sandbox_id: str, audit_id: str) -> None:
    suffix = uuid.uuid4().hex
    connection.execute(
        insert(command_receipts).values(
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            operation_id="Documents.register",
            contract_major=1,
            idempotency_key=f"key-{suffix}",
            command_hash=_HASH,
            original_run_id=f"run-{suffix}",
            audit_id=audit_id,
            committed_at=datetime.now(timezone.utc),
            receipt_json={},
            response_schema_id="documents.register.output",
            response_schema_version="1.0.0",
            response_hash=_HASH,
            response_payload_json={},
        )
    )


def _assert_fk_violation(error: pytest.ExceptionInfo[IntegrityError], name: str) -> None:
    assert name in str(error.value.orig)


def test_version_parent_and_receipt_audit_links_accept_matching_scope(documents_engine):
    tenant_id, sandbox_id = _scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    audit_id = f"audit-{uuid.uuid4().hex}"

    with documents_engine.begin() as connection:
        _insert_document(connection, tenant_id, sandbox_id, document_id)
        _insert_version(connection, tenant_id, sandbox_id, document_id, 1, None)
        _insert_version(connection, tenant_id, sandbox_id, document_id, 2, 1)
        _insert_audit(connection, tenant_id, sandbox_id, audit_id)
        _insert_receipt(connection, tenant_id, sandbox_id, audit_id)

        assert connection.scalar(
            select(func.count()).select_from(versions).where(
                versions.c.tenant_id == tenant_id,
                versions.c.sandbox_id == sandbox_id,
                versions.c.document_id == document_id,
            )
        ) == 2
        assert connection.scalar(
            select(func.count()).select_from(command_receipts).where(
                command_receipts.c.tenant_id == tenant_id,
                command_receipts.c.sandbox_id == sandbox_id,
                command_receipts.c.audit_id == audit_id,
            )
        ) == 1


def test_version_parent_fk_rejects_orphan_parent(documents_engine):
    tenant_id, sandbox_id = _scope()
    document_id = f"doc-{uuid.uuid4().hex}"

    with documents_engine.begin() as connection:
        _insert_document(connection, tenant_id, sandbox_id, document_id)

    with pytest.raises(IntegrityError) as error:
        with documents_engine.begin() as connection:
            _insert_version(connection, tenant_id, sandbox_id, document_id, 2, 1)
    _assert_fk_violation(error, "fk_versions_parent_scope")


@pytest.mark.parametrize("scope_mismatch", ["tenant", "sandbox"])
def test_version_parent_fk_rejects_parent_from_another_scope(documents_engine, scope_mismatch):
    tenant_id, sandbox_id = _scope()
    if scope_mismatch == "tenant":
        parent_scope = (f"{tenant_id}-other", sandbox_id)
    else:
        parent_scope = (tenant_id, f"{sandbox_id}-other")
    document_id = f"doc-{uuid.uuid4().hex}"

    with documents_engine.begin() as connection:
        _insert_document(connection, *parent_scope, document_id)
        _insert_document(connection, tenant_id, sandbox_id, document_id)
        _insert_version(connection, *parent_scope, document_id, 1, None)

    with pytest.raises(IntegrityError) as error:
        with documents_engine.begin() as connection:
            _insert_version(connection, tenant_id, sandbox_id, document_id, 2, 1)
    _assert_fk_violation(error, "fk_versions_parent_scope")


def test_receipt_audit_fk_rejects_orphan_audit(documents_engine):
    tenant_id, sandbox_id = _scope()
    audit_id = f"audit-{uuid.uuid4().hex}"

    with pytest.raises(IntegrityError) as error:
        with documents_engine.begin() as connection:
            _insert_receipt(connection, tenant_id, sandbox_id, audit_id)
    _assert_fk_violation(error, "fk_command_receipts_audit_scope")


@pytest.mark.parametrize("scope_mismatch", ["tenant", "sandbox"])
def test_receipt_audit_fk_rejects_audit_from_another_scope(documents_engine, scope_mismatch):
    tenant_id, sandbox_id = _scope()
    if scope_mismatch == "tenant":
        audit_scope = (f"{tenant_id}-other", sandbox_id)
    else:
        audit_scope = (tenant_id, f"{sandbox_id}-other")
    audit_id = f"audit-{uuid.uuid4().hex}"

    with documents_engine.begin() as connection:
        _insert_audit(connection, *audit_scope, audit_id)

    with pytest.raises(IntegrityError) as error:
        with documents_engine.begin() as connection:
            _insert_receipt(connection, tenant_id, sandbox_id, audit_id)
    _assert_fk_violation(error, "fk_command_receipts_audit_scope")
