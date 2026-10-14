"""Local append-only guard for the T08 live-call budget and duplicate cases."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jev_spike import (
    SpikeError,
    load_verified_inputs,
    make_request,
    request_hash,
)

MAX_CUMULATIVE_ATTEMPTS = 50
HISTORICAL_CASE_ID = "e01-supply-rail"
HISTORICAL_REQUEST_SHA256 = (
    "a5d7356b04bce548810847dbbd297792c5da0c05733d4124863d48fd87e5d592"
)
HISTORICAL_LEGACY_REQUEST_SHA256 = (
    "32267acce614055107a4c627a29167d0b9d19603d412c0a6722df3a0f1558291"
)
LEDGER_SCHEMA_VERSION = 1


def default_ledger_path() -> Path:
    state_root = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_STATE_HOME")
        or str(Path.home() / ".local" / "state")
    )
    return Path(state_root) / "AlfaBankHackathon" / "T08" / "live-attempts.json"


class AttemptLedger:
    """Reserve a case hash before a network call; failed calls consume the budget."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_ledger_path()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @staticmethod
    def _seed() -> dict[str, Any]:
        # The pinned experiment already consumed its full 50-call ceiling:
        # 49 non-empty baseline cases via Polza plus one recorded legacy
        # TypeSafe request for e01. New local state must not reopen that budget.
        taxonomy, _corpus, cases = load_verified_inputs()
        attempts = []
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        for case in cases:
            if case["expected_status"] == "no_content":
                continue
            digest = request_hash(make_request(case, taxonomy))
            if case["id"] == HISTORICAL_CASE_ID and digest != HISTORICAL_REQUEST_SHA256:
                raise SpikeError("pinned_historical_request_changed")
            attempts.append(
                {
                    "case_id": case["id"],
                    "request_sha256": digest,
                    "timestamp_utc": timestamp,
                    "record_type": "historical_recorded_attempt",
                }
            )
        attempts.append(
            {
                "case_id": "legacy-typesafe-e01-failed",
                "request_sha256": HISTORICAL_LEGACY_REQUEST_SHA256,
                "timestamp_utc": timestamp,
                "record_type": "historical_recorded_attempt",
            }
        )
        if len(attempts) != MAX_CUMULATIVE_ATTEMPTS:
            raise SpikeError("pinned_live_budget_manifest_changed")
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "attempts": attempts,
        }

    def _load_or_seed(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = self._seed()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpikeError("live_attempt_ledger_invalid") from exc
        if (
            not isinstance(data, dict)
            or set(data) != {"schema_version", "attempts"}
            or data.get("schema_version") != LEDGER_SCHEMA_VERSION
            or not isinstance(data.get("attempts"), list)
            or len(data["attempts"]) > MAX_CUMULATIVE_ATTEMPTS
        ):
            raise SpikeError("live_attempt_ledger_invalid")
        case_ids: set[str] = set()
        hashes: set[str] = set()
        for entry in data["attempts"]:
            if (
                not isinstance(entry, dict)
                or set(entry)
                != {"case_id", "request_sha256", "timestamp_utc", "record_type"}
                or not isinstance(entry["case_id"], str)
                or not entry["case_id"]
                or not isinstance(entry["request_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["request_sha256"])
                or not isinstance(entry["timestamp_utc"], str)
                or entry["record_type"]
                not in {"historical_recorded_attempt", "reserved_before_request"}
            ):
                raise SpikeError("live_attempt_ledger_invalid")
            if entry["case_id"] in case_ids or entry["request_sha256"] in hashes:
                raise SpikeError("live_attempt_ledger_invalid")
            case_ids.add(entry["case_id"])
            hashes.add(entry["request_sha256"])
        if not data["attempts"]:
            raise SpikeError("live_attempt_ledger_invalid")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".t08-live-attempts-", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def count(self) -> int:
        with self._locked():
            data = self._load_or_seed()
            if not self.path.exists():
                self._write(data)
            return len(data["attempts"])

    def reserve(self, case_id: str, request_sha256: str) -> tuple[int, int]:
        if not isinstance(case_id, str) or not case_id:
            raise SpikeError("live_attempt_case_invalid")
        if not isinstance(request_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", request_sha256
        ):
            raise SpikeError("live_attempt_hash_invalid")
        with self._locked():
            data = self._load_or_seed()
            if not self.path.exists():
                self._write(data)
            attempts = data["attempts"]
            if any(
                entry["case_id"] == case_id or entry["request_sha256"] == request_sha256
                for entry in attempts
            ):
                raise SpikeError("request_already_in_live_ledger")
            if len(attempts) >= MAX_CUMULATIVE_ATTEMPTS:
                raise SpikeError("cumulative_live_call_limit_reached")
            previous_count = len(attempts)
            attempts.append(
                {
                    "case_id": case_id,
                    "request_sha256": request_sha256,
                    "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                    "record_type": "reserved_before_request",
                }
            )
            self._write(data)
            return previous_count, len(attempts)

    def record_historical_attempt(
        self, case_id: str, request_sha256: str, timestamp_utc: str
    ) -> tuple[int, int]:
        """Reconcile a known completed request omitted before ledger creation."""
        if not isinstance(case_id, str) or not case_id:
            raise SpikeError("live_attempt_case_invalid")
        if not isinstance(request_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", request_sha256
        ):
            raise SpikeError("live_attempt_hash_invalid")
        if not isinstance(timestamp_utc, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)",
            timestamp_utc,
        ):
            raise SpikeError("live_attempt_timestamp_invalid")
        with self._locked():
            data = self._load_or_seed()
            if not self.path.exists():
                self._write(data)
            attempts = data["attempts"]
            if any(
                entry["case_id"] == case_id or entry["request_sha256"] == request_sha256
                for entry in attempts
            ):
                raise SpikeError("request_already_in_live_ledger")
            if len(attempts) >= MAX_CUMULATIVE_ATTEMPTS:
                raise SpikeError("cumulative_live_call_limit_reached")
            previous_count = len(attempts)
            attempts.append(
                {
                    "case_id": case_id,
                    "request_sha256": request_sha256,
                    "timestamp_utc": timestamp_utc,
                    "record_type": "historical_recorded_attempt",
                }
            )
            self._write(data)
            return previous_count, len(attempts)
