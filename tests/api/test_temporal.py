"""Runtime UTC parser behavior shared by execution and storage adapters."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alfalab.execution.temporal import parse_utc_timestamp


@pytest.mark.parametrize(
    ("wire_value", "expected"),
    [
        ("2026-10-12T03:00:00Z", datetime(2026, 10, 12, 3, tzinfo=timezone.utc)),
        (
            "2026-10-12T03:00:00+00:00",
            datetime(2026, 10, 12, 3, tzinfo=timezone.utc),
        ),
        (
            "2016-12-31T23:59:60Z",
            datetime(2017, 1, 1, 0, tzinfo=timezone.utc),
        ),
        (
            "2016-12-31T23:59:60.500000Z",
            datetime(2017, 1, 1, 0, 0, 0, 500000, tzinfo=timezone.utc),
        ),
    ],
)
def test_parse_utc_timestamp_preserves_utc_and_leap_second_semantics(
    wire_value: str,
    expected: datetime,
) -> None:
    assert parse_utc_timestamp(wire_value) == expected


@pytest.mark.parametrize(
    "wire_value",
    [
        "2026-10-12T03:00:00+01:00",
        "2026-02-30T03:00:00Z",
        "2026-10-12T03:00:61Z",
        "2026-10-12T03:00:00",
    ],
)
def test_parse_utc_timestamp_rejects_invalid_or_non_utc_values(wire_value: str) -> None:
    with pytest.raises(ValueError):
        parse_utc_timestamp(wire_value)
