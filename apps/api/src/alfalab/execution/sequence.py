"""Per-run ordering for recorded dependencies, clock reads, and retries."""

from __future__ import annotations


class DependencySequence:
    def __init__(self) -> None:
        self._next_value = 0

    def next(self) -> int:
        value = self._next_value
        self._next_value += 1
        return value
