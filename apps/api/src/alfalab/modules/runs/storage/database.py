"""Create a PostgreSQL pool whose effective role is Runs-only."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from alfalab.common.postgres import psycopg_url


def create_runs_engine(database_url: str) -> Engine:
    """Build a trusted runtime engine that can assume only ``runs_owner``."""
    engine = create_engine(psycopg_url(database_url), pool_pre_ping=True, echo=False)

    @event.listens_for(engine, "connect")
    def assume_runs_owner(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("SET ROLE runs_owner")
            dbapi_connection.commit()  # type: ignore[attr-defined]
        except Exception:
            dbapi_connection.rollback()  # type: ignore[attr-defined]
            raise
        finally:
            cursor.close()

    return engine
