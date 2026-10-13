"""Create scoped Documents state, transaction receipts, and owner audit."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_documents_owner"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("current_revision", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "sandbox_id", "document_id", name="pk_documents_scope"),
        sa.CheckConstraint("current_revision >= 0", name="ck_documents_current_revision_nonnegative"),
        schema="documents",
    )
    op.create_table(
        "versions",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("raw_artifact_hash", sa.Text(), nullable=False),
        sa.Column("prepared_artifact_hash", sa.Text(), nullable=True),
        sa.Column("raw_content_hash", sa.Text(), nullable=False),
        sa.Column("semantic_hash", sa.Text(), nullable=False),
        sa.Column("version_hash", sa.Text(), nullable=False),
        sa.Column("parent_revision", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "sandbox_id", "document_id", "revision", name="pk_versions_scope"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sandbox_id", "document_id"],
            ["documents.documents.tenant_id", "documents.documents.sandbox_id", "documents.documents.document_id"],
            name="fk_versions_document_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_versions_revision_positive"),
        sa.CheckConstraint("parent_revision IS NULL OR parent_revision >= 1", name="ck_versions_parent_revision_positive"),
        sa.CheckConstraint("kind IN ('raw', 'prepared')", name="ck_versions_kind"),
        sa.CheckConstraint("raw_artifact_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_raw_artifact_hash"),
        sa.CheckConstraint(
            "prepared_artifact_hash IS NULL OR prepared_artifact_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_versions_prepared_artifact_hash",
        ),
        sa.CheckConstraint("raw_content_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_raw_content_hash"),
        sa.CheckConstraint("semantic_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_semantic_hash"),
        sa.CheckConstraint("version_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_versions_version_hash"),
        schema="documents",
    )
    op.create_foreign_key(
        "fk_versions_parent_scope",
        "versions",
        "versions",
        ["tenant_id", "sandbox_id", "document_id", "parent_revision"],
        ["tenant_id", "sandbox_id", "document_id", "revision"],
        source_schema="documents",
        referent_schema="documents",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_versions_scope_recorded_revision",
        "versions",
        ["tenant_id", "sandbox_id", "document_id", "recorded_at", "revision"],
        schema="documents",
    )
    op.create_table(
        "command_claims",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("contract_major", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "sandbox_id", "operation_id", "contract_major", "idempotency_key",
            name="pk_command_claims_scope",
        ),
        sa.CheckConstraint("contract_major >= 1", name="ck_command_claims_major_positive"),
        schema="documents",
    )
    op.create_table(
        "command_receipts",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("contract_major", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("command_hash", sa.Text(), nullable=False),
        sa.Column("original_run_id", sa.Text(), nullable=False),
        sa.Column("audit_id", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receipt_json", postgresql.JSONB(), nullable=False),
        sa.Column("response_schema_id", sa.Text(), nullable=False),
        sa.Column("response_schema_version", sa.Text(), nullable=False),
        sa.Column("response_hash", sa.Text(), nullable=False),
        sa.Column("response_payload_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "sandbox_id", "operation_id", "contract_major", "idempotency_key",
            name="pk_command_receipts_scope",
        ),
        sa.UniqueConstraint("tenant_id", "sandbox_id", "audit_id", name="uq_command_receipts_audit_scope"),
        sa.CheckConstraint("contract_major >= 1", name="ck_command_receipts_major_positive"),
        sa.CheckConstraint("command_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_command_receipts_command_hash"),
        sa.CheckConstraint("response_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_command_receipts_response_hash"),
        schema="documents",
    )
    op.create_table(
        "audit_entries",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("audit_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("command_hash", sa.Text(), nullable=False),
        sa.Column("before_refs", postgresql.JSONB(), nullable=False),
        sa.Column("after_refs", postgresql.JSONB(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "sandbox_id", "audit_id", name="pk_audit_entries_scope"),
        sa.CheckConstraint("command_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_audit_entries_command_hash"),
        schema="documents",
    )
    op.create_foreign_key(
        "fk_command_receipts_audit_scope",
        "command_receipts",
        "audit_entries",
        ["tenant_id", "sandbox_id", "audit_id"],
        ["tenant_id", "sandbox_id", "audit_id"],
        source_schema="documents",
        referent_schema="documents",
        ondelete="RESTRICT",
    )

    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA documents FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA documents TO documents_owner")
    op.execute("GRANT SELECT, INSERT ON documents.documents TO documents_owner")
    op.execute(
        "GRANT UPDATE (current_revision) ON documents.documents TO documents_owner"
    )
    op.execute("GRANT SELECT, INSERT ON documents.versions TO documents_owner")
    op.execute("GRANT SELECT, INSERT, DELETE ON documents.command_claims TO documents_owner")
    op.execute("GRANT SELECT, INSERT ON documents.command_receipts TO documents_owner")
    op.execute("GRANT SELECT, INSERT ON documents.audit_entries TO documents_owner")


def downgrade() -> None:
    op.drop_table("command_receipts", schema="documents")
    op.drop_table("audit_entries", schema="documents")
    op.drop_table("command_claims", schema="documents")
    op.drop_index("ix_versions_scope_recorded_revision", table_name="versions", schema="documents")
    op.drop_table("versions", schema="documents")
    op.drop_table("documents", schema="documents")
