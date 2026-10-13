from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = ROOT / "apps" / "api" / "src"
if str(API_SOURCE) not in sys.path:
    sys.path.insert(0, str(API_SOURCE))


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
