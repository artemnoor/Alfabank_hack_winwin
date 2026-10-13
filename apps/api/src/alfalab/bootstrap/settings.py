"""Server-side settings for the supported local API and CLI profiles."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import URL


@dataclass(frozen=True, slots=True)
class ApiSettings:
    developer_token: str | None
    environment: str
    actor_id: str
    tenant_id: str
    allowed_sandboxes: frozenset[str]
    playground_origins: tuple[str, ...]
    runs_database_url: str | None = field(default=None, repr=False)
    artifact_root: Path | None = field(default=None, repr=False)

    @classmethod
    def from_environment(cls) -> ApiSettings:
        environment = os.environ.get("ALFALAB_ENVIRONMENT", "development")
        if environment not in {"development", "testing"}:
            raise ValueError(
                "the T03 local runtime does not support a production profile"
            )
        token = os.environ.get("ALFALAB_DEV_TOKEN")
        sandbox_values = os.environ.get("ALFALAB_ALLOWED_SANDBOXES", "demo-a").split(
            ","
        )
        sandboxes = frozenset(
            value.strip() for value in sandbox_values if value.strip()
        )
        origins = os.environ.get(
            "ALFALAB_PLAYGROUND_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        database_url = os.environ.get(
            "ALFALAB_RUNS_DATABASE_URL"
        ) or _profile_database_url(environment)
        artifact_root = (
            Path(
                os.environ.get(
                    "ALFALAB_ARTIFACT_ROOT",
                    str(Path(__file__).resolve().parents[5] / ".local" / "artifacts"),
                )
            )
            .expanduser()
            .resolve()
        )
        return cls(
            developer_token=token,
            environment=environment,
            actor_id=os.environ.get("ALFALAB_ACTOR_ID", "local-developer"),
            tenant_id=os.environ.get("ALFALAB_TENANT_ID", "local-tenant"),
            allowed_sandboxes=sandboxes,
            playground_origins=tuple(
                origin.strip() for origin in origins if origin.strip()
            ),
            runs_database_url=database_url,
            artifact_root=artifact_root,
        )


def _profile_database_url(environment: str) -> str | None:
    """Read the ignored local profile without exposing its credential in errors."""
    root = Path(__file__).resolve().parents[5]
    profile_path = root / ".local" / f"{environment}.json"
    if not profile_path.is_file():
        return None
    try:
        value = json.loads(profile_path.read_text(encoding="utf-8"))
        return URL.create(
            "postgresql+psycopg",
            username=value["username"],
            password=value["password"],
            host=value["host"],
            port=int(value["port"]),
            database=value["database"],
            query={"sslmode": value.get("sslmode", "disable")},
        ).render_as_string(hide_password=False)
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("the local PostgreSQL profile is malformed") from None
