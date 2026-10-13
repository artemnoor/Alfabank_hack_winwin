"""Create tenant-scoped Runs history and immutable artifact metadata."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_runs_owner"
down_revision = None
branch_labels = None
depends_on = None


def _scope_policy(table: str) -> None:
    op.execute(f"ALTER TABLE runs.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE runs.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""CREATE POLICY {table}_scope ON runs.{table}
        USING (
            tenant_id = current_setting('alfalab.tenant_id', true)
            AND sandbox_id = current_setting('alfalab.sandbox_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('alfalab.tenant_id', true)
            AND sandbox_id = current_setting('alfalab.sandbox_id', true)
        )"""
    )


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("scenario_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("analytical_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.PrimaryKeyConstraint("tenant_id", "sandbox_id", "run_id", name="pk_runs_scope"),
        sa.CheckConstraint("status IN ('running', 'success', 'partial', 'abstained', 'failed', 'cancelled', 'unknown')", name="ck_runs_status"),
        sa.CheckConstraint("input_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_runs_input_hash"),
        sa.CheckConstraint("random_seed >= 0", name="ck_runs_seed_nonnegative"),
        sa.CheckConstraint("jsonb_typeof(record_json) = 'object'", name="ck_runs_record_object"),
        schema="runs",
    )
    op.create_index(
        "ix_runs_scope_created",
        "runs",
        ["tenant_id", "sandbox_id", sa.text("created_at DESC"), sa.text("run_id DESC")],
        schema="runs",
    )
    op.create_index(
        "ix_runs_scope_operation_created",
        "runs",
        ["tenant_id", "sandbox_id", "operation_id", sa.text("created_at DESC"), sa.text("run_id DESC")],
        schema="runs",
    )
    op.create_index(
        "ix_runs_scope_scenario_created",
        "runs",
        ["tenant_id", "sandbox_id", "scenario_id", sa.text("created_at DESC"), sa.text("run_id DESC")],
        schema="runs",
    )

    op.create_table(
        "spans",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("span_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "sandbox_id", "run_id", "sequence", name="pk_spans_scope"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sandbox_id", "run_id"],
            ["runs.runs.tenant_id", "runs.runs.sandbox_id", "runs.runs.run_id"],
            name="fk_spans_run_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_spans_sequence_nonnegative"),
        sa.CheckConstraint("jsonb_typeof(span_json) = 'object'", name="ck_spans_record_object"),
        schema="runs",
    )

    op.create_table(
        "dependencies",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("dependency_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "sandbox_id", "run_id", "sequence", name="pk_dependencies_scope"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sandbox_id", "run_id"],
            ["runs.runs.tenant_id", "runs.runs.sandbox_id", "runs.runs.run_id"],
            name="fk_dependencies_run_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_dependencies_sequence_nonnegative"),
        sa.CheckConstraint("jsonb_typeof(dependency_json) = 'object'", name="ck_dependencies_record_object"),
        schema="runs",
    )

    op.create_table(
        "artifacts",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("artifact_hash", sa.Text(), nullable=False),
        sa.Column("schema_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.PrimaryKeyConstraint("tenant_id", "sandbox_id", "run_id", "artifact_id", name="pk_artifacts_scope"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sandbox_id", "run_id"],
            ["runs.runs.tenant_id", "runs.runs.sandbox_id", "runs.runs.run_id"],
            name="fk_artifacts_run_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("artifact_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_artifacts_hash"),
        sa.CheckConstraint("size_bytes BETWEEN 0 AND 2097152", name="ck_artifacts_size"),
        sa.CheckConstraint(
            r"storage_key IS NULL OR (storage_key !~ '^/' AND storage_key !~ '(^|/)\.\.(/|$)' AND position(chr(92) in storage_key) = 0)",
            name="ck_artifacts_relative_key",
        ),
        sa.CheckConstraint("classification IN ('synthetic', 'public', 'unknown')", name="ck_artifacts_classification"),
        sa.CheckConstraint("media_type IN ('application/json', 'text/plain')", name="ck_artifacts_media_type"),
        schema="runs",
    )

    for table in ("runs", "spans", "dependencies", "artifacts"):
        _scope_policy(table)
        op.execute(f"REVOKE ALL ON runs.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON runs.{table} TO runs_owner")

    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA runs FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA runs TO runs_owner")


def downgrade() -> None:
    for table in ("artifacts", "dependencies", "spans", "runs"):
        op.drop_table(table, schema="runs")
