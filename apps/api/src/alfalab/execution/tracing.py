"""Measured in-memory spans with safe, fixed detail strings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Mapping
from uuid import uuid4

from alfalab_contracts import SpanRecord


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(slots=True)
class _Span:
    sequence: int
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    started_at: str
    started_ns: int


class InMemoryTraceRecorder:
    """Collect actual timings and safe execution labels for one run."""

    def __init__(self) -> None:
        self._open: dict[str, _Span] = {}
        self._records: list[SpanRecord] = []
        self._events: list[tuple[str, tuple[tuple[str, str | int | float | bool | None], ...]]] = []
        self._next_sequence = 0

    def start(self, name: str, kind: str, parent_span_id: str | None = None) -> str:
        span_id = uuid4().hex
        self._open[span_id] = _Span(
            sequence=self._next_sequence,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
            started_at=utc_timestamp(),
            started_ns=perf_counter_ns(),
        )
        self._next_sequence += 1
        return span_id

    def finish(self, span_id: str, *, status: str, safe_detail: str) -> None:
        span = self._open.pop(span_id)
        elapsed_ns = perf_counter_ns() - span.started_ns
        self._records.append(
            SpanRecord(
                sequence=span.sequence,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                name=span.name,
                kind=span.kind,
                started_at=span.started_at,
                duration_ms=max(0, elapsed_ns // 1_000_000),
                status=status,
                safe_detail=safe_detail,
            )
        )

    def record_safe_event(
        self,
        event_name: str,
        attributes: Mapping[str, str | int | float | bool | None],
        /,
    ) -> None:
        """Accept only T03's fixed event vocabulary and bounded scalar fields."""
        if event_name != "documents.prepare.completed":
            raise ValueError("unsupported safe event")
        permitted = {
            "input_codepoints",
            "output_codepoints",
            "quality",
            "normalize_newlines",
            "trim_outer_whitespace",
        }
        if any(key not in permitted for key in attributes):
            raise ValueError("unsafe event attribute")
        normalized: list[tuple[str, str | int | float | bool | None]] = []
        for key, value in attributes.items():
            if key == "quality" and value not in {"valid", "rejected"}:
                raise ValueError("unsafe event value")
            if key != "quality" and value is not None and type(value) not in {int, bool, float, str}:
                raise ValueError("unsafe event value")
            if isinstance(value, str) and len(value) > 16:
                raise ValueError("unsafe event value")
            normalized.append((key, value))
        self._events.append((event_name, tuple(sorted(normalized))))

    def finish_open(self, *, status: str, safe_detail: str) -> None:
        for span_id in tuple(self._open):
            self.finish(span_id, status=status, safe_detail=safe_detail)

    @property
    def spans(self) -> tuple[SpanRecord, ...]:
        return tuple(sorted(self._records, key=lambda span: span.sequence))

    @property
    def events(self) -> tuple[tuple[str, tuple[tuple[str, str | int | float | bool | None], ...]], ...]:
        return tuple(self._events)
