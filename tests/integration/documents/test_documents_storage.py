from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from alfalab.common.limits import MAX_ARTIFACT_RESPONSE_BYTES
from alfalab.execution.context import SystemDomainClock
from alfalab.modules.documents.operations.read import ReadOperation
from alfalab.modules.documents.operations.register import RegisterOperation
from alfalab.modules.documents.storage.artifacts import (
    ArtifactIntegrityError,
    ArtifactStore,
)
from alfalab.modules.documents.storage.context import TrustedScope
from alfalab.modules.documents.storage.errors import (
    DocumentsPolicyDenied,
    DocumentsStorageError,
    ExpectedRevisionConflict,
    IdempotencyConflict,
    ScopeDenied,
)
from alfalab.modules.documents.storage.schema import (
    audit_entries,
    command_receipts,
    versions,
)
from alfalab.modules.documents.storage.service import DocumentsStorage
from alfalab_contracts import (
    DocumentSelection,
    PreparedMaterial,
    Provenance,
    RawMaterial,
    ReadDocumentsInput,
    ReceiptQuery,
    RegisterDocumentInput,
    SpanMap,
    TimeSlice,
)
from sqlalchemy import create_engine, event, select, text

ROOT = Path(__file__).resolve().parents[3]


def test_documents_migrations_upgrade_downgrade_upgrade(admin_dsn):
    previous_url = os.environ.get("ALFALAB_MIGRATION_DATABASE_URL")
    os.environ["ALFALAB_MIGRATION_DATABASE_URL"] = admin_dsn
    config = Config(str(ROOT / "infra" / "alembic.ini"))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        engine = create_engine(admin_dsn, pool_pre_ping=True, echo=False)
        try:
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT to_regclass('documents.versions')")
                    ).scalar_one()
                    == "documents.versions"
                )
                columns = (
                    connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema='documents' AND table_name='versions'"
                        )
                    )
                    .scalars()
                    .all()
                )
                assert "raw_artifact_size_bytes" in columns
                assert "prepared_artifact_size_bytes" in columns
        finally:
            engine.dispose()
    finally:
        if previous_url is None:
            os.environ.pop("ALFALAB_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["ALFALAB_MIGRATION_DATABASE_URL"] = previous_url


def _hash_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _raw(
    material_id: str, text: str, *, published_at: str | None = None
) -> RawMaterial:
    provenance = Provenance(
        origin="synthetic",
        source_refs=[],
        input_statement_refs=[],
        producer_run_id=None,
        derivation_method=None,
        evidence_refs=[],
        origin_verified=False,
    )
    return RawMaterial(
        material_id=material_id,
        source_id=None,
        source_url=None,
        title="Тестовый документ",
        text=text,
        published_at=published_at,
        collected_at="2026-10-12T10:00:00Z",
        content_hash=_hash_text(text),
        language="ru",
        provenance=provenance,
    )


def _payload(
    document_id: str,
    expected_revision: int,
    text: str,
    *,
    published_at: str | None = None,
    with_prepared: bool = True,
):
    raw = _raw(f"raw-{document_id}", text, published_at=published_at)
    prepared_text = text.strip()
    prepared_material = raw.model_copy(
        update={
            "text": prepared_text,
            "content_hash": _hash_text(prepared_text),
        }
    )
    trim_start = len(text) - len(text.lstrip())
    prepared = PreparedMaterial(
        material=prepared_material,
        raw_hash=raw.content_hash,
        prepared_hash=prepared_material.content_hash,
        quality="valid" if prepared_text else "rejected",
        span_map=(
            [
                SpanMap(
                    prepared_start=0,
                    prepared_end=len(prepared_text),
                    raw_start=trim_start,
                    raw_end=trim_start + len(prepared_text),
                )
            ]
            if prepared_text
            else []
        ),
        warnings=[] if prepared_text else ["empty_text"],
    )
    return RegisterDocumentInput(
        document_id=document_id,
        expected_revision=expected_revision,
        raw=raw,
        prepared=prepared if with_prepared else None,
    )


def _context(
    tenant_id: str,
    sandbox_id: str,
    *,
    key: str | None,
    operation_id: str,
    run_id: str | None = None,
):
    return SimpleNamespace(
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        environment="testing",
        run_id=run_id or f"run-{uuid.uuid4().hex}",
        operation_id=operation_id,
        request_id=f"request-{uuid.uuid4().hex}",
        contract_version="1.0.0",
        idempotency_key=key,
        implementation_id="documents.owner-storage",
        implementation_version="1.0.0",
        implementation_configuration_hash=_hash_text("documents-owner-storage-v1"),
        domain_clock=SystemDomainClock(),
        principal=SimpleNamespace(
            tenant_id=tenant_id,
            actor_id="actor-test",
            role="developer",
            permissions=frozenset({"documents.read", "documents.register"}),
            allowed_sandboxes=frozenset({sandbox_id}),
        ),
    )


def _new_scope() -> tuple[str, str]:
    suffix = uuid.uuid4().hex
    return f"t04-{suffix}", f"s04-{suffix}"


def _read(
    storage: DocumentsStorage,
    tenant_id: str,
    sandbox_id: str,
    document_id: str,
    *,
    revision=None,
    as_of=None,
):
    request = ReadDocumentsInput(
        query=DocumentSelection(
            kind="documents",
            document_ids=[document_id],
            revision=revision,
            as_of=as_of,
        )
    )
    return storage.read(
        request,
        _context(tenant_id, sandbox_id, key=None, operation_id="Documents.read"),
    )


def _register(storage, tenant_id, sandbox_id, payload, key, *, run_id=None):
    context = _context(
        tenant_id,
        sandbox_id,
        key=key,
        operation_id="Documents.register",
        run_id=run_id,
    )
    return storage.register(payload, context)


def test_register_read_revision_receipt_and_as_of_roundtrip(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    initial = _payload(document_id, 0, "Кириллица и документ")

    first = _register(
        documents_storage, tenant, sandbox, initial, f"key-{uuid.uuid4().hex}"
    )
    assert first.version.ref.revision == 1
    assert first.version.kind == "prepared"
    assert first.version.prepared is not None
    assert first.receipt.applied is True
    assert first.receipt.changed_refs == [first.version.ref]

    latest = _read(documents_storage, tenant, sandbox, document_id)
    assert latest.versions == [first.version]
    assert latest.missing_ids == []

    revised = _payload(document_id, 1, "Исправленный текст")
    second = _register(
        documents_storage, tenant, sandbox, revised, f"key-{uuid.uuid4().hex}"
    )
    assert second.version.ref.revision == 2
    assert second.version.parent_ref == first.version.ref
    assert _read(
        documents_storage, tenant, sandbox, document_id, revision=1
    ).versions == [first.version]
    assert _read(documents_storage, tenant, sandbox, document_id).versions == [
        second.version
    ]

    unknown_publication = _payload(f"unknown-{uuid.uuid4().hex}", 0, "Неизвестная дата")
    unknown_id = unknown_publication.document_id
    _register(
        documents_storage,
        tenant,
        sandbox,
        unknown_publication,
        f"key-{uuid.uuid4().hex}",
    )
    as_of = TimeSlice(
        valid_as_of="2099-01-01T00:00:00Z", known_as_of="2099-01-01T00:00:00Z"
    )
    assert (
        _read(documents_storage, tenant, sandbox, unknown_id, as_of=as_of)
        .versions[0]
        .raw.published_at
        is None
    )

    missing = _read(documents_storage, tenant, sandbox, "not-present")
    assert missing.versions == []
    assert missing.missing_ids == ["not-present"]

    receipt_result = documents_storage.read(
        ReadDocumentsInput(
            query=ReceiptQuery(
                kind="receipt",
                operation_id="Documents.register",
                idempotency_key=first.receipt.idempotency_key,
            )
        ),
        _context(tenant, sandbox, key=None, operation_id="Documents.read"),
    )
    assert receipt_result.receipt == first.receipt


@pytest.mark.parametrize(
    ("artifact_hash_field", "artifact_size_field"),
    [
        ("raw_artifact_hash", "raw_artifact_size_bytes"),
        ("prepared_artifact_hash", "prepared_artifact_size_bytes"),
    ],
)
def test_documents_read_bounds_artifact_read_to_persisted_size(
    documents_storage,
    documents_engine,
    monkeypatch,
    artifact_hash_field,
    artifact_size_field,
):
    tenant, sandbox = _new_scope()
    document_id = f"bounded-{uuid.uuid4().hex}"
    _register(
        documents_storage,
        tenant,
        sandbox,
        _payload(document_id, 0, "Bounded artifact content"),
        f"key-{uuid.uuid4().hex}",
    )
    with documents_engine.connect() as connection:
        version = (
            connection.execute(
                select(versions).where(
                    versions.c.tenant_id == tenant,
                    versions.c.sandbox_id == sandbox,
                    versions.c.document_id == document_id,
                )
            )
            .mappings()
            .one()
        )
    artifact_hash = version[artifact_hash_field]
    expected_size = version[artifact_size_field]
    assert artifact_hash is not None
    assert expected_size > 0

    artifact_path = (
        ROOT
        / ".local"
        / "artifacts"
        / "testing"
        / tenant
        / sandbox
        / f"{artifact_hash.removeprefix('sha256:')}.json"
    )
    artifact_path.write_bytes(b"x" * (expected_size + 4096))

    expected_reads = []
    original_read_json = ArtifactStore.read_json

    def tracked_read_json(self, scope, value_hash, *, expected_size_bytes=None):
        expected_reads.append(expected_size_bytes)
        return original_read_json(
            self,
            scope,
            value_hash,
            expected_size_bytes=expected_size_bytes,
        )

    monkeypatch.setattr(ArtifactStore, "read_json", tracked_read_json)
    with pytest.raises(ArtifactIntegrityError):
        _read(documents_storage, tenant, sandbox, document_id)
    if artifact_hash_field == "raw_artifact_hash":
        assert expected_reads == [expected_size]
    else:
        assert expected_reads == [version["raw_artifact_size_bytes"], expected_size]


def test_documents_read_rejects_corrupt_oversized_size_before_disk_read(
    documents_storage,
    monkeypatch,
):
    tenant, sandbox = _new_scope()
    read_calls = []

    def forbidden_read(*args, **kwargs):
        read_calls.append((args, kwargs))
        raise AssertionError("artifact file must not be opened for an invalid size")

    monkeypatch.setattr(ArtifactStore, "read_json", forbidden_read)
    record = {
        "raw_artifact_hash": "sha256:" + "a" * 64,
        "raw_artifact_size_bytes": MAX_ARTIFACT_RESPONSE_BYTES + 1,
    }
    with pytest.raises(DocumentsStorageError, match="artifact size is invalid"):
        documents_storage._materialize_version(
            None,
            TrustedScope(tenant, sandbox, "testing"),
            record,
        )
    assert read_calls == []


def test_documents_read_uses_bounded_fallback_for_legacy_null_size(
    documents_storage,
    admin_dsn,
    monkeypatch,
    tmp_path,
):
    documents_storage._artifacts = ArtifactStore(tmp_path)
    tenant, sandbox = _new_scope()
    document_id = f"legacy-bounded-{uuid.uuid4().hex}"
    _register(
        documents_storage,
        tenant,
        sandbox,
        _payload(document_id, 0, "Legacy artifact content", with_prepared=False),
        f"key-{uuid.uuid4().hex}",
    )
    admin_engine = create_engine(admin_dsn, pool_pre_ping=True, echo=False)
    try:
        with admin_engine.begin() as connection:
            version = (
                connection.execute(
                    select(versions).where(
                        versions.c.tenant_id == tenant,
                        versions.c.sandbox_id == sandbox,
                        versions.c.document_id == document_id,
                    )
                )
                .mappings()
                .one()
            )
            connection.execute(
                versions.update()
                .where(
                    versions.c.tenant_id == tenant,
                    versions.c.sandbox_id == sandbox,
                    versions.c.document_id == document_id,
                )
                .values(raw_artifact_size_bytes=None)
            )
    finally:
        admin_engine.dispose()

    artifact_hash = version["raw_artifact_hash"]
    artifact_path = (
        tmp_path
        / "testing"
        / tenant
        / sandbox
        / f"{artifact_hash.removeprefix('sha256:')}.json"
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_cap = 32
    artifact_path.write_bytes(b"x" * (legacy_cap + 1))
    monkeypatch.setattr(
        "alfalab.modules.documents.storage.service.MAX_LEGACY_DOCUMENT_ARTIFACT_READ_BYTES",
        legacy_cap,
    )

    expected_reads = []
    original_read_json = ArtifactStore.read_json

    def tracked_read_json(self, scope, value_hash, *, expected_size_bytes=None):
        expected_reads.append(expected_size_bytes)
        return original_read_json(
            self,
            scope,
            value_hash,
            expected_size_bytes=expected_size_bytes,
        )

    monkeypatch.setattr(ArtifactStore, "read_json", tracked_read_json)
    with pytest.raises(ArtifactIntegrityError):
        _read(documents_storage, tenant, sandbox, document_id)
    assert expected_reads == [legacy_cap]


def test_as_of_uses_publication_and_recorded_time_and_rejects_mixed_selector(
    documents_storage,
):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    published = _payload(
        document_id,
        0,
        "Published on a known date",
        published_at="2026-10-10T00:00:00Z",
    )
    _register(documents_storage, tenant, sandbox, published, f"key-{uuid.uuid4().hex}")

    before_publication = TimeSlice(
        valid_as_of="2026-10-09T00:00:00Z", known_as_of="2099-01-01T00:00:00Z"
    )
    after_publication = TimeSlice(
        valid_as_of="2026-10-11T00:00:00Z", known_as_of="2099-01-01T00:00:00Z"
    )
    assert _read(
        documents_storage, tenant, sandbox, document_id, as_of=before_publication
    ).missing_ids == [document_id]
    assert (
        len(
            _read(
                documents_storage, tenant, sandbox, document_id, as_of=after_publication
            ).versions
        )
        == 1
    )

    invalid = ReadDocumentsInput(
        query=DocumentSelection(
            kind="documents",
            document_ids=[document_id],
            revision=1,
            as_of=after_publication,
        )
    )
    with pytest.raises(ValueError, match="revision and as_of"):
        documents_storage.read(
            invalid, _context(tenant, sandbox, key=None, operation_id="Documents.read")
        )


def test_idempotency_conflicts_and_same_content_noop(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    key = f"key-{uuid.uuid4().hex}"
    payload = _payload(document_id, 0, "Один и тот же текст")

    first = _register(
        documents_storage, tenant, sandbox, payload, key, run_id="run-first"
    )
    retry = _register(
        documents_storage, tenant, sandbox, payload, key, run_id="run-retry"
    )
    assert retry == first
    assert retry.receipt.original_run_id == "run-first"

    changed = _payload(document_id, 0, "Другой текст")
    with pytest.raises(IdempotencyConflict):
        _register(documents_storage, tenant, sandbox, changed, key)

    changed_permissions = _context(
        tenant,
        sandbox,
        key=key,
        operation_id="Documents.register",
    )
    changed_permissions.principal.permissions = frozenset(
        {"documents.read", "documents.register", "documents.prepare"}
    )
    with pytest.raises(IdempotencyConflict):
        documents_storage.register(payload, changed_permissions)

    changed_implementation = _context(
        tenant,
        sandbox,
        key=key,
        operation_id="Documents.register",
    )
    changed_implementation.implementation_version = "1.1.0"
    with pytest.raises(IdempotencyConflict):
        documents_storage.register(payload, changed_implementation)

    same_content_new_key = _payload(document_id, 1, "Один и тот же текст")
    duplicate = _register(
        documents_storage,
        tenant,
        sandbox,
        same_content_new_key,
        f"key-{uuid.uuid4().hex}",
    )
    assert duplicate.version.ref == first.version.ref
    assert duplicate.receipt.applied is False
    assert duplicate.receipt.changed_refs == []

    with pytest.raises(ExpectedRevisionConflict):
        _register(
            documents_storage, tenant, sandbox, payload, f"key-{uuid.uuid4().hex}"
        )


def test_register_requires_documents_register_permission(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    context = _context(
        tenant,
        sandbox,
        key=f"key-{uuid.uuid4().hex}",
        operation_id="Documents.register",
    )
    context.principal.permissions = frozenset({"documents.read"})

    with pytest.raises(ScopeDenied):
        documents_storage.register(_payload(document_id, 0, "Denied write"), context)
    assert _read(documents_storage, tenant, sandbox, document_id).missing_ids == [
        document_id
    ]


def test_register_denies_untrusted_material_before_owner_writes(
    documents_engine, tmp_path
):
    from alfalab.modules.documents.storage.schema import documents

    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    storage = DocumentsStorage(documents_engine, ArtifactStore(tmp_path / "artifacts"))
    context = _context(
        tenant,
        sandbox,
        key=f"key-{uuid.uuid4().hex}",
        operation_id="Documents.register",
    )

    with pytest.raises(DocumentsPolicyDenied):
        storage.register(_payload(document_id, 0, "Untrusted content"), context)

    with documents_engine.connect() as connection:
        assert (
            connection.execute(
                select(documents.c.document_id).where(
                    documents.c.tenant_id == tenant,
                    documents.c.sandbox_id == sandbox,
                    documents.c.document_id == document_id,
                )
            ).first()
            is None
        )


def test_documents_read_rejects_same_size_tampered_artifact(documents_engine, tmp_path):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    artifact_root = tmp_path / "artifacts"
    storage = DocumentsStorage(
        documents_engine,
        ArtifactStore(artifact_root),
        trusted_material=lambda _material, _context: True,
        trusted_content_hash=lambda _content_hash: True,
    )
    _register(
        storage,
        tenant,
        sandbox,
        _payload(document_id, 0, "Tamper detection material"),
        f"key-{uuid.uuid4().hex}",
    )
    with documents_engine.connect() as connection:
        artifact_hash = connection.execute(
            select(versions.c.raw_artifact_hash).where(
                versions.c.tenant_id == tenant,
                versions.c.sandbox_id == sandbox,
                versions.c.document_id == document_id,
            )
        ).scalar_one()
    path = (
        artifact_root
        / "testing"
        / tenant
        / sandbox
        / f"{artifact_hash.removeprefix('sha256:')}.json"
    )
    contents = bytearray(path.read_bytes())
    contents[0] = ord(" ") if contents[0] != ord(" ") else ord("!")
    path.write_bytes(contents)

    with pytest.raises(ArtifactIntegrityError) as error:
        _read(storage, tenant, sandbox, document_id)
    assert "Tamper detection material" not in str(error.value)


def test_register_rejects_span_map_outside_raw_text_before_commit(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    key = f"key-{uuid.uuid4().hex}"
    payload = _payload(document_id, 0, "Short")
    prepared = payload.prepared
    assert prepared is not None
    invalid_prepared = prepared.model_copy(
        update={
            "span_map": [
                SpanMap(
                    prepared_start=0,
                    prepared_end=len(prepared.material.text),
                    raw_start=0,
                    raw_end=len(payload.raw.text) + 1,
                )
            ]
        }
    )
    invalid_payload = payload.model_copy(update={"prepared": invalid_prepared})
    context = _context(
        tenant,
        sandbox,
        key=key,
        operation_id="Documents.register",
    )

    with pytest.raises(ValueError, match="span map exceeds registered raw text"):
        documents_storage.register(invalid_payload, context)

    assert _read(documents_storage, tenant, sandbox, document_id).missing_ids == [
        document_id
    ]
    receipt = documents_storage.read(
        ReadDocumentsInput(
            query=ReceiptQuery(
                kind="receipt",
                operation_id="Documents.register",
                idempotency_key=key,
            )
        ),
        _context(tenant, sandbox, key=None, operation_id="Documents.read"),
    )
    assert receipt.receipt is None


def test_documents_and_receipt_reads_require_documents_read_permission(
    documents_storage,
):
    tenant, sandbox = _new_scope()
    context = _context(
        tenant,
        sandbox,
        key=None,
        operation_id="Documents.read",
    )
    context.principal.permissions = frozenset({"documents.register"})
    documents_query = ReadDocumentsInput(
        query=DocumentSelection(
            kind="documents",
            document_ids=["doc-absent"],
            revision=None,
            as_of=None,
        )
    )
    receipt_query = ReadDocumentsInput(
        query=ReceiptQuery(
            kind="receipt",
            operation_id="Documents.register",
            idempotency_key="key-absent",
        )
    )

    with pytest.raises(ScopeDenied):
        documents_storage.read(documents_query, context)
    with pytest.raises(ScopeDenied):
        documents_storage.read(receipt_query, context)


def test_concurrent_duplicate_returns_one_atomic_commit(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    key = f"key-{uuid.uuid4().hex}"
    payload = _payload(document_id, 0, "Одновременная регистрация")

    def call(run_id: str):
        return _register(
            documents_storage, tenant, sandbox, payload, key, run_id=run_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(call, "run-concurrent-a")
        second_future = pool.submit(call, "run-concurrent-b")
        first = first_future.result(timeout=20)
        second = second_future.result(timeout=20)
    assert first == second
    assert first.version.ref.revision == 1

    with documents_storage._engine.connect() as connection:
        version_count = connection.execute(
            select(versions.c.revision).where(
                versions.c.tenant_id == tenant,
                versions.c.sandbox_id == sandbox,
                versions.c.document_id == document_id,
            )
        ).all()
        receipt_count = connection.execute(
            select(command_receipts.c.idempotency_key).where(
                command_receipts.c.tenant_id == tenant,
                command_receipts.c.sandbox_id == sandbox,
                command_receipts.c.idempotency_key == key,
            )
        ).all()
        audit_count = connection.execute(
            select(audit_entries.c.audit_id).where(
                audit_entries.c.tenant_id == tenant,
                audit_entries.c.sandbox_id == sandbox,
            )
        ).all()
    assert len(version_count) == len(receipt_count) == len(audit_count) == 1


def test_concurrent_distinct_keys_same_expected_revision_conflict_atomically(
    documents_storage,
):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    keys = (f"key-{uuid.uuid4().hex}", f"key-{uuid.uuid4().hex}")
    payload = _payload(document_id, 0, "Одновременные независимые команды")

    def call(key: str, run_id: str):
        try:
            return (
                "success",
                _register(
                    documents_storage, tenant, sandbox, payload, key, run_id=run_id
                ),
            )
        except ExpectedRevisionConflict:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(call, keys[0], "run-distinct-key-a"),
            pool.submit(call, keys[1], "run-distinct-key-b"),
        ]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(result[0] for result in results) == ["conflict", "success"]
    winner_index = next(
        index for index, result in enumerate(results) if result[0] == "success"
    )

    with documents_storage._engine.connect() as connection:
        revisions = connection.execute(
            select(versions.c.revision).where(
                versions.c.tenant_id == tenant,
                versions.c.sandbox_id == sandbox,
                versions.c.document_id == document_id,
            )
        ).all()
        receipts = connection.execute(
            select(command_receipts.c.idempotency_key).where(
                command_receipts.c.tenant_id == tenant,
                command_receipts.c.sandbox_id == sandbox,
                command_receipts.c.operation_id == "Documents.register",
            )
        ).all()
        audits = connection.execute(
            select(audit_entries.c.audit_id).where(
                audit_entries.c.tenant_id == tenant,
                audit_entries.c.sandbox_id == sandbox,
            )
        ).all()
    assert revisions == [(1,)]
    assert receipts == [(keys[winner_index],)]
    assert len(audits) == 1


def test_failure_after_commit_replays_saved_response(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    key = f"key-{uuid.uuid4().hex}"
    payload = _payload(document_id, 0, "Ответ потерян после фиксации")
    committed_response = None

    def deliver_response():
        nonlocal committed_response
        committed_response = _register(documents_storage, tenant, sandbox, payload, key)
        raise RuntimeError("simulated response loss after commit")

    with pytest.raises(RuntimeError, match="response loss after commit"):
        deliver_response()

    retry = _register(
        documents_storage, tenant, sandbox, payload, key, run_id="run-after-commit"
    )
    assert retry == committed_response
    with documents_storage._engine.connect() as connection:
        version_count = connection.execute(
            select(versions.c.revision).where(
                versions.c.tenant_id == tenant,
                versions.c.sandbox_id == sandbox,
                versions.c.document_id == document_id,
            )
        ).all()
        receipt_count = connection.execute(
            select(command_receipts.c.idempotency_key).where(
                command_receipts.c.tenant_id == tenant,
                command_receipts.c.sandbox_id == sandbox,
                command_receipts.c.idempotency_key == key,
            )
        ).all()
        audit_count = connection.execute(
            select(audit_entries.c.audit_id).where(
                audit_entries.c.tenant_id == tenant,
                audit_entries.c.sandbox_id == sandbox,
            )
        ).all()
    assert len(version_count) == len(receipt_count) == len(audit_count) == 1


def test_failure_before_commit_rolls_back_and_same_key_can_retry(
    documents_storage, documents_engine
):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    key = f"key-{uuid.uuid4().hex}"
    payload = _payload(document_id, 0, "Откат до фиксации")

    def fail_before_receipt(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        if (
            statement.lstrip()
            .lower()
            .startswith("insert into documents.command_receipts")
        ):
            raise RuntimeError("simulated failure before commit")

    event.listen(documents_engine, "before_cursor_execute", fail_before_receipt)
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            _register(documents_storage, tenant, sandbox, payload, key)
    finally:
        event.remove(documents_engine, "before_cursor_execute", fail_before_receipt)

    assert _read(documents_storage, tenant, sandbox, document_id).missing_ids == [
        document_id
    ]
    retry = _register(documents_storage, tenant, sandbox, payload, key)
    assert retry.version.ref.revision == 1
    assert retry.receipt.applied is True


def test_same_document_id_isolated_by_tenant_and_sandbox(
    documents_storage, documents_engine
):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    _register(
        documents_storage,
        tenant,
        sandbox,
        _payload(document_id, 0, "Scoped document"),
        f"key-{uuid.uuid4().hex}",
    )

    other_sandbox = f"other-{uuid.uuid4().hex}"
    same_tenant_context = _context(
        tenant, sandbox, key=None, operation_id="Documents.read"
    )
    same_tenant_context.sandbox_id = other_sandbox
    same_tenant_context.principal.allowed_sandboxes = frozenset(
        {sandbox, other_sandbox}
    )
    result = documents_storage.read(
        ReadDocumentsInput(
            query=DocumentSelection(
                kind="documents", document_ids=[document_id], revision=None, as_of=None
            )
        ),
        same_tenant_context,
    )
    assert result.missing_ids == [document_id]

    other_tenant = f"other-{uuid.uuid4().hex}"
    assert _read(documents_storage, other_tenant, sandbox, document_id).missing_ids == [
        document_id
    ]

    with documents_engine.connect() as connection:
        raw_hash = connection.execute(
            select(versions.c.raw_artifact_hash).where(
                versions.c.tenant_id == tenant,
                versions.c.sandbox_id == sandbox,
                versions.c.document_id == document_id,
            )
        ).scalar_one()
    store = ArtifactStore(ROOT / ".local" / "artifacts")
    with pytest.raises(ArtifactIntegrityError):
        store.read_json(TrustedScope(tenant, other_sandbox, "testing"), raw_hash)


def test_raw_only_registration_has_raw_kind(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    output = _register(
        documents_storage,
        tenant,
        sandbox,
        _payload(document_id, 0, "Raw source only", with_prepared=False),
        f"key-{uuid.uuid4().hex}",
    )
    assert output.version.kind == "raw"
    assert output.version.prepared is None


def test_operation_adapters_preserve_typed_register_read_contract(documents_storage):
    tenant, sandbox = _new_scope()
    document_id = f"doc-{uuid.uuid4().hex}"
    context = _context(
        tenant,
        sandbox,
        key=f"key-{uuid.uuid4().hex}",
        operation_id="Documents.register",
    )
    context.dependency_gateway = SimpleNamespace(
        invoke=lambda dependency_id, request: (
            documents_storage.capture_register_before_state(request, context)
        )
    )
    registered = RegisterOperation(documents_storage).execute(
        _payload(document_id, 0, "Operation protocol roundtrip"),
        context,
    )
    read_context = _context(tenant, sandbox, key=None, operation_id="Documents.read")
    read_context.dependency_gateway = SimpleNamespace(
        invoke=lambda dependency_id, request: documents_storage.read(
            ReadDocumentsInput(query=request), read_context
        )
    )
    read = ReadOperation(documents_storage).execute(
        ReadDocumentsInput(
            query=DocumentSelection(
                kind="documents", document_ids=[document_id], revision=None, as_of=None
            )
        ),
        read_context,
    )
    assert read.versions == [registered.version]
