"""Runtime timestamp helpers shared by execution adapters and storage."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


_RFC3339_UTC = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"T(?:[01]\d|2[0-3]):[0-5]\d:(?:[0-5]\d|60)"
    r"(?:\.\d+)?(?:Z|\+00:00)$"
)


def parse_utc_timestamp(value: str) -> datetime:
    """Parse an RFC3339 UTC timestamp, mapping a valid leap second forward."""
    if not _RFC3339_UTC.fullmatch(value):
        raise ValueError("timestamp must be RFC3339 with a UTC timezone")

    # Python's datetime does not represent leap seconds. Validate the calendar
    # date using second 59, then map :60 to the following instant for ordering.
    leap_second = value[17:19] == "60"
    normalized = value[:17] + "59" + value[19:] if leap_second else value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp is not a valid RFC3339 date-time") from exc
    if result.tzinfo != timezone.utc:
        raise ValueError("timestamp must use UTC (Z or +00:00)")
    return result + timedelta(seconds=1) if leap_second else result
