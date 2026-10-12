"""SQLAlchemy Core metadata for the Documents-owned PostgreSQL schema."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

DOCUMENTS_SCHEMA = "documents"
CONTRACT_MAJOR = 1

metadata = MetaData(schema=DOCUMENTS_SCHEMA)

documents = Table(
    "documents",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("sandbox_id", Text, nullable=False),
    Column("document_id", Text, nullable=False),
    Column("current_revision", BigInteger, nullable=False),
    PrimaryKeyConstraint("tenant_id", "sandbox_id", "document_id", name="pk_documents_scope"),
    CheckConstraint("current_revision >= 0", name="ck_documents_current_revision_nonnegative"),
)

versions = Table(
    "versions",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("sandbox_id", Text, nullable=False),
    Column("document_id", Text, nullable=False),
    Column("revision", BigInteger, nullable=False),
    Column("kind", Text, nullable=False),
    Column("raw_artifact_hash", Text, nullable=False),
    Column("prepared_artifact_hash", Text, nullable=True),
    Column("raw_content_hash", Text, nullable=False),
    Column("semantic_hash", Text, nullable=False),
    Column("version_hash", Text, nullable=False),
    Column("parent_revision", BigInteger, nullable=True),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "tenant_id", "sandbox_id", "document_id", "revision", name="pk_versions_scope"
    ),
    ForeignKeyConstraint(
        ["tenant_id", "sandbox_id", "document_id"],
        [
            "documents.documents.tenant_id",
            "documents.documents.sandbox_id",
            "documents.documents.document_id",
        ],
        name="fk_versions_document_scope",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "sandbox_id", "document_id", "parent_revision"],
        [
            "documents.versions.tenant_id",
            "documents.versions.sandbox_id",
            "documents.versions.document_id",
            "documents.versions.revision",
        ],
        name="fk_versions_parent_scope",
        ondelete="RESTRICT",
    ),
    CheckConstraint("revision >= 1", name="ck_versions_revision_positive"),
    CheckConstraint("parent_revision IS NULL OR parent_revision >= 1", name="ck_versions_parent_revision_positive"),
    CheckConstraint("kind IN ('raw', 'prepared')", name="ck_versions_kind"),
    CheckConstraint("raw_artifact_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_raw_artifact_hash"),
    CheckConstraint(
        "prepared_artifact_hash IS NULL OR prepared_artifact_hash ~ '^sha256:[0-9a-f]{64}$'",
        name="ck_versions_prepared_artifact_hash",
    ),
    CheckConstraint("raw_content_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_raw_content_hash"),
    CheckConstraint("semantic_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_semantic_hash"),
    CheckConstraint("version_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_version_hash"),
)
Index(
    "ix_versions_scope_recorded_revision",
    versions.c.tenant_id,
    versions.c.sandbox_id,
    versions.c.document_id,
    versions.c.recorded_at,
    versions.c.revision,
)

command_claims = Table(
    "command_claims",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("sandbox_id", Text, nullable=False),
    Column("operation_id", Text, nullable=False),
    Column("contract_major", BigInteger, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    PrimaryKeyConstraint(
        "tenant_id",
        "sandbox_id",
        "operation_id",
        "contract_major",
        "idempotency_key",
        name="pk_command_claims_scope",
    ),
    CheckConstraint("contract_major >= 1", name="ck_command_claims_major_positive"),
)

command_receipts = Table(
    "command_receipts",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("sandbox_id", Text, nullable=False),
    Column("operation_id", Text, nullable=False),
    Column("contract_major", BigInteger, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("command_hash", Text, nullable=False),
    Column("original_run_id", Text, nullable=False),
    Column("audit_id", Text, nullable=False),
    Column("committed_at", DateTime(timezone=True), nullable=False),
    Column("receipt_json", JSONB, nullable=False),
    Column("response_schema_id", Text, nullable=False),
    Column("response_schema_version", Text, nullable=False),
    Column("response_hash", Text, nullable=False),
    Column("response_payload_json", JSONB, nullable=False),
    PrimaryKeyConstraint(
        "tenant_id",
        "sandbox_id",
        "operation_id",
        "contract_major",
        "idempotency_key",
        name="pk_command_receipts_scope",
    ),
    UniqueConstraint("tenant_id", "sandbox_id", "audit_id", name="uq_command_receipts_audit_scope"),
    ForeignKeyConstraint(
        ["tenant_id", "sandbox_id", "audit_id"],
        [
            "documents.audit_entries.tenant_id",
            "documents.audit_entries.sandbox_id",
            "documents.audit_entries.audit_id",
        ],
        name="fk_command_receipts_audit_scope",
        ondelete="RESTRICT",
    ),
    CheckConstraint("contract_major >= 1", name="ck_command_receipts_major_positive"),
    CheckConstraint("command_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_command_receipts_command_hash"),
    CheckConstraint("response_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_command_receipts_response_hash"),
)

audit_entries = Table(
    "audit_entries",
    metadata,
    Column("tenant_id", Text, nullable=False),
    Column("sandbox_id", Text, nullable=False),
    Column("audit_id", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("operation_id", Text, nullable=False),
    Column("command_hash", Text, nullable=False),
    Column("before_refs", JSONB, nullable=False),
    Column("after_refs", JSONB, nullable=False),
    Column("committed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("tenant_id", "sandbox_id", "audit_id", name="pk_audit_entries_scope"),
    CheckConstraint("command_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_audit_entries_command_hash"),
)
