"""Persist trusted artifact sizes for bounded Documents reads."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_documents_artifact_sizes"
down_revision = "0001_documents_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column("raw_artifact_size_bytes", sa.BigInteger(), nullable=True),
        schema="documents",
    )
    op.add_column(
        "versions",
        sa.Column("prepared_artifact_size_bytes", sa.BigInteger(), nullable=True),
        schema="documents",
    )
    op.create_check_constraint(
        "ck_versions_raw_artifact_size",
        "versions",
        "raw_artifact_size_bytes IS NULL OR raw_artifact_size_bytes BETWEEN 0 AND 2097152",
        schema="documents",
    )
    op.create_check_constraint(
        "ck_versions_prepared_artifact_size",
        "versions",
        "prepared_artifact_size_bytes IS NULL OR prepared_artifact_size_bytes BETWEEN 0 AND 2097152",
        schema="documents",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_versions_prepared_artifact_size",
        "versions",
        schema="documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_versions_raw_artifact_size",
        "versions",
        schema="documents",
        type_="check",
    )
    op.drop_column("versions", "prepared_artifact_size_bytes", schema="documents")
    op.drop_column("versions", "raw_artifact_size_bytes", schema="documents")
