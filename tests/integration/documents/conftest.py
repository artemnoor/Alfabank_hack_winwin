from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = ROOT / "apps" / "api" / "src"
if str(API_SOURCE) not in sys.path:
    sys.path.insert(0, str(API_SOURCE))


class _RedactedDsn(str):
    def __repr__(self) -> str:
        return "<redacted PostgreSQL DSN>"


@pytest.fixture(scope="session")
def admin_dsn() -> str:
    value = os.environ.get("ALFALAB_T04_ADMIN_DSN")
    if not value:
        pytest.skip(
            "set ALFALAB_T04_ADMIN_DSN to run PostgreSQL owner integration tests"
        )
    return value


@pytest.fixture(scope="session", autouse=True)
def documents_migrated(admin_dsn: str) -> bool:
    from alfalab.modules.documents.storage.database import psycopg_url

    admin_dsn = psycopg_url(admin_dsn)
    engine = create_engine(admin_dsn, pool_pre_ping=True, echo=False)
    role_script = (ROOT / "infra" / "bootstrap" / "documents_roles.sql").read_text(
        encoding="utf-8"
    )
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(role_script, prepare=False)
            raw.commit()
        finally:
            cursor.close()
    finally:
        raw.close()

    prior = os.environ.get("ALFALAB_MIGRATION_DATABASE_URL")
    os.environ["ALFALAB_MIGRATION_DATABASE_URL"] = admin_dsn
    try:
        config = Config(str(ROOT / "infra" / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if prior is None:
            os.environ.pop("ALFALAB_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["ALFALAB_MIGRATION_DATABASE_URL"] = prior
        engine.dispose()
    return True


@pytest.fixture
def documents_engine(admin_dsn: str, documents_migrated: bool):
    from alfalab.modules.documents.storage.database import create_documents_engine

    owner_dsn = os.environ.get("ALFALAB_T04_OWNER_DSN", admin_dsn)
    engine = create_documents_engine(owner_dsn)
    yield engine
    engine.dispose()


@pytest.fixture
def documents_storage(documents_engine):
    from alfalab.modules.documents.storage.artifacts import ArtifactStore
    from alfalab.modules.documents.storage.service import DocumentsStorage

    root = ROOT / ".local" / "artifacts"
    # These owner transaction tests use synthetic test payloads. The runtime
    # policy gate is exercised separately with the strict approved-source catalog.
    return DocumentsStorage(
        documents_engine,
        ArtifactStore(root),
        trusted_material=lambda _material, _context: True,
        trusted_content_hash=lambda _content_hash: True,
    )


@pytest.fixture
def documents_runs_database(admin_dsn: str) -> str:
    """Create an isolated database with both real owner schemas migrated."""
    from alfalab.common.postgres import psycopg_url

    admin_url = make_url(psycopg_url(admin_dsn))
    database_name = f"alfalab_t07_{uuid.uuid4().hex[:12]}"
    maintenance_url = admin_url.set(database="postgres")
    maintenance_engine = create_engine(maintenance_url, pool_pre_ping=True, echo=False)
    database_created = False
    try:
        with maintenance_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            database_created = True
    finally:
        maintenance_engine.dispose()

    database_url = admin_url.set(database=database_name).render_as_string(
        hide_password=False
    )
    env_names = (
        "ALFALAB_MIGRATION_DATABASE_URL",
        "ALFALAB_RUNS_MIGRATION_DATABASE_URL",
    )
    previous = {name: os.environ.get(name) for name in env_names}
    try:
        database_engine = create_engine(database_url, pool_pre_ping=True, echo=False)
        try:
            raw = database_engine.raw_connection()
            try:
                cursor = raw.cursor()
                try:
                    for role_script in ("documents_roles.sql", "runs_roles.sql"):
                        cursor.execute(
                            (ROOT / "infra" / "bootstrap" / role_script).read_text(
                                encoding="utf-8"
                            ),
                            prepare=False,
                        )
                    raw.commit()
                finally:
                    cursor.close()
            finally:
                raw.close()
        finally:
            database_engine.dispose()
        os.environ[env_names[0]] = database_url
        os.environ[env_names[1]] = database_url
        command.upgrade(Config(str(ROOT / "infra" / "alembic.ini")), "head")
        command.upgrade(Config(str(ROOT / "infra" / "runs" / "alembic.ini")), "head")
        yield _RedactedDsn(database_url)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if database_created:
            maintenance_engine = create_engine(
                maintenance_url, pool_pre_ping=True, echo=False
            )
            try:
                with maintenance_engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as connection:
                    connection.execute(
                        text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
                    )
            finally:
                maintenance_engine.dispose()
