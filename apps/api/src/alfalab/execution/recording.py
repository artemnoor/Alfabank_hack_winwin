"""Bounded process-local run metadata writer for the T03 execution slice."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from alfalab_contracts import ExecutionMeta, SpanRecord


@dataclass(frozen=True, slots=True)
class InMemoryRun:
    run_id: str
    input_hash: str
    analytical_time: str
    random_seed: int
    meta: ExecutionMeta
    spans: tuple[SpanRecord, ...]
    status: Literal["in_progress", "success", "error"]


class RunsWriter:
    """Keep only safe metadata and spans; nothing is persisted or replayable."""

    def __init__(self, capacity: int = 256) -> None:
        self._capacity = capacity
        self._records: OrderedDict[str, InMemoryRun] = OrderedDict()
        self._lock = Lock()

    def write(self, record: InMemoryRun) -> None:
        with self._lock:
            self._records[record.run_id] = record
            self._records.move_to_end(record.run_id)
            while len(self._records) > self._capacity:
                self._records.popitem(last=False)

    def get(self, run_id: str) -> InMemoryRun | None:
        with self._lock:
            return self._records.get(run_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)
