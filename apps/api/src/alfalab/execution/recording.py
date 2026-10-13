"""Compatibility exports for the T03 recording port and test adapter."""

from alfalab.modules.runs.storage.memory import InMemoryRunsRepository
from alfalab.modules.runs.storage.repository import StoredRun

# Runtime composition uses RunsRepository and PostgreSQL. The in-memory alias is
# retained only for existing unit tests that explicitly use the testing profile.
InMemoryRun = StoredRun
RunsWriter = InMemoryRunsRepository

__all__ = ["InMemoryRun", "RunsWriter"]
