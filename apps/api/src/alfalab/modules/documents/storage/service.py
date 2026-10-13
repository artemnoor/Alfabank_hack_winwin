"""Documents repository, command, and historical read behavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from alfalab_contracts import (
    CommandReceipt,
    DocumentResult,
    DocumentSelection,
    DocumentVersion,
    ObjectRef,
    RawMaterial,
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
from sqlalchemy.exc import IntegrityError

from alfalab.common.limits import (
    MAX_ARTIFACT_RESPONSE_BYTES,
    MAX_LEGACY_DOCUMENT_ARTIFACT_READ_BYTES,
)
from alfalab.execution.temporal import parse_utc_timestamp

from ..validation import validate_registered_content
from .artifacts import ArtifactStore
from .canonical import canonical_hash
from .context import OperationContext, TrustedScope, owner_command_context
from .errors import (
    DocumentsPolicyDenied,
    DocumentsStorageError,
    ExpectedRevisionConflict,
)
from .policy import (
    DEFAULT_SCOPE_POLICY,
    DOCUMENTS_READ_PERMISSION,
    DOCUMENTS_REGISTER_PERMISSION,
    ScopePolicy,
    require_permission,
)
from .replay import (
    RegisterBeforeState,
    RegisterBeforeStateRequest,
    RestorableDocumentVersion,
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
        *,
        trusted_material: Callable[[RawMaterial, OperationContext], bool] | None = None,
        trusted_content_hash: Callable[[str], bool] | None = None,
    ) -> None:
        self._engine = engine
        self._artifacts = artifacts
        self._scope_policy = scope_policy
        self._trusted_material = trusted_material or (lambda _material, _context: False)
        self._trusted_content_hash = trusted_content_hash or (lambda _hash: False)
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

        validate_registered_content(payload.raw, payload.prepared)
        if not self._trusted_material(payload.raw, context):
            raise DocumentsPolicyDenied(
                "trusted source policy does not authorize storing this content"
            )
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
            recorded_at = context.domain_clock.now()
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

    def content_hashes_for_read(
        self,
        payload: ReadDocumentsInput,
        *,
        tenant_id: str,
        sandbox_id: str,
        environment: str = "testing",
    ) -> tuple[str, ...]:
        """Read only owner metadata needed for a pre-content policy decision."""
        scope = TrustedScope(tenant_id, sandbox_id, environment)
        if isinstance(payload.query, DocumentSelection):
            hashes: list[str] = []
            with self._engine.connect() as connection:
                for document_id in payload.query.document_ids:
                    record = self._select_version(
                        connection, scope, document_id, payload.query
                    )
                    if record is not None:
                        hashes.append(record["raw_content_hash"])
            return tuple(hashes)
        if isinstance(payload.query, ReceiptQuery):
            with self._engine.connect() as connection:
                receipt = self._receipt_metadata(connection, scope, payload.query)
                if receipt is None:
                    return ()
                return self._content_hashes_for_audit(
                    connection, scope, receipt["audit_id"]
                )
        raise TypeError("unsupported Documents.read query kind")

    def capture_register_before_state(
        self,
        request: RegisterBeforeStateRequest,
        context: OperationContext,
        /,
    ) -> RegisterBeforeState:
        """Capture a bounded, typed immutable owner snapshot before a command."""
        scope = self._scope_policy.resolve(context)
        require_permission(context, DOCUMENTS_READ_PERMISSION)
        with self._engine.connect() as connection:
            current_revision = connection.execute(
                select(documents.c.current_revision).where(
                    documents.c.tenant_id == scope.tenant_id,
                    documents.c.sandbox_id == scope.sandbox_id,
                    documents.c.document_id == request.document_id,
                )
            ).scalar_one_or_none()
            current_revision = current_revision or 0
            receipt_key = {
                "tenant_id": scope.tenant_id,
                "sandbox_id": scope.sandbox_id,
                "operation_id": REGISTER_OPERATION_ID,
                "contract_major": 1,
                "idempotency_key": request.idempotency_key,
            }
            key_used = (
                connection.execute(
                    select(command_receipts.c.idempotency_key)
                    .where(*_equals(command_receipts, receipt_key))
                    .limit(1)
                ).first()
                is not None
            )
            claim_exists = (
                connection.execute(
                    select(command_claims.c.idempotency_key)
                    .where(*_equals(command_claims, receipt_key))
                    .limit(1)
                ).first()
                is not None
            )
            key_used = key_used or claim_exists
            if current_revision == 0:
                return RegisterBeforeState(
                    document_id=request.document_id,
                    current_revision=0,
                    versions=[],
                    replayable=not key_used,
                )
            rows = (
                connection.execute(
                    select(versions)
                    .where(
                        versions.c.tenant_id == scope.tenant_id,
                        versions.c.sandbox_id == scope.sandbox_id,
                        versions.c.document_id == request.document_id,
                        versions.c.revision <= current_revision,
                    )
                    .order_by(versions.c.revision)
                )
                .mappings()
                .all()
            )
            if len(rows) != current_revision:
                raise DocumentsStorageError("document history is incomplete")
            total_size = 0
            for row in rows:
                raw_size = row["raw_artifact_size_bytes"]
                prepared_size = row["prepared_artifact_size_bytes"]
                if row["prepared_artifact_hash"] is None:
                    prepared_size = 0
                if (
                    not self._trusted_content_hash(row["raw_content_hash"])
                    or type(raw_size) is not int
                    or raw_size < 0
                    or raw_size > MAX_ARTIFACT_RESPONSE_BYTES
                    or type(prepared_size) is not int
                    or prepared_size < 0
                    or prepared_size > MAX_ARTIFACT_RESPONSE_BYTES
                ):
                    return RegisterBeforeState(
                        document_id=request.document_id,
                        current_revision=current_revision,
                        versions=[],
                        replayable=False,
                    )
                total_size += raw_size + prepared_size
                if total_size > MAX_ARTIFACT_RESPONSE_BYTES:
                    return RegisterBeforeState(
                        document_id=request.document_id,
                        current_revision=current_revision,
                        versions=[],
                        replayable=False,
                    )
            restored = [
                RestorableDocumentVersion(
                    version=self._materialize_version(connection, scope, row),
                    semantic_hash=row["semantic_hash"],
                    published_at=(
                        _timestamp_string(row["published_at"])
                        if row["published_at"] is not None
                        else None
                    ),
                    recorded_at=_timestamp_string(row["recorded_at"]),
                )
                for row in rows
            ]
        return RegisterBeforeState(
            document_id=request.document_id,
            current_revision=current_revision,
            versions=restored,
            replayable=not key_used,
        )

    def restore_register_before_state(
        self,
        snapshot: RegisterBeforeState,
        request: RegisterBeforeStateRequest,
        context: OperationContext,
        /,
    ) -> None:
        """Restore command state only into an empty, different replay sandbox."""
        if (
            getattr(context, "execution_mode", "live") != "replay"
            or getattr(context, "replay_source_sandbox_id", None) == context.sandbox_id
            or not snapshot.replayable
            or snapshot.document_id != request.document_id
        ):
            raise DocumentsPolicyDenied("recorded command state is unavailable")
        if snapshot.current_revision != request.expected_revision:
            raise DocumentsPolicyDenied(
                "recorded command state does not match the request"
            )
        scope = self._scope_policy.resolve(context)
        if [item.version.ref.revision for item in snapshot.versions] != list(
            range(1, snapshot.current_revision + 1)
        ):
            raise DocumentsStorageError("recorded command state has invalid revisions")

        receipt_key = {
            "tenant_id": scope.tenant_id,
            "sandbox_id": scope.sandbox_id,
            "operation_id": REGISTER_OPERATION_ID,
            "contract_major": 1,
            "idempotency_key": request.idempotency_key,
        }
        try:
            with self._engine.begin() as connection:
                existing_document = connection.execute(
                    select(documents.c.current_revision).where(
                        documents.c.tenant_id == scope.tenant_id,
                        documents.c.sandbox_id == scope.sandbox_id,
                        documents.c.document_id == snapshot.document_id,
                    )
                ).first()
                existing_receipt = connection.execute(
                    select(command_receipts.c.idempotency_key)
                    .where(*_equals(command_receipts, receipt_key))
                    .limit(1)
                ).first()
                existing_claim = connection.execute(
                    select(command_claims.c.idempotency_key)
                    .where(*_equals(command_claims, receipt_key))
                    .limit(1)
                ).first()
                if existing_document or existing_receipt or existing_claim:
                    raise DocumentsPolicyDenied(
                        "replay target already contains command state"
                    )
                if snapshot.current_revision == 0:
                    return

                restored_rows: list[dict[str, Any]] = []
                parent_ref = None
                for item in snapshot.versions:
                    version = item.version
                    if (
                        version.ref.object_id != snapshot.document_id
                        or version.parent_ref != parent_ref
                    ):
                        raise DocumentsStorageError(
                            "recorded command state has invalid lineage"
                        )
                    validate_registered_content(version.raw, version.prepared)
                    if not self._trusted_material(version.raw, context):
                        raise DocumentsPolicyDenied(
                            "recorded command state is not approved by data policy"
                        )
                    version_body = {
                        "kind": str(getattr(version.kind, "value", version.kind)),
                        "raw": version.raw.model_dump(mode="json"),
                        "prepared": version.prepared.model_dump(mode="json")
                        if version.prepared
                        else None,
                        "parent_ref": parent_ref.model_dump(mode="json")
                        if parent_ref
                        else None,
                    }
                    if canonical_hash(version_body) != version.ref.hash:
                        raise DocumentsStorageError(
                            "recorded command state failed hash verification"
                        )
                    raw_artifact = self._artifacts.put_json(
                        scope,
                        version.raw,
                        schema_id="RawMaterial",
                        schema_version=CONTRACT_VERSION,
                    )
                    prepared_artifact = (
                        self._artifacts.put_json(
                            scope,
                            version.prepared,
                            schema_id="PreparedMaterial",
                            schema_version=CONTRACT_VERSION,
                        )
                        if version.prepared is not None
                        else None
                    )
                    restored_rows.append(
                        {
                            "tenant_id": scope.tenant_id,
                            "sandbox_id": scope.sandbox_id,
                            "document_id": snapshot.document_id,
                            "revision": version.ref.revision,
                            "kind": str(getattr(version.kind, "value", version.kind)),
                            "raw_artifact_hash": raw_artifact.artifact_ref.hash,
                            "raw_artifact_size_bytes": raw_artifact.artifact_ref.size_bytes,
                            "prepared_artifact_hash": prepared_artifact.artifact_ref.hash
                            if prepared_artifact
                            else None,
                            "prepared_artifact_size_bytes": prepared_artifact.artifact_ref.size_bytes
                            if prepared_artifact
                            else None,
                            "raw_content_hash": version.raw.content_hash,
                            "semantic_hash": item.semantic_hash,
                            "version_hash": version.ref.hash,
                            "parent_revision": version.parent_ref.revision
                            if version.parent_ref
                            else None,
                            "published_at": _timestamp_value(item.published_at),
                            "recorded_at": parse_utc_timestamp(item.recorded_at),
                        }
                    )
                    parent_ref = version.ref
                connection.execute(
                    insert(documents).values(
                        tenant_id=scope.tenant_id,
                        sandbox_id=scope.sandbox_id,
                        document_id=snapshot.document_id,
                        current_revision=0,
                    )
                )
                for row in restored_rows:
                    connection.execute(insert(versions).values(**row))
                connection.execute(
                    update(documents)
                    .where(
                        documents.c.tenant_id == scope.tenant_id,
                        documents.c.sandbox_id == scope.sandbox_id,
                        documents.c.document_id == snapshot.document_id,
                    )
                    .values(current_revision=snapshot.current_revision)
                )
        except IntegrityError as exc:
            raise DocumentsPolicyDenied(
                "replay target changed while restoring command state"
            ) from exc

    def _read_receipt(self, scope: TrustedScope, query: ReceiptQuery) -> ReceiptResult:
        key = {
            "tenant_id": scope.tenant_id,
            "sandbox_id": scope.sandbox_id,
            "operation_id": query.operation_id,
            "contract_major": 1,
            "idempotency_key": query.idempotency_key,
        }
        with self._engine.connect() as connection:
            metadata_record = self._receipt_metadata(connection, scope, query)
            if metadata_record is None:
                return ReceiptResult(kind="receipt", receipt=None)
            hashes = self._content_hashes_for_audit(
                connection, scope, metadata_record["audit_id"]
            )
            if not hashes or not all(
                self._trusted_content_hash(value) for value in hashes
            ):
                raise DocumentsPolicyDenied(
                    "trusted source policy denies receipt content"
                )
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
        try:
            validate_registered_content(response.version.raw, response.version.prepared)
        except ValueError as exc:
            raise DocumentsStorageError(
                "stored receipt document failed content validation"
            ) from exc
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
                    if not self._trusted_content_hash(record["raw_content_hash"]):
                        raise DocumentsPolicyDenied(
                            "trusted source policy denies document content"
                        )
                    results.append(self._materialize_version(connection, scope, record))
        return DocumentResult(kind="documents", versions=results, missing_ids=missing)

    @staticmethod
    def _receipt_metadata(
        connection: Connection, scope: TrustedScope, query: ReceiptQuery
    ) -> Mapping[str, Any] | None:
        return (
            connection.execute(
                select(
                    command_receipts.c.audit_id,
                    command_receipts.c.tenant_id,
                    command_receipts.c.sandbox_id,
                ).where(
                    command_receipts.c.tenant_id == scope.tenant_id,
                    command_receipts.c.sandbox_id == scope.sandbox_id,
                    command_receipts.c.operation_id == query.operation_id,
                    command_receipts.c.contract_major == 1,
                    command_receipts.c.idempotency_key == query.idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _content_hashes_for_audit(
        connection: Connection, scope: TrustedScope, audit_id: str
    ) -> tuple[str, ...]:
        refs = connection.execute(
            select(audit_entries.c.after_refs).where(
                audit_entries.c.tenant_id == scope.tenant_id,
                audit_entries.c.sandbox_id == scope.sandbox_id,
                audit_entries.c.audit_id == audit_id,
            )
        ).scalar_one_or_none()
        if not isinstance(refs, list):
            return ()
        hashes: list[str] = []
        for value in refs:
            if not isinstance(value, dict) or value.get("owner") != "Documents":
                continue
            raw_hash = connection.execute(
                select(versions.c.raw_content_hash).where(
                    versions.c.tenant_id == scope.tenant_id,
                    versions.c.sandbox_id == scope.sandbox_id,
                    versions.c.document_id == value.get("object_id"),
                    versions.c.revision == value.get("revision"),
                )
            ).scalar_one_or_none()
            if raw_hash is not None:
                hashes.append(raw_hash)
        return tuple(hashes)

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
        try:
            validate_registered_content(raw, prepared)
        except ValueError as exc:
            raise DocumentsStorageError(
                "stored document artifacts failed content validation"
            ) from exc
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


def _timestamp_string(value: datetime) -> str:
    if value.tzinfo is None:
        raise DocumentsStorageError("database timestamp has no timezone")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _expected_artifact_read_size(stored_size: int | None) -> int:
    if stored_size is None:
        return MAX_LEGACY_DOCUMENT_ARTIFACT_READ_BYTES
    if (
        type(stored_size) is not int
        or not 0 <= stored_size <= MAX_ARTIFACT_RESPONSE_BYTES
    ):
        raise DocumentsStorageError("stored document artifact size is invalid")
    return stored_size
