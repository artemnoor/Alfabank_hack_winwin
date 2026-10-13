"""Server-side settings for the supported local API and CLI profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApiSettings:
    developer_token: str | None
    environment: str
    actor_id: str
    tenant_id: str
    allowed_sandboxes: frozenset[str]
    playground_origins: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> ApiSettings:
        environment = os.environ.get("ALFALAB_ENVIRONMENT", "development")
        if environment not in {"development", "testing"}:
            raise ValueError("the T03 local runtime does not support a production profile")
        token = os.environ.get("ALFALAB_DEV_TOKEN")
        sandbox_values = os.environ.get("ALFALAB_ALLOWED_SANDBOXES", "demo-a").split(",")
        sandboxes = frozenset(value.strip() for value in sandbox_values if value.strip())
        origins = os.environ.get(
            "ALFALAB_PLAYGROUND_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        return cls(
            developer_token=token,
            environment=environment,
            actor_id=os.environ.get("ALFALAB_ACTOR_ID", "local-developer"),
            tenant_id=os.environ.get("ALFALAB_TENANT_ID", "local-tenant"),
            allowed_sandboxes=sandboxes,
            playground_origins=tuple(origin.strip() for origin in origins if origin.strip()),
        )
