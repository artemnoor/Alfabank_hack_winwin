"""Small in-memory Runs adapter for isolated unit tests and local fakes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from threading import RLock

from alfalab_contracts import ArtifactView, QueryRunsInput, RunRecord
from alfalab_contracts._generated import Availability

from alfalab.execution.errors import invalid_input
from alfalab.modules.runs.storage.cursor import (
    decode_cursor,
    encode_cursor,
    query_fingerprint,
)
from alfalab.modules.runs.storage.repository import StoredRun


def _views(record: RunRecord) -> list[ArtifactView]:
    views = [record.manifest.configuration]
    if record.input is not None:
        views.append(record.input)
    if record.output is not None:
        views.append(record.output)
    for dependency in record.dependencies:
        views.append(dependency.request)
        if dependency.response is not None:
            views.append(dependency.response)
    return views


class InMemoryRunsRepository:
    """Test-only adapter. Production profiles use PostgreSQL Runs storage."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str], StoredRun] = {}
        self._query_snapshots: dict[
            tuple[str, str, str], tuple[datetime, str, list[StoredRun]]
        ] = {}
        self._lock = RLock()

    def write(self, record: StoredRun, /) -> None:
        decision = record.record.manifest.data_policy
        full_recording_allowed = (
            decision.classification in {"synthetic", "public"}
            and decision.processing_allowed
            and decision.recording == "full"
        )
        if not full_recording_allowed and any(
            view.content_json is not None for view in _views(record.record)
        ):
            raise ValueError("full artifact content rejected by Runs policy gate")
        key = (record.tenant_id, record.sandbox_id, record.run_id)
        with self._lock:
            self._records[key] = record

    def get(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        sandbox_id: str | None = None,
    ) -> StoredRun | None:
        with self._lock:
            if tenant_id is not None and sandbox_id is not None:
                return self._records.get((tenant_id, sandbox_id, run_id))
            return next(
                (
                    item
                    for (_, _, found), item in self._records.items()
                    if found == run_id
                ),
                None,
            )

    def query(
        self,
        payload: QueryRunsInput,
        *,
        tenant_id: str,
        sandbox_id: str,
        exclude_run_id: str,
        include_artifacts: bool,
    ) -> tuple[list[RunRecord], str | None]:
        fingerprint = query_fingerprint(payload)
        cursor = None
        if payload.cursor is not None:
            cursor = decode_cursor(
                payload.cursor,
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
                query_fingerprint=fingerprint,
            )
            if cursor is None:
                raise invalid_input("payload.cursor")

        now = datetime.now(UTC)
        scope_key = (tenant_id, sandbox_id)
        with self._lock:
            self._query_snapshots = {
                key: snapshot
                for key, snapshot in self._query_snapshots.items()
                if snapshot[0] > now
            }
            if cursor is not None:
                snapshot = self._query_snapshots.get((*scope_key, cursor.snapshot_id))
                if snapshot is None or snapshot[1] != fingerprint:
                    raise invalid_input("payload.cursor")
                entries = snapshot[2]
                start = cursor.after_position
                selected = entries[start : start + payload.limit + 1]
                has_more = len(selected) > payload.limit
                page_entries = selected[: payload.limit]
                snapshot_id = cursor.snapshot_id
                after_position = start
            else:
                entries = [
                    item
                    for item in self._records.values()
                    if item.tenant_id == tenant_id
                    and item.sandbox_id == sandbox_id
                    and item.run_id != exclude_run_id
                    and (not payload.run_ids or item.run_id in payload.run_ids)
                    and (
                        payload.operation_id is None
                        or item.record.operation_id == payload.operation_id
                    )
                    and (
                        payload.scenario_id is None
                        or (
                            item.record.scenario is not None
                            and item.record.scenario.id == payload.scenario_id
                        )
                    )
                ]
                entries.sort(
                    key=lambda item: (item.started_at, item.run_id), reverse=True
                )
                has_more = len(entries) > payload.limit
                snapshot_id = None
                if has_more:
                    snapshot_id = uuid.uuid4().hex
                    frozen_entries = [
                        StoredRun(
                            tenant_id=item.tenant_id,
                            sandbox_id=item.sandbox_id,
                            record=item.record.model_copy(deep=True),
                            input_hash=item.input_hash,
                            started_at=item.started_at,
                            updated_at=item.updated_at,
                            writer_status=item.writer_status,
                        )
                        for item in entries
                    ]
                    self._query_snapshots[(*scope_key, snapshot_id)] = (
                        now + timedelta(minutes=15),
                        fingerprint,
                        frozen_entries,
                    )
                    entries = frozen_entries
                page_entries = entries[: payload.limit]
                after_position = 0

        next_cursor = None
        if has_more and page_entries and snapshot_id is not None:
            next_cursor = encode_cursor(
                snapshot_id=snapshot_id,
                after_position=after_position + len(page_entries),
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
                query_fingerprint=fingerprint,
            )
        result = []
        for entry in page_entries:
            record = entry.record.model_copy(deep=True)
            for view in _views(record):
                if not include_artifacts:
                    view.content_json = None
                    view.availability = Availability.metadata_only
                    continue
                decision = record.manifest.data_policy
                export_allowed = (
                    decision.export_allowed
                    and decision.recording == "full"
                    and decision.classification in {"synthetic", "public"}
                    and view.ref.classification in {"synthetic", "public"}
                )
                if not export_allowed:
                    view.content_json = None
                    view.availability = (
                        Availability.metadata_only
                        if decision.recording == "metadata_only"
                        else Availability.policy_denied
                    )
                elif view.content_json is not None:
                    view.availability = Availability.available
                else:
                    view.availability = Availability.metadata_only
            result.append(record)
        return result, next_cursor

    def close(self) -> None:
        return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)
