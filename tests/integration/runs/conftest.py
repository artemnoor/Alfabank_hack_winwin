from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = ROOT / "apps" / "api" / "src"
if str(API_SOURCE) not in sys.path:
    sys.path.insert(0, str(API_SOURCE))

from alfalab.common.postgres import psycopg_url


def _url_text(url: URL) -> str:
    return url.render_as_string(hide_password=False)


@dataclass(frozen=True, slots=True)
class RunsTestDatabase:
    admin_url: str = field(repr=False)
    owner_url: str = field(repr=False)


class _RedactedDsn(str):
    """Keep transient test credentials out of pytest parameter output."""

    def __repr__(self) -> str:
        return "<redacted database URL>"


@pytest.fixture(scope="session")
def runs_test_database() -> RunsTestDatabase:
    configured_admin = os.environ.get("ALFALAB_T05_ADMIN_DSN")
    if not configured_admin:
        pytest.skip("set ALFALAB_T05_ADMIN_DSN to run isolated Runs PostgreSQL tests")

    database_name = f"alfalab_t05_{uuid.uuid4().hex[:12]}"
    admin_url = make_url(psycopg_url(configured_admin))
    maintenance_url = admin_url.set(database="postgres")
    admin_engine = create_engine(maintenance_url, pool_pre_ping=True, echo=False)
    created = False
    try:
        with admin_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            created = True

        database_url = _url_text(admin_url.set(database=database_name))
        database_engine = create_engine(database_url, pool_pre_ping=True, echo=False)
        try:
            raw = database_engine.raw_connection()
            try:
                cursor = raw.cursor()
                try:
                    script = (
                        ROOT / "infra" / "bootstrap" / "runs_roles.sql"
                    ).read_text(encoding="utf-8")
                    cursor.execute(script, prepare=False)
                    raw.commit()
                finally:
                    cursor.close()
            finally:
                raw.close()
        finally:
            database_engine.dispose()

        prior_migration_url = os.environ.get("ALFALAB_RUNS_MIGRATION_DATABASE_URL")
        os.environ["ALFALAB_RUNS_MIGRATION_DATABASE_URL"] = database_url
        try:
            config = Config(str(ROOT / "infra" / "runs" / "alembic.ini"))
            command.upgrade(config, "head")
        finally:
            if prior_migration_url is None:
                os.environ.pop("ALFALAB_RUNS_MIGRATION_DATABASE_URL", None)
            else:
                os.environ["ALFALAB_RUNS_MIGRATION_DATABASE_URL"] = prior_migration_url

        configured_owner = os.environ.get("ALFALAB_T05_OWNER_DSN")
        owner_url = (
            make_url(psycopg_url(configured_owner)).set(database=database_name)
            if configured_owner
            else admin_url.set(database=database_name)
        )
        if configured_owner:
            profile_engine = create_engine(database_url, pool_pre_ping=True, echo=False)
            try:
                with profile_engine.begin() as connection:
                    login = owner_url.username
                    exists = connection.execute(
                        text("SELECT 1 FROM pg_roles WHERE rolname = :login"),
                        {"login": login},
                    ).scalar_one_or_none()
                    if exists is None:
                        raise RuntimeError(
                            "ALFALAB_T05_OWNER_DSN login role does not exist"
                        )
                    preparer = connection.dialect.identifier_preparer
                    connection.exec_driver_sql(
                        f"GRANT CONNECT ON DATABASE {preparer.quote(database_name)} TO {preparer.quote(login)}"
                    )
            finally:
                profile_engine.dispose()
        yield RunsTestDatabase(
            admin_url=_RedactedDsn(database_url),
            owner_url=_RedactedDsn(_url_text(owner_url)),
        )
    finally:
        admin_engine.dispose()
        if created:
            with (
                create_engine(maintenance_url, pool_pre_ping=True, echo=False)
                .connect()
                .execution_options(isolation_level="AUTOCOMMIT") as connection
            ):
                connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
                )


@pytest.fixture(scope="session")
def runs_database_url(runs_test_database: RunsTestDatabase) -> str:
    return runs_test_database.owner_url


@pytest.fixture(scope="session")
def runs_migration_config(runs_test_database: RunsTestDatabase) -> Config:
    prior = os.environ.get("ALFALAB_RUNS_MIGRATION_DATABASE_URL")
    os.environ["ALFALAB_RUNS_MIGRATION_DATABASE_URL"] = runs_test_database.admin_url
    config = Config(str(ROOT / "infra" / "runs" / "alembic.ini"))
    try:
        yield config
    finally:
        if prior is None:
            os.environ.pop("ALFALAB_RUNS_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["ALFALAB_RUNS_MIGRATION_DATABASE_URL"] = prior


@pytest.fixture(scope="session")
def runs_artifact_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep filesystem artifact checks outside both the repo and user data."""
    return tmp_path_factory.mktemp("t05-runs-artifacts")
