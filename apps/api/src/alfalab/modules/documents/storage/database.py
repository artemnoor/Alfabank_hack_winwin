"""Create a pool whose effective PostgreSQL role is Documents-only."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from alfalab.common.postgres import psycopg_url


def create_documents_engine(database_url: str) -> Engine:
    """Build an owner-scoped engine from trusted server configuration.

    The login role must be explicitly granted membership in
    ``documents_owner``. The migration role is never selected by this engine.
    """

    database_url = psycopg_url(database_url)
    engine = create_engine(database_url, pool_pre_ping=True, echo=False)

    @event.listens_for(engine, "connect")
    def assume_documents_owner(
        dbapi_connection: object, _connection_record: object
    ) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("SET ROLE documents_owner")
            dbapi_connection.commit()  # type: ignore[attr-defined]
        except Exception:
            dbapi_connection.rollback()  # type: ignore[attr-defined]
            raise
        finally:
            cursor.close()

    return engine
