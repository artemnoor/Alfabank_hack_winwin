"""Opaque, scope- and filter-bound Runs pagination cursors."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class CursorState:
    snapshot_at: datetime
    after_created_at: datetime
    after_run_id: str


def encode_cursor(
    *,
    snapshot_at: datetime,
    after_created_at: datetime,
    after_run_id: str,
    tenant_id: str,
    sandbox_id: str,
    query_fingerprint: str,
) -> str:
    body = {
        "v": 1,
        "snapshot_at": snapshot_at.isoformat(),
        "after_created_at": after_created_at.isoformat(),
        "after_run_id": after_run_id,
        "scope": _digest([tenant_id, sandbox_id]),
        "query": query_fingerprint,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(
    value: str,
    *,
    tenant_id: str,
    sandbox_id: str,
    query_fingerprint: str,
) -> CursorState | None:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("v") != 1
            or data.get("scope") != _digest([tenant_id, sandbox_id])
            or data.get("query") != query_fingerprint
            or not isinstance(data.get("after_run_id"), str)
        ):
            return None
        snapshot_at = datetime.fromisoformat(data["snapshot_at"])
        after_created_at = datetime.fromisoformat(data["after_created_at"])
        if snapshot_at.tzinfo is None or after_created_at.tzinfo is None:
            return None
        return CursorState(snapshot_at, after_created_at, data["after_run_id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def query_fingerprint(payload: object) -> str:
    if hasattr(payload, "model_dump"):
        value = payload.model_dump(mode="json")  # type: ignore[union-attr]
        if isinstance(value, dict):
            value.pop("cursor", None)
            return _digest(value)
    return _digest(payload)
