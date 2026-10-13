"""Documents repository, command, and historical read behavior."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from alfalab_contracts import (
    CommandReceipt,
    DocumentResult,
    DocumentSelection,
    DocumentVersion,
    ObjectRef,
    ReadDocumentsInput,
    ReadDocumentsOutput,
    ReceiptQuery,
    ReceiptResult,
    RegisterDocumentInput,
    RegisterDocumentOutput,
)
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from alfalab.common.limits import (
    MAX_ARTIFACT_RESPONSE_BYTES,
    MAX_LEGACY_DOCUMENT_ARTIFACT_READ_BYTES,
)
from alfalab.execution.temporal import parse_utc_timestamp

from .artifacts import ArtifactStore
from .canonical import canonical_hash
from .context import OperationContext, TrustedScope, owner_command_context
from .errors import DocumentsStorageError, ExpectedRevisionConflict
from .policy import (
    DEFAULT_SCOPE_POLICY,
    DOCUMENTS_READ_PERMISSION,
    DOCUMENTS_REGISTER_PERMISSION,
    ScopePolicy,
    require_permission,
)
from .schema import audit_entries, command_claims, command_receipts, documents, versions
from .transactions import OwnerCommandEffect, OwnerCommandRunner, OwnerTables

REGISTER_OPERATION_ID = "Documents.register"
REGISTER_RESPONSE_SCHEMA_ID = "RegisterDocumentOutput"
CONTRACT_VERSION = "1.0.0"


class DocumentsStorage:
    """Owns Documents state and exposes typed register/read operations."""

    def __init__(
        self,
        engine: Engine,
        artifacts: ArtifactStore,
        scope_policy: ScopePolicy = DEFAULT_SCOPE_POLICY,
    ) -> None:
        self._engine = engine
        self._artifacts = artifacts
        self._scope_policy = scope_policy
        self._commands = OwnerCommandRunner(
            engine,
            OwnerTables(
                claims=command_claims, receipts=command_receipts, audits=audit_entries
            ),
        )

    def register(
        self,
        payload: RegisterDocumentInput,
        context: OperationContext,
        /,
    ) -> RegisterDocumentOutput:
        """Store a new immutable version or return the current semantic duplicate."""

        require_permission(context, DOCUMENTS_REGISTER_PERMISSION)
        command_context = owner_command_context(
            context, scope_policy=self._scope_policy
        )
        if command_context.operation_id != REGISTER_OPERATION_ID:
            raise ValueError(
                "DocumentsStorage.register requires Documents.register context"
            )
        if command_context.contract_major != 1:
            raise ValueError("unsupported Documents.register contract major")
        if payload.prepared is not None:
            if payload.prepared.raw_hash != payload.raw.content_hash:
                raise ValueError(
                    "prepared material raw_hash does not match registered raw content"
                )
            raw_length = len(payload.raw.text)
            if any(span.raw_end > raw_length for span in payload.prepared.span_map):
                raise ValueError("prepared span map exceeds registered raw text")

        payload_json = payload.model_dump(mode="json")

        def mutate(connection: Connection) -> OwnerCommandEffect[DocumentVersion]:
            scope_values = _scope_values(command_context.scope)
            document_key = {**scope_values, "document_id": payload.document_id}
            connection.execute(
                pg_insert(documents)
                .values(**document_key, current_revision=0)
                .on_conflict_do_nothing(
                    index_elements=[
                        documents.c.tenant_id,
                        documents.c.sandbox_id,
                        documents.c.document_id,
                    ]
                )
            )
            aggregate = (
                connection.execute(
                    select(documents.c.current_revision)
                    .where(*_equals(documents, document_key))
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            current_revision = aggregate["current_revision"]
            if current_revision != payload.expected_revision:
                raise ExpectedRevisionConflict(
                    payload.expected_revision, current_revision
                )

            current_record = None
            if current_revision:
                current_record = _version_row(
                    connection,
                    command_context.scope,
                    payload.document_id,
                    current_revision,
                )
                if current_record is None:
                    raise DocumentsStorageError(
                        "document pointer refers to a missing immutable version"
                    )
            semantic_hash = _semantic_hash(payload)
            if (
                current_record is not None
                and current_record["semantic_hash"] == semantic_hash
            ):
                version = self._materialize_version(
                    connection, command_context.scope, current_record
                )
                before = (version.ref,)
                return OwnerCommandEffect(
                    value=version,
                    applied=False,
                    changed_refs=(),
                    before_refs=before,
                    after_refs=before,
                )

            parent_ref = (
                _ref_for_record(current_record, payload.document_id)
                if current_record
                else None
            )
            revision = current_revision + 1
            kind = "prepared" if payload.prepared is not None else "raw"
            version_body = {
                "kind": kind,
                "raw": payload.raw.model_dump(mode="json"),
                "prepared": payload.prepared.model_dump(mode="json")
                if payload.prepared
                else None,
                "parent_ref": parent_ref.model_dump(mode="json")
                if parent_ref
                else None,
            }
            version_hash = canonical_hash(version_body)
            version_ref = ObjectRef(
                owner="Documents",
                object_id=payload.document_id,
                revision=revision,
                hash=version_hash,
            )
            raw_artifact = self._artifacts.put_json(
                command_context.scope,
                payload.raw,
                schema_id="RawMaterial",
                schema_version=CONTRACT_VERSION,
            )
            prepared_artifact_hash = None
            prepared_artifact_size_bytes = None
            if payload.prepared is not None:
                prepared_artifact = self._artifacts.put_json(
                    command_context.scope,
                    payload.prepared,
                    schema_id="PreparedMaterial",
                    schema_version=CONTRACT_VERSION,
                )
                prepared_artifact_hash = prepared_artifact.artifact_ref.hash
                prepared_artifact_size_bytes = prepared_artifact.artifact_ref.size_bytes
            recorded_at = connection.execute(select(_database_clock())).scalar_one()
            published_at = _timestamp_value(payload.raw.published_at)
            connection.execute(
                insert(versions).values(
                    **document_key,
                    revision=revision,
                    kind=kind,
                    raw_artifact_hash=raw_artifact.artifact_ref.hash,
                    raw_artifact_size_bytes=raw_artifact.artifact_ref.size_bytes,
                    prepared_artifact_hash=prepared_artifact_hash,
                    prepared_artifact_size_bytes=prepared_artifact_size_bytes,
                    raw_content_hash=payload.raw.content_hash,
                    semantic_hash=semantic_hash,
                    version_hash=version_hash,
                    parent_revision=current_revision or None,
                    published_at=published_at,
                    recorded_at=recorded_at,
                )
            )
            connection.execute(
                update(documents)
                .where(*_equals(documents, document_key))
                .values(current_revision=revision)
            )
            version = DocumentVersion(
                ref=version_ref,
                kind=kind,
                raw=payload.raw,
                prepared=payload.prepared,
                parent_ref=parent_ref,
            )
            return OwnerCommandEffect(
                value=version,
                applied=True,
                changed_refs=(version_ref,),
                before_refs=(parent_ref,) if parent_ref else (),
                after_refs=(version_ref,),
            )

        result = self._commands.execute(
            context=command_context,
            operation_id=REGISTER_OPERATION_ID,
            contract_major=command_context.contract_major,
            idempotency_key=command_context.idempotency_key,
            command_payload=payload_json,
            response_model=RegisterDocumentOutput,
            response_schema_id=REGISTER_RESPONSE_SCHEMA_ID,
            response_schema_version=CONTRACT_VERSION,
            mutate=mutate,
            build_response=lambda version, receipt: RegisterDocumentOutput(
                version=version, receipt=receipt
            ),
        )
        return result.response

    def read(
        self, payload: ReadDocumentsInput, context: OperationContext, /
    ) -> ReadDocumentsOutput:
        """Return owner-scoped immutable versions or a register receipt."""

        scope = self._scope_policy.resolve(context)
        require_permission(context, DOCUMENTS_READ_PERMISSION)
        if isinstance(payload.query, ReceiptQuery):
            if payload.query.operation_id != REGISTER_OPERATION_ID:
                raise ValueError(
                    "Documents.read receipt query supports Documents.register only"
                )
            return self._read_receipt(scope, payload.query)
        if not isinstance(payload.query, DocumentSelection):
            raise TypeError("unsupported Documents.read query kind")
        return self._read_documents(scope, payload.query)

    def _read_receipt(self, scope: TrustedScope, query: ReceiptQuery) -> ReceiptResult:
        key = {
            "tenant_id": scope.tenant_id,
            "sandbox_id": scope.sandbox_id,
            "operation_id": query.operation_id,
            "contract_major": 1,
            "idempotency_key": query.idempotency_key,
        }
        with self._engine.connect() as connection:
            record = (
                connection.execute(
                    select(command_receipts).where(*_equals(command_receipts, key))
                )
                .mappings()
                .one_or_none()
            )
        if record is None:
            return ReceiptResult(kind="receipt", receipt=None)
        receipt = CommandReceipt.model_validate(record["receipt_json"])
        response = RegisterDocumentOutput.model_validate(
            record["response_payload_json"]
        )
        if record["response_schema_id"] != REGISTER_RESPONSE_SCHEMA_ID:
            raise DocumentsStorageError("stored receipt response schema is unsupported")
        if record["response_schema_version"] != CONTRACT_VERSION:
            raise DocumentsStorageError(
                "stored receipt response version is unsupported"
            )
        if canonical_hash(response.model_dump(mode="json")) != record["response_hash"]:
            raise DocumentsStorageError(
                "stored receipt response failed integrity verification"
            )
        if response.receipt != receipt:
            raise DocumentsStorageError(
                "stored receipt metadata does not match its typed response"
            )
        return ReceiptResult(kind="receipt", receipt=receipt)

    def _read_documents(
        self, scope: TrustedScope, query: DocumentSelection
    ) -> DocumentResult:
        if query.revision is not None and query.as_of is not None:
            raise ValueError("revision and as_of cannot be selected together")
        results: list[DocumentVersion] = []
        missing: list[str] = []
        with self._engine.connect() as connection:
            for document_id in query.document_ids:
                record = self._select_version(connection, scope, document_id, query)
                if record is None:
                    missing.append(document_id)
                else:
                    results.append(self._materialize_version(connection, scope, record))
        return DocumentResult(kind="documents", versions=results, missing_ids=missing)

    def _select_version(
        self,
        connection: Connection,
        scope: TrustedScope,
        document_id: str,
        query: DocumentSelection,
    ) -> Mapping[str, Any] | None:
        predicates = [
            versions.c.tenant_id == scope.tenant_id,
            versions.c.sandbox_id == scope.sandbox_id,
            versions.c.document_id == document_id,
        ]
        if query.revision is not None:
            predicates.append(versions.c.revision == query.revision)
        elif query.as_of is not None:
            predicates.append(
                versions.c.recorded_at <= parse_utc_timestamp(query.as_of.known_as_of)
            )
            valid_as_of = parse_utc_timestamp(query.as_of.valid_as_of)
            predicates.append(
                (versions.c.published_at.is_(None))
                | (versions.c.published_at <= valid_as_of)
            )
        else:
            aggregate = connection.execute(
                select(documents.c.current_revision).where(
                    documents.c.tenant_id == scope.tenant_id,
                    documents.c.sandbox_id == scope.sandbox_id,
                    documents.c.document_id == document_id,
                )
            ).scalar_one_or_none()
            if aggregate is None or aggregate == 0:
                return None
            predicates.append(versions.c.revision == aggregate)
        return (
            connection.execute(
                select(versions)
                .where(*predicates)
                .order_by(versions.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )

    def _materialize_version(
        self,
        connection: Connection,
        scope: TrustedScope,
        record: Mapping[str, Any],
    ) -> DocumentVersion:
        raw_json = self._artifacts.read_json(
            scope,
            record["raw_artifact_hash"],
            expected_size_bytes=_expected_artifact_read_size(
                record["raw_artifact_size_bytes"]
            ),
        )
        from alfalab_contracts import RawMaterial

        raw = RawMaterial.model_validate_json(raw_json, strict=True)
        prepared = None
        if record["prepared_artifact_hash"] is not None:
            from alfalab_contracts import PreparedMaterial

            prepared_json = self._artifacts.read_json(
                scope,
                record["prepared_artifact_hash"],
                expected_size_bytes=_expected_artifact_read_size(
                    record["prepared_artifact_size_bytes"]
                ),
            )
            prepared = PreparedMaterial.model_validate_json(prepared_json, strict=True)
        parent_ref = None
        if record["parent_revision"] is not None:
            parent = _version_row(
                connection, scope, record["document_id"], record["parent_revision"]
            )
            if parent is None:
                raise DocumentsStorageError("document parent version is unavailable")
            parent_ref = _ref_for_record(parent, record["document_id"])
        body = {
            "kind": record["kind"],
            "raw": raw.model_dump(mode="json"),
            "prepared": prepared.model_dump(mode="json") if prepared else None,
            "parent_ref": parent_ref.model_dump(mode="json") if parent_ref else None,
        }
        if canonical_hash(body) != record["version_hash"]:
            raise DocumentsStorageError(
                "stored document version failed integrity verification"
            )
        return DocumentVersion(
            ref=ObjectRef(
                owner="Documents",
                object_id=record["document_id"],
                revision=record["revision"],
                hash=record["version_hash"],
            ),
            kind=record["kind"],
            raw=raw,
            prepared=prepared,
            parent_ref=parent_ref,
        )


def _scope_values(scope: TrustedScope) -> dict[str, str]:
    return {"tenant_id": scope.tenant_id, "sandbox_id": scope.sandbox_id}


def _equals(table: Any, values: Mapping[str, Any]) -> list[Any]:
    return [getattr(table.c, name) == value for name, value in values.items()]


def _version_row(
    connection: Connection,
    scope: TrustedScope,
    document_id: str,
    revision: int,
) -> Mapping[str, Any] | None:
    return (
        connection.execute(
            select(versions).where(
                versions.c.tenant_id == scope.tenant_id,
                versions.c.sandbox_id == scope.sandbox_id,
                versions.c.document_id == document_id,
                versions.c.revision == revision,
            )
        )
        .mappings()
        .one_or_none()
    )


def _ref_for_record(record: Mapping[str, Any], document_id: str) -> ObjectRef:
    return ObjectRef(
        owner="Documents",
        object_id=document_id,
        revision=record["revision"],
        hash=record["version_hash"],
    )


def _semantic_hash(payload: RegisterDocumentInput) -> str:
    semantic = {
        "raw_content_hash": payload.raw.content_hash,
        "prepared_content_hash": payload.prepared.prepared_hash
        if payload.prepared
        else None,
        "span_map": [span.model_dump(mode="json") for span in payload.prepared.span_map]
        if payload.prepared
        else None,
    }
    return canonical_hash(semantic)


def _timestamp_value(value: str | None) -> datetime | None:
    return parse_utc_timestamp(value) if value is not None else None


def _database_clock() -> Any:
    from sqlalchemy import func

    return func.clock_timestamp()


def _expected_artifact_read_size(stored_size: int | None) -> int:
    if stored_size is None:
        return MAX_LEGACY_DOCUMENT_ARTIFACT_READ_BYTES
    if (
        type(stored_size) is not int
        or not 0 <= stored_size <= MAX_ARTIFACT_RESPONSE_BYTES
    ):
        raise DocumentsStorageError("stored document artifact size is invalid")
    return stored_size
