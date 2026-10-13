"""Build the immutable, contract-checked runtime operation registry."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alfalab_contracts import (
    FetchInput,
    FetchOutput,
    ImplementationDescriptor,
    MockParameters,
    OperationDescriptor,
    PrepareInput,
    PrepareOutput,
    QueryRunsInput,
    QueryRunsOutput,
    ReadDocumentsInput,
    ReadDocumentsOutput,
    RealPrepareParameters,
    RegisterDocumentInput,
    RegisterDocumentOutput,
)
from alfalab_contracts.registry import (
    OperationContract,
    build_operation_descriptor,
    load_operation_registry,
)
from pydantic import BaseModel

from alfalab.common.protocols import OperationContext
from alfalab.execution.gateway import DependencyDefinition
from alfalab.modules.documents.implementations.prepare import (
    BaselineMockPrepare,
    RealPrepare,
)
from alfalab.modules.documents.operations.read import ReadOperation
from alfalab.modules.documents.operations.register import RegisterOperation
from alfalab.modules.documents.storage.service import DocumentsStorage
from alfalab.modules.runs.implementation import QueryRuns
from alfalab.modules.runs.storage.repository import RunsRepository
from alfalab.modules.sources.implementations.fetch import FetchOperation


@dataclass(frozen=True, slots=True)
class RegisteredImplementation[PayloadT: BaseModel, OutputT: BaseModel]:
    id: str
    version: str
    kind: str
    parameter_type: type
    payload_type: type[BaseModel]
    output_type: type[BaseModel]
    execute: Callable[[PayloadT, OperationContext], OutputT]
    configuration: dict[str, object]
    dependency_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RuntimeRegistry:
    contracts: dict[str, OperationContract]
    descriptors: dict[str, OperationDescriptor]
    implementations: dict[tuple[str, str, str], RegisteredImplementation[Any, Any]]
    dependencies: dict[str, DependencyDefinition]

    def contract(self, operation_id: str) -> OperationContract:
        return self.contracts[operation_id]

    def descriptor(self, operation_id: str) -> OperationDescriptor:
        return self.descriptors[operation_id]

    def available_routes(self) -> tuple[OperationDescriptor, ...]:
        return tuple(
            descriptor
            for descriptor in self.descriptors.values()
            if descriptor.implementations
        )


def repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def runtime_build_hash() -> str:
    root = repository_root()
    files = [
        *sorted((root / "apps/api/src/alfalab").rglob("*.py")),
        root / "uv.lock",
        root / "docs/specs/framework-v1/contracts/openapi.json",
    ]
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def create_runtime_registry(
    environment: str,
    runs_repository: RunsRepository,
    dependencies: dict[str, DependencyDefinition] | None = None,
    *,
    documents_storage: DocumentsStorage | None = None,
) -> RuntimeRegistry:
    source_registry, contracts = load_operation_registry()
    prepare_implementations = (
        RegisteredImplementation(
            id="mock.baseline",
            version="1.0.0",
            kind="mock",
            parameter_type=MockParameters,
            payload_type=PrepareInput,
            output_type=PrepareOutput,
            execute=BaselineMockPrepare().execute,
            configuration={"scenario": "operation-default"},
        ),
        RegisteredImplementation(
            id="real.prepare",
            version="1.0.0",
            kind="real",
            parameter_type=RealPrepareParameters,
            payload_type=PrepareInput,
            output_type=PrepareOutput,
            execute=RealPrepare().execute,
            configuration={"algorithm": "documents-prepare-v1"},
        ),
    )
    implementations = {
        ("Documents.prepare", item.id, item.version): item
        for item in prepare_implementations
    }
    fetch_implementation = RegisteredImplementation(
        id="mock.baseline",
        version="1.0.0",
        kind="mock",
        parameter_type=MockParameters,
        payload_type=FetchInput,
        output_type=FetchOutput,
        execute=FetchOperation().execute,
        configuration={"adapter": "approved-local-fixture-v1"},
        dependency_ids=frozenset({"sources.fixture"}),
    )
    implementations[
        ("Sources.fetch", fetch_implementation.id, fetch_implementation.version)
    ] = fetch_implementation

    if documents_storage is not None:
        register_implementation = RegisteredImplementation(
            id="mock.baseline",
            version="1.0.0",
            kind="mock",
            parameter_type=MockParameters,
            payload_type=RegisterDocumentInput,
            output_type=RegisterDocumentOutput,
            execute=RegisterOperation(documents_storage).execute,
            configuration={"owner": "documents.postgres-v1"},
            dependency_ids=frozenset({"documents.register.before_state"}),
        )
        read_implementation = RegisteredImplementation(
            id="mock.baseline",
            version="1.0.0",
            kind="mock",
            parameter_type=MockParameters,
            payload_type=ReadDocumentsInput,
            output_type=ReadDocumentsOutput,
            execute=ReadOperation(documents_storage).execute,
            configuration={"owner": "documents.postgres-v1"},
            dependency_ids=frozenset(
                {"documents.read.versions", "documents.read.receipt"}
            ),
        )
        implementations[
            (
                "Documents.register",
                register_implementation.id,
                register_implementation.version,
            )
        ] = register_implementation
        implementations[
            ("Documents.read", read_implementation.id, read_implementation.version)
        ] = read_implementation
    query_implementation = RegisteredImplementation(
        id="mock.baseline",
        version="1.0.0",
        kind="mock",
        parameter_type=MockParameters,
        payload_type=QueryRunsInput,
        output_type=QueryRunsOutput,
        execute=QueryRuns(runs_repository).execute,
        configuration={"scenario": "operation-default"},
    )
    implementations[
        ("Runs.query", query_implementation.id, query_implementation.version)
    ] = query_implementation

    descriptors: dict[str, OperationDescriptor] = {}
    for entry in source_registry.operations:
        actual: list[ImplementationDescriptor] = []
        if entry.operation_id == "Sources.fetch" and environment in {
            "development",
            "testing",
        }:
            actual = [
                ImplementationDescriptor(
                    id="mock.baseline",
                    version="1.0.0",
                    kind="mock",
                    available=True,
                    reason=None,
                    parameter_schema_id="MockParameters",
                    capabilities=["deterministic", "registered_source_only"],
                    environments=["development", "testing"],
                )
            ]
        elif entry.operation_id == "Documents.prepare":
            if environment in {"development", "testing"}:
                actual = [
                    ImplementationDescriptor(
                        id="mock.baseline",
                        version="1.0.0",
                        kind="mock",
                        available=True,
                        reason=None,
                        parameter_schema_id="MockParameters",
                        capabilities=["deterministic", "span_mapping"],
                        environments=["development", "testing"],
                    ),
                    ImplementationDescriptor(
                        id="real.prepare",
                        version="1.0.0",
                        kind="real",
                        available=True,
                        reason=None,
                        parameter_schema_id="RealPrepareParameters",
                        capabilities=["deterministic", "span_mapping"],
                        environments=["development", "testing"],
                    ),
                ]
        elif (
            entry.operation_id in {"Documents.register", "Documents.read"}
            and documents_storage is not None
            and environment in {"development", "testing"}
        ):
            actual = [
                ImplementationDescriptor(
                    id="mock.baseline",
                    version="1.0.0",
                    kind="mock",
                    available=True,
                    reason=None,
                    parameter_schema_id="MockParameters",
                    capabilities=["postgres_owner", "scope_isolated"],
                    environments=["development", "testing"],
                )
            ]
        elif entry.operation_id == "Runs.query" and environment in {
            "development",
            "testing",
        }:
            actual = [
                ImplementationDescriptor(
                    id="mock.baseline",
                    version="1.0.0",
                    kind="mock",
                    available=True,
                    reason=None,
                    parameter_schema_id="MockParameters",
                    capabilities=["deterministic", "scope_isolated"],
                    environments=["development", "testing"],
                )
            ]
        descriptors[entry.operation_id] = build_operation_descriptor(
            entry,
            actual,
            effects=[],
        )

    return RuntimeRegistry(
        contracts=contracts,
        descriptors=descriptors,
        implementations=implementations,
        dependencies=dict(dependencies or {}),
    )
