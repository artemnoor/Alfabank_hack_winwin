"""Opaque, scope- and filter-bound Runs snapshot cursors."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass


def _digest(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class CursorState:
    snapshot_id: str
    after_position: int


def encode_cursor(
    *,
    snapshot_id: str,
    after_position: int,
    tenant_id: str,
    sandbox_id: str,
    query_fingerprint: str,
) -> str:
    body = {
        "v": 2,
        "snapshot_id": snapshot_id,
        "after_position": after_position,
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
        snapshot_id = data.get("snapshot_id") if isinstance(data, dict) else None
        after_position = data.get("after_position") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or data.get("v") != 2
            or data.get("scope") != _digest([tenant_id, sandbox_id])
            or data.get("query") != query_fingerprint
            or not isinstance(snapshot_id, str)
            or re.fullmatch(r"[0-9a-f]{32}", snapshot_id) is None
            or type(after_position) is not int
            or after_position < 1
        ):
            return None
        return CursorState(snapshot_id, after_position)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def query_fingerprint(payload: object) -> str:
    if hasattr(payload, "model_dump"):
        value = payload.model_dump(mode="json")  # type: ignore[union-attr]
        if isinstance(value, dict):
            value.pop("cursor", None)
            return _digest(value)
    return _digest(payload)
