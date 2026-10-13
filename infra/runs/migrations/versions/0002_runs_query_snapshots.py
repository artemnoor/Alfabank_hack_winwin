"""Store bounded, scope-local immutable Runs.query page snapshots."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_runs_query_snapshots"
down_revision = "0001_runs_owner"
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
        "query_snapshots",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("query_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "sandbox_id", "snapshot_id", name="pk_query_snapshots_scope"
        ),
        sa.CheckConstraint(
            "snapshot_id ~ '^[0-9a-f]{32}$'", name="ck_query_snapshots_id"
        ),
        sa.CheckConstraint(
            "query_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_query_snapshots_fingerprint",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_query_snapshots_expiry"),
        schema="runs",
    )
    op.create_index(
        "ix_query_snapshots_scope_expiry",
        "query_snapshots",
        ["tenant_id", "sandbox_id", "expires_at"],
        schema="runs",
    )
    op.create_table(
        "query_snapshot_items",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sandbox_id", sa.Text(), nullable=False),
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_keys_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "sandbox_id",
            "snapshot_id",
            "position",
            name="pk_query_snapshot_items_scope",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "sandbox_id",
            "snapshot_id",
            "run_id",
            name="uq_query_snapshot_items_run_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sandbox_id", "snapshot_id"],
            [
                "runs.query_snapshots.tenant_id",
                "runs.query_snapshots.sandbox_id",
                "runs.query_snapshots.snapshot_id",
            ],
            name="fk_query_snapshot_items_snapshot_scope",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("position >= 0", name="ck_query_snapshot_items_position"),
        sa.CheckConstraint(
            "jsonb_typeof(record_json) = 'object'",
            name="ck_query_snapshot_items_record",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(artifact_keys_json) = 'object'",
            name="ck_query_snapshot_items_artifact_keys",
        ),
        schema="runs",
    )

    for table in ("query_snapshots", "query_snapshot_items"):
        _scope_policy(table)
        op.execute(f"REVOKE ALL ON runs.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT, DELETE ON runs.{table} TO runs_owner")
    op.execute("GRANT DELETE ON runs.spans, runs.dependencies TO runs_owner")


def downgrade() -> None:
    op.drop_table("query_snapshot_items", schema="runs")
    op.drop_index(
        "ix_query_snapshots_scope_expiry", table_name="query_snapshots", schema="runs"
    )
    op.drop_table("query_snapshots", schema="runs")
