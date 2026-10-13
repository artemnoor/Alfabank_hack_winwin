"""Canonical JSON encoding and fingerprints shared across module owners."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically, including Pydantic DTOs."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hash(content: bytes) -> str:
    """Return the framework's prefixed SHA-256 representation."""

    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def canonical_hash(value: Any) -> str:
    """Hash canonical JSON with the same encoding used by immutable artifacts."""

    return sha256_hash(canonical_json_bytes(value))
