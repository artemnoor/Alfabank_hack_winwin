"""Shared composition root for the HTTP and CLI execution adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alfalab_contracts import (
    DocumentResult,
    DocumentSelection,
    FetchInput,
    FetchOutput,
    ReadDocumentsInput,
    ReceiptQuery,
    ReceiptResult,
)

from alfalab.bootstrap.registry import (
    RuntimeRegistry,
    create_runtime_registry,
    repository_root,
)
from alfalab.execution.context import ExecutionLimits
from alfalab.execution.gateway import DependencyDefinition
from alfalab.execution.policy import (
    TrustedDataPolicyResolver,
    TrustedSource,
    load_approved_prepare_sources,
)
from alfalab.execution.service import ExecutionService
from alfalab.modules.documents.storage.artifacts import ArtifactStore
from alfalab.modules.documents.storage.database import create_documents_engine
from alfalab.modules.documents.storage.replay import (
    RegisterBeforeState,
    RegisterBeforeStateRequest,
)
from alfalab.modules.documents.storage.service import DocumentsStorage
from alfalab.modules.runs.storage.database import create_runs_engine
from alfalab.modules.runs.storage.memory import InMemoryRunsRepository
from alfalab.modules.runs.storage.postgres import PostgresRunsRepository
from alfalab.modules.runs.storage.repository import RunsRepository
from alfalab.modules.sources.fixture_catalog import load_fixture_source_catalog
from alfalab.modules.sources.implementations.fetch import FixtureSourceFetch


class _UnavailableRunsRepository:
    """Fail-closed adapter used when a development profile lacks local DB config."""

    def write(self, record, /) -> None:
        del record
        raise OSError("Runs history is unavailable")

    def query(
        self, payload, *, tenant_id, sandbox_id, exclude_run_id, include_artifacts
    ):
        del payload, tenant_id, sandbox_id, exclude_run_id, include_artifacts
        raise OSError("Runs history is unavailable")

    def get(self, run_id, *, tenant_id=None, sandbox_id=None):
        del run_id, tenant_id, sandbox_id

    def close(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class ExecutionRuntime:
    registry: RuntimeRegistry
    runs_writer: RunsRepository
    execution_service: ExecutionService
    limits: ExecutionLimits
    runs_repository: RunsRepository
    documents_storage: DocumentsStorage | None = None
    documents_engine: object | None = None

    def close(self) -> None:
        self.runs_repository.close()
        if self.documents_engine is not None:
            self.documents_engine.dispose()


def create_execution_runtime(
    environment: str,
    *,
    runs_database_url: str | None = None,
    runs_repository: RunsRepository | None = None,
    trusted_sources: dict[str, TrustedSource] | None = None,
    artifact_root: Path | None = None,
    documents_database_url: str | None = None,
    documents_storage: DocumentsStorage | None = None,
    dependency_overrides: dict[str, DependencyDefinition] | None = None,
) -> ExecutionRuntime:
    """Build the shared registry, policy kernel, owner storage, and service."""
    limits = ExecutionLimits()
    if runs_repository is not None:
        repository = runs_repository
    elif runs_database_url:
        repository = PostgresRunsRepository(
            create_runs_engine(runs_database_url),
            environment=environment,
            artifact_root=artifact_root or (repository_root() / ".local" / "artifacts"),
        )
    elif environment == "testing":
        repository = InMemoryRunsRepository()
    else:
        repository = _UnavailableRunsRepository()

    root = repository_root()
    fixture_catalog = load_fixture_source_catalog(root)
    source_registry = load_approved_prepare_sources(root)
    if trusted_sources is not None:
        source_registry.update(trusted_sources)
    for source_id, source in fixture_catalog.sources().items():
        source_registry.setdefault(
            source_id,
            TrustedSource(
                classification="synthetic",
                processing_allowed=True,
                egress_allowed=True,
                recording="full",
                export_allowed=True,
                source_binding_hash=source.binding_hash,
            ),
        )

    def trusted_material(
        material, tenant_id: str, allowed_sandboxes: frozenset[str]
    ) -> bool:
        if not fixture_catalog.matches_material(material):
            return False
        producer_run_id = material.provenance.producer_run_id
        if producer_run_id is None:
            return True
        for source_sandbox in allowed_sandboxes:
            try:
                stored = repository.get(
                    producer_run_id,
                    tenant_id=tenant_id,
                    sandbox_id=source_sandbox,
                )
            except OSError:
                return False
            if (
                stored is None
                or stored.record.operation_id != "Sources.fetch"
                or stored.record.status != "success"
                or stored.record.replay_status != "available"
                or stored.record.trace_status != "complete"
                or stored.record.output is None
                or stored.record.output.ref.schema_id != "FetchOutput"
                or stored.record.manifest.data_classification != "synthetic"
                or stored.record.manifest.recording != "full"
            ):
                continue
            try:
                contents = repository.read_replay_artifacts(
                    producer_run_id,
                    (stored.record.output.ref,),
                    tenant_id=tenant_id,
                    sandbox_id=source_sandbox,
                )
                if contents is None:
                    continue
                output = FetchOutput.model_validate_json(
                    contents[stored.record.output.ref.artifact_id], strict=True
                )
            except (KeyError, ValueError, OSError):
                continue
            if any(
                candidate.model_dump(mode="json") == material.model_dump(mode="json")
                and candidate.provenance.producer_run_id == producer_run_id
                for candidate in output.materials
            ):
                return True
        return False

    documents_engine = None
    if documents_storage is None:
        database_url = documents_database_url or runs_database_url
        if database_url:
            documents_engine = create_documents_engine(database_url)
            documents_storage = DocumentsStorage(
                documents_engine,
                ArtifactStore(artifact_root or (root / ".local" / "artifacts")),
                trusted_material=lambda material, context: trusted_material(
                    material,
                    context.principal.tenant_id,
                    context.principal.allowed_sandboxes,
                ),
                trusted_content_hash=fixture_catalog.trusts_content_hash,
            )

    dependencies = {
        "sources.fixture": DependencyDefinition(
            dependency_id="sources.fixture",
            kind="source",
            request_type=FetchInput,
            response_type=FetchOutput,
            invoke=FixtureSourceFetch(fixture_catalog).fetch,
            sensitive_values=(),
            secret_inventory_complete=True,
            requires_egress=False,
        )
    }
    if documents_storage is not None:

        def capture_before(request: RegisterBeforeStateRequest, context):
            return documents_storage.capture_register_before_state(request, context)

        def read_versions(request: DocumentSelection, context):
            return documents_storage.read(ReadDocumentsInput(query=request), context)

        def read_receipt(request: ReceiptQuery, context):
            return documents_storage.read(ReadDocumentsInput(query=request), context)

        dependencies.update(
            {
                "documents.register.before_state": DependencyDefinition(
                    dependency_id="documents.register.before_state",
                    kind="owner_read",
                    request_type=RegisterBeforeStateRequest,
                    response_type=RegisterBeforeState,
                    invoke=capture_before,
                    sensitive_values=(),
                    secret_inventory_complete=True,
                    requires_egress=False,
                ),
                "documents.read.versions": DependencyDefinition(
                    dependency_id="documents.read.versions",
                    kind="owner_read",
                    request_type=DocumentSelection,
                    response_type=DocumentResult,
                    invoke=read_versions,
                    sensitive_values=(),
                    secret_inventory_complete=True,
                    requires_egress=False,
                ),
                "documents.read.receipt": DependencyDefinition(
                    dependency_id="documents.read.receipt",
                    kind="owner_read",
                    request_type=ReceiptQuery,
                    response_type=ReceiptResult,
                    invoke=read_receipt,
                    sensitive_values=(),
                    secret_inventory_complete=True,
                    requires_egress=False,
                ),
            }
        )
    if dependency_overrides:
        dependencies.update(dependency_overrides)

    registry = create_runtime_registry(
        environment,
        repository,
        dependencies,
        documents_storage=documents_storage,
    )
    policy_resolver = TrustedDataPolicyResolver(
        source_registry,
        approved_content_hashes=frozenset(
            material.content_hash
            for source in fixture_catalog.sources().values()
            for material in source.materials
        ),
        material_validator=trusted_material,
        document_hash_resolver=(
            documents_storage.content_hashes_for_read
            if documents_storage is not None
            else None
        ),
    )
    execution_service = ExecutionService(
        registry,
        repository,
        environment=environment,
        limits=limits,
        policy_resolver=policy_resolver,
    )
    return ExecutionRuntime(
        registry=registry,
        runs_writer=repository,
        execution_service=execution_service,
        limits=limits,
        runs_repository=repository,
        documents_storage=documents_storage,
        documents_engine=documents_engine,
    )
