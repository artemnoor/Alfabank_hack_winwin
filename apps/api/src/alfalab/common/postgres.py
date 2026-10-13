"""PostgreSQL URL normalization shared across owner modules."""


def psycopg_url(database_url: str) -> str:
    """Normalize a trusted PostgreSQL URL to the pinned Psycopg 3 driver."""

    if not database_url or "@" not in database_url:
        raise ValueError("a server-configured PostgreSQL URL is required")
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("storage requires PostgreSQL with psycopg")
    return database_url
