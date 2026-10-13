"""PostgreSQL Runs owner repository with row-level scope enforcement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from alfalab_contracts import ArtifactView, QueryRunsInput, QueryRunsOutput, RunRecord
from alfalab_contracts._generated import Availability
from sqlalchemy import Engine, bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from alfalab.common.artifacts import ArtifactStore
from alfalab.common.limits import (
    ARTIFACT_RESPONSE_ENVELOPE_RESERVE_BYTES,
    MAX_ARTIFACT_RESPONSE_BYTES,
)
from alfalab.common.scope import TrustedScope
from alfalab.common.storage_errors import ArtifactIntegrityError
from alfalab.execution.errors import SafeExecutionError, invalid_input
from alfalab.modules.runs.storage.cursor import (
    decode_cursor,
    encode_cursor,
    query_fingerprint,
)
from alfalab.modules.runs.storage.repository import StoredRun


class ContentPolicyViolation(RuntimeError):
    """Raised if a full artifact crosses the owner boundary without trusted policy."""


def _reserve_artifact_response_bytes(current_size: int, artifact_size: int) -> int:
    """Reserve a conservative outer-JSON size before materializing an artifact."""

    # Run artifacts are canonical JSON. When content_json is serialized as a JSON
    # string, quotes and backslashes can at most double its UTF-8 byte length.
    reserved = current_size + (2 * artifact_size) + 2
    if (
        reserved + ARTIFACT_RESPONSE_ENVELOPE_RESERVE_BYTES
        > MAX_ARTIFACT_RESPONSE_BYTES
    ):
        raise SafeExecutionError(
            status_code=429,
            code="LIMIT_EXCEEDED",
            category="validation",
            safe_message="The artifact response exceeds 2 MiB; retry with include_artifacts=false.",
        )
    return reserved


def _artifact_views(record: RunRecord) -> list[ArtifactView]:
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


def _without_content(record: RunRecord) -> dict[str, object]:
    value = record.model_dump(mode="json")
    manifest = value.get("manifest")
    if isinstance(manifest, dict) and isinstance(manifest.get("configuration"), dict):
        manifest["configuration"]["content_json"] = None
        manifest["configuration"]["availability"] = "metadata_only"
    for key in ("input", "output"):
        view = value.get(key)
        if isinstance(view, dict):
            view["content_json"] = None
            view["availability"] = "metadata_only"
    dependencies = value.get("dependencies")
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            for key in ("request", "response"):
                view = dependency.get(key)
                if isinstance(view, dict):
                    view["content_json"] = None
                    view["availability"] = "metadata_only"
    return value


def _set_scope(connection: object, tenant_id: str, sandbox_id: str) -> None:
    connection.execute(  # type: ignore[attr-defined]
        text(
            "SELECT set_config('alfalab.tenant_id', :tenant_id, true), set_config('alfalab.sandbox_id', :sandbox_id, true)"
        ),
        {"tenant_id": tenant_id, "sandbox_id": sandbox_id},
    )


class PostgresRunsRepository:
    """Persist typed run aggregates using only the ``runs_owner`` role."""

    def __init__(
        self,
        engine: Engine,
        *,
        environment: str = "testing",
        artifact_root: Path | None = None,
    ) -> None:
        self._engine = engine
        self._environment = environment
        self._artifact_store = (
            ArtifactStore(artifact_root) if artifact_root is not None else None
        )

    def write(self, entry: StoredRun, /) -> None:
        decision = entry.record.manifest.data_policy
        full_recording_allowed = (
            decision.classification in {"synthetic", "public"}
            and decision.processing_allowed
            and decision.recording == "full"
        )
        views = _artifact_views(entry.record)
        if (
            any(view.content_json is not None for view in views)
            and not full_recording_allowed
        ):
            raise ContentPolicyViolation(
                "full artifact content rejected by Runs policy gate"
            )

        scope = TrustedScope(entry.tenant_id, entry.sandbox_id, self._environment)
        artifact_keys: dict[str, str | None] = {}
        if full_recording_allowed:
            for view in views:
                if view.content_json is None:
                    artifact_keys[view.ref.artifact_id] = None
                    continue
                if self._artifact_store is None:
                    raise OSError("Runs artifact storage is unavailable")
                raw = view.content_json.encode("utf-8")
                if len(raw) > 2 * 1024 * 1024:
                    raise ContentPolicyViolation(
                        "artifact exceeds the approved storage limit"
                    )
                actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
                if actual_hash != view.ref.hash or len(raw) != view.ref.size_bytes:
                    raise ContentPolicyViolation(
                        "artifact hash or size did not match its immutable reference"
                    )
                try:
                    stored = self._artifact_store.put_json(
                        scope,
                        json.loads(view.content_json),
                        schema_id=view.ref.schema_id,
                        schema_version=view.ref.schema_version,
                        classification=view.ref.classification.value,
                    )
                except (ArtifactIntegrityError, OSError, ValueError) as exc:
                    raise OSError("Runs artifact could not be safely stored") from exc
                if (
                    stored.artifact_ref.hash != view.ref.hash
                    or stored.artifact_ref.size_bytes != view.ref.size_bytes
                ):
                    raise ContentPolicyViolation(
                        "canonical artifact bytes did not match their immutable reference"
                    )
                artifact_keys[view.ref.artifact_id] = stored.relative_key
        else:
            artifact_keys = {view.ref.artifact_id: None for view in views}

        record_json = _without_content(entry.record)
        safe_dependencies = record_json.get("dependencies")
        # The owner tables are authoritative for ordered trace and gateway rows.
        record_json["spans"] = []
        record_json["dependencies"] = []
        try:
            with self._engine.begin() as connection:
                _set_scope(connection, entry.tenant_id, entry.sandbox_id)
                connection.execute(
                    text(
                        """INSERT INTO runs.runs (
                            tenant_id, sandbox_id, run_id, operation_id, scenario_id,
                            status, input_hash, analytical_time, random_seed, record_json, updated_at
                        ) VALUES (
                            :tenant_id, :sandbox_id, :run_id, :operation_id, :scenario_id,
                            :status, :input_hash, :analytical_time, :random_seed,
                            CAST(:record_json AS jsonb), clock_timestamp()
                        )
                        ON CONFLICT (tenant_id, sandbox_id, run_id) DO UPDATE SET
                            operation_id = EXCLUDED.operation_id,
                            scenario_id = EXCLUDED.scenario_id,
                            status = EXCLUDED.status,
                            input_hash = EXCLUDED.input_hash,
                            analytical_time = EXCLUDED.analytical_time,
                            random_seed = EXCLUDED.random_seed,
                            record_json = EXCLUDED.record_json,
                            updated_at = clock_timestamp()"""
                    ),
                    {
                        "tenant_id": entry.tenant_id,
                        "sandbox_id": entry.sandbox_id,
                        "run_id": entry.run_id,
                        "operation_id": entry.record.operation_id,
                        "scenario_id": entry.record.scenario.id
                        if entry.record.scenario
                        else None,
                        "status": entry.record.status.value,
                        "input_hash": entry.input_hash,
                        "analytical_time": entry.record.analytical_time,
                        "random_seed": entry.record.random_seed,
                        "record_json": json.dumps(
                            record_json, ensure_ascii=False, separators=(",", ":")
                        ),
                    },
                )
                for span in entry.record.spans:
                    connection.execute(
                        text(
                            """INSERT INTO runs.spans
                            (tenant_id, sandbox_id, run_id, sequence, span_json)
                            VALUES (:tenant_id, :sandbox_id, :run_id, :sequence, CAST(:value AS jsonb))
                            ON CONFLICT (tenant_id, sandbox_id, run_id, sequence)
                            DO UPDATE SET span_json = EXCLUDED.span_json"""
                        ),
                        {
                            "tenant_id": entry.tenant_id,
                            "sandbox_id": entry.sandbox_id,
                            "run_id": entry.run_id,
                            "sequence": span.sequence,
                            "value": span.model_dump_json(),
                        },
                    )
                for dependency in (
                    safe_dependencies if isinstance(safe_dependencies, list) else []
                ):
                    if not isinstance(dependency, dict):
                        continue
                    connection.execute(
                        text(
                            """INSERT INTO runs.dependencies
                            (tenant_id, sandbox_id, run_id, sequence, dependency_json)
                            VALUES (:tenant_id, :sandbox_id, :run_id, :sequence, CAST(:value AS jsonb))
                            ON CONFLICT (tenant_id, sandbox_id, run_id, sequence)
                            DO UPDATE SET dependency_json = EXCLUDED.dependency_json"""
                        ),
                        {
                            "tenant_id": entry.tenant_id,
                            "sandbox_id": entry.sandbox_id,
                            "run_id": entry.run_id,
                            "sequence": dependency["sequence"],
                            "value": json.dumps(
                                dependency, ensure_ascii=False, separators=(",", ":")
                            ),
                        },
                    )
                for view in views:
                    connection.execute(
                        text(
                            """INSERT INTO runs.artifacts (
                                tenant_id, sandbox_id, run_id, artifact_id, artifact_hash,
                                schema_id, schema_version, size_bytes, classification, media_type, storage_key
                            ) VALUES (
                                :tenant_id, :sandbox_id, :run_id, :artifact_id, :artifact_hash,
                                :schema_id, :schema_version, :size_bytes, :classification, :media_type, :storage_key
                            ) ON CONFLICT (tenant_id, sandbox_id, run_id, artifact_id) DO NOTHING"""
                        ),
                        {
                            "tenant_id": entry.tenant_id,
                            "sandbox_id": entry.sandbox_id,
                            "run_id": entry.run_id,
                            "artifact_id": view.ref.artifact_id,
                            "artifact_hash": view.ref.hash,
                            "schema_id": view.ref.schema_id,
                            "schema_version": view.ref.schema_version,
                            "size_bytes": view.ref.size_bytes,
                            "classification": view.ref.classification.value,
                            "media_type": view.ref.media_type.value,
                            "storage_key": artifact_keys.get(view.ref.artifact_id),
                        },
                    )
        except ContentPolicyViolation:
            raise
        except SQLAlchemyError as exc:
            raise OSError("Runs history is unavailable") from exc

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

        try:
            with self._engine.begin() as connection:
                _set_scope(connection, tenant_id, sandbox_id)
                snapshot_at = (
                    cursor.snapshot_at
                    if cursor is not None
                    else connection.execute(
                        text("SELECT clock_timestamp()")
                    ).scalar_one()
                )
                clauses = [
                    "tenant_id = :tenant_id",
                    "sandbox_id = :sandbox_id",
                    "run_id <> :exclude_run_id",
                    "created_at <= :snapshot_at",
                ]
                values: dict[str, object] = {
                    "tenant_id": tenant_id,
                    "sandbox_id": sandbox_id,
                    "exclude_run_id": exclude_run_id,
                    "snapshot_at": snapshot_at,
                    "limit": payload.limit + 1,
                }
                if payload.run_ids:
                    clauses.append("run_id IN :run_ids")
                    values["run_ids"] = list(payload.run_ids)
                if payload.operation_id is not None:
                    clauses.append("operation_id = :operation_id")
                    values["operation_id"] = payload.operation_id
                if payload.scenario_id is not None:
                    clauses.append("scenario_id = :scenario_id")
                    values["scenario_id"] = payload.scenario_id
                if cursor is not None:
                    clauses.append(
                        "(created_at < :after_created_at OR (created_at = :after_created_at AND run_id < :after_run_id))"
                    )
                    values["after_created_at"] = cursor.after_created_at
                    values["after_run_id"] = cursor.after_run_id
                query = text(
                    "SELECT run_id, record_json, input_hash, created_at, updated_at, status "
                    "FROM runs.runs WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at DESC, run_id DESC LIMIT :limit"
                )
                if payload.run_ids:
                    query = query.bindparams(bindparam("run_ids", expanding=True))
                rows = list(connection.execute(query, values).mappings())
                has_more = len(rows) > payload.limit
                rows = rows[: payload.limit]
                run_ids = [row["run_id"] for row in rows]
                spans_by_run: dict[str, list[object]] = {}
                dependencies_by_run: dict[str, list[object]] = {}
                if run_ids:
                    span_rows = connection.execute(
                        text(
                            "SELECT run_id, span_json FROM runs.spans "
                            "WHERE tenant_id=:tenant_id AND sandbox_id=:sandbox_id AND run_id IN :run_ids "
                            "ORDER BY run_id, sequence"
                        ).bindparams(bindparam("run_ids", expanding=True)),
                        {
                            "tenant_id": tenant_id,
                            "sandbox_id": sandbox_id,
                            "run_ids": run_ids,
                        },
                    ).mappings()
                    for span in span_rows:
                        spans_by_run.setdefault(span["run_id"], []).append(
                            span["span_json"]
                        )
                    dependency_rows = connection.execute(
                        text(
                            "SELECT run_id, dependency_json FROM runs.dependencies "
                            "WHERE tenant_id=:tenant_id AND sandbox_id=:sandbox_id AND run_id IN :run_ids "
                            "ORDER BY run_id, sequence"
                        ).bindparams(bindparam("run_ids", expanding=True)),
                        {
                            "tenant_id": tenant_id,
                            "sandbox_id": sandbox_id,
                            "run_ids": run_ids,
                        },
                    ).mappings()
                    for dependency in dependency_rows:
                        dependencies_by_run.setdefault(dependency["run_id"], []).append(
                            dependency["dependency_json"]
                        )
                storage_keys: dict[tuple[str, str], str | None] = {}
                if run_ids and include_artifacts:
                    artifact_stmt = text(
                        "SELECT run_id, artifact_id, storage_key FROM runs.artifacts "
                        "WHERE tenant_id = :tenant_id AND sandbox_id = :sandbox_id AND run_id IN :run_ids"
                    ).bindparams(bindparam("run_ids", expanding=True))
                    for artifact in connection.execute(
                        artifact_stmt,
                        {
                            "tenant_id": tenant_id,
                            "sandbox_id": sandbox_id,
                            "run_ids": run_ids,
                        },
                    ).mappings():
                        storage_keys[(artifact["run_id"], artifact["artifact_id"])] = (
                            artifact["storage_key"]
                        )
        except SafeExecutionError:
            raise
        except SQLAlchemyError as exc:
            raise OSError("Runs history is unavailable") from exc

        records: list[RunRecord] = []
        eligible_views: list[tuple[ArtifactView, str]] = []
        for row in rows:
            record_payload = dict(row["record_json"])
            record_payload["spans"] = spans_by_run.get(row["run_id"], [])
            record_payload["dependencies"] = dependencies_by_run.get(row["run_id"], [])
            record = RunRecord.model_validate(record_payload)
            for view in _artifact_views(record):
                view.content_json = None
                view.availability = Availability.metadata_only
                if not include_artifacts:
                    continue
                decision = record.manifest.data_policy
                export_allowed = (
                    decision.export_allowed
                    and decision.recording == "full"
                    and decision.classification in {"synthetic", "public"}
                    and view.ref.classification in {"synthetic", "public"}
                )
                storage_key = storage_keys.get((row["run_id"], view.ref.artifact_id))
                if export_allowed and storage_key is not None:
                    if self._artifact_store is None:
                        view.availability = Availability.missing
                        continue
                    expected_key = PurePosixPath(
                        self._environment,
                        tenant_id,
                        sandbox_id,
                        f"{view.ref.hash.removeprefix('sha256:')}.json",
                    ).as_posix()
                    if storage_key != expected_key:
                        view.availability = Availability.missing
                        continue
                    eligible_views.append((view, view.ref.hash))
                elif decision.recording == "metadata_only":
                    view.availability = Availability.metadata_only
                elif not decision.export_allowed:
                    view.availability = Availability.policy_denied
            records.append(record)

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(
                snapshot_at=snapshot_at,
                after_created_at=last["created_at"],
                after_run_id=last["run_id"],
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
                query_fingerprint=fingerprint,
            )

        if eligible_views:
            base_response = QueryRunsOutput(runs=records, next_cursor=next_cursor)
            reserved_bytes = len(base_response.model_dump_json().encode("utf-8"))
            scope = TrustedScope(tenant_id, sandbox_id, self._environment)
            for view, artifact_hash in eligible_views:
                reserved_bytes = _reserve_artifact_response_bytes(
                    reserved_bytes, view.ref.size_bytes
                )
                try:
                    raw = self._artifact_store.read_json(
                        scope,
                        artifact_hash,
                        expected_size_bytes=view.ref.size_bytes,
                    )  # type: ignore[union-attr]
                    if (
                        len(raw) == view.ref.size_bytes
                        and "sha256:" + hashlib.sha256(raw).hexdigest() == artifact_hash
                    ):
                        view.content_json = raw.decode("utf-8")
                        view.availability = Availability.available
                    else:
                        view.availability = Availability.missing
                except (ArtifactIntegrityError, OSError, ValueError):
                    view.availability = Availability.missing
        return records, next_cursor

    def get(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        sandbox_id: str | None = None,
    ) -> StoredRun | None:
        if tenant_id is None or sandbox_id is None:
            return None
        try:
            with self._engine.begin() as connection:
                _set_scope(connection, tenant_id, sandbox_id)
                row = (
                    connection.execute(
                        text(
                            "SELECT record_json, input_hash, created_at, updated_at, status "
                            "FROM runs.runs WHERE tenant_id = :tenant_id AND sandbox_id = :sandbox_id AND run_id = :run_id"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "sandbox_id": sandbox_id,
                            "run_id": run_id,
                        },
                    )
                    .mappings()
                    .first()
                )
            if row is None:
                return None
            return StoredRun(
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
                record=RunRecord.model_validate(row["record_json"]),
                input_hash=row["input_hash"],
                started_at=row["created_at"],
                updated_at=row["updated_at"],
                writer_status={
                    "running": "in_progress",
                    "success": "success",
                    "failed": "error",
                    "unknown": "unknown",
                }.get(row["status"], "unknown"),
            )
        except SQLAlchemyError as exc:
            raise OSError("Runs history is unavailable") from exc

    def close(self) -> None:
        self._engine.dispose()
