"""Canonical typed artifact helpers shared by live and replay execution."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

from alfalab_contracts import ArtifactRef, ArtifactView

from alfalab.common.artifacts import ARTIFACT_SCHEMA_VERSION
from alfalab.modules.runs.storage.memory import InMemoryRunsRepository
from alfalab.modules.runs.storage.repository import StoredRun


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def hash_text(value: str) -> str:
    return hash_bytes(value.encode("utf-8"))


def canonical_hash(value: object) -> str:
    return hash_text(canonical_json(value))


def dependency_recording_view(
    *,
    artifact_id: str,
    schema_id: str,
    value: object,
    classification: str,
    include_content: bool,
    sensitive_values: tuple[str, ...] = (),
) -> tuple[ArtifactView, str, bool]:
    """Record a typed dependency value without retaining registered secrets."""
    value_json = canonical_json(value)
    safe_value, contains_sensitive_field = _redact_sensitive_fields(value)
    contains_sensitive_value = contains_sensitive_values(value, sensitive_values)
    is_sensitive = contains_sensitive_field or contains_sensitive_value
    safe_json = (
        canonical_json({"recording": "omitted_sensitive_fields"})
        if is_sensitive
        else canonical_json(safe_value)
    )
    if is_sensitive:
        marker = canonical_json({"recording": "omitted_sensitive_fields"})
        return (
            artifact_view(
                artifact_id=artifact_id,
                schema_id=schema_id,
                value_json=marker,
                classification=classification,
                include_content=False,
                availability="metadata_only",
            ),
            safe_json,
            True,
        )
    return (
        artifact_view(
            artifact_id=artifact_id,
            schema_id=schema_id,
            value_json=value_json,
            classification=classification,
            include_content=include_content,
        ),
        safe_json,
        False,
    )


def _redact_sensitive_fields(value: object) -> tuple[object, bool]:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        found = False
        for key, item in value.items():
            key_text = str(key)
            if _sensitive_key(key_text):
                result[key_text] = "[redacted]"
                found = True
            else:
                result[key_text], nested = _redact_sensitive_fields(item)
                found = found or nested
        return result, found
    if isinstance(value, list):
        result_list: list[object] = []
        found = False
        for item in value:
            redacted, nested = _redact_sensitive_fields(item)
            result_list.append(redacted)
            found = found or nested
        return result_list, found
    return value, False


def contains_sensitive_fields(value: object) -> bool:
    return _redact_sensitive_fields(value)[1]


def contains_sensitive_values(value: object, sensitive_values: tuple[str, ...]) -> bool:
    """Find server-registered secret values in JSON-compatible keys or values."""
    needles = tuple(secret for secret in sensitive_values if secret)
    if not needles:
        return False
    if isinstance(value, Mapping):
        return any(
            any(secret in str(key) for secret in needles)
            or contains_sensitive_values(item, needles)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_sensitive_values(item, needles) for item in value)
    if isinstance(value, str):
        return any(secret in value for secret in needles)
    return False


def contains_sensitive_data(
    value: object, sensitive_values: tuple[str, ...] = ()
) -> bool:
    return contains_sensitive_fields(value) or contains_sensitive_values(
        value, sensitive_values
    )


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    # Treat auth-prefixed fields as credentials without catching ordinary author fields.
    if normalized.startswith("auth") and not normalized.startswith("author"):
        return True
    return any(
        marker in normalized
        for marker in (
            "secret",
            "password",
            "passwd",
            "passphrase",
            "passcode",
            "pincode",
            "credential",
            "authorization",
            "apikey",
            "accesskey",
            "privatekey",
            "signingkey",
            "encryptionkey",
            "token",
            "cookie",
            "bearer",
            "session",
            "jwt",
            "xsrf",
            "csrf",
        )
    )


def artifact_view(
    *,
    artifact_id: str,
    schema_id: str,
    value_json: str,
    classification: str,
    include_content: bool,
    availability: str | None = None,
) -> ArtifactView:
    raw = value_json.encode("utf-8")
    return ArtifactView(
        ref=ArtifactRef(
            artifact_id=artifact_id,
            hash=hash_bytes(raw),
            schema_id=schema_id,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            size_bytes=len(raw),
            classification=classification,
            media_type="application/json",
        ),
        content_json=value_json if include_content else None,
        availability=availability
        or ("available" if include_content else "metadata_only"),
    )


# T03 compatibility surface retained for existing test adapters.
InMemoryRun = StoredRun
RunsWriter = InMemoryRunsRepository
__all__ = ["InMemoryRun", "RunsWriter"]
