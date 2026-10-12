"""Alembic environment for the Documents owner schema."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from alfalab.modules.documents.storage.database import psycopg_url
from alfalab.modules.documents.storage.schema import DOCUMENTS_SCHEMA, metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_offline() -> None:
    raise RuntimeError("offline Documents migrations are disabled; use a scoped migration connection")


def run_migrations_online() -> None:
    database_url = os.environ.get("ALFALAB_MIGRATION_DATABASE_URL")
    if not database_url:
        raise RuntimeError("ALFALAB_MIGRATION_DATABASE_URL is required")
    engine = create_engine(psycopg_url(database_url), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET ROLE documents_migrator")
            connection.commit()
            with connection.begin():
                context.configure(
                    connection=connection,
                    target_metadata=metadata,
                    include_schemas=True,
                    version_table_schema=DOCUMENTS_SCHEMA,
                    compare_type=True,
                )
                with context.begin_transaction():
                    context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
