"""Build the immutable, contract-checked runtime operation registry."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from alfalab_contracts import (
    ImplementationDescriptor,
    OperationDescriptor,
    PrepareInput,
    PrepareOutput,
    RealPrepareParameters,
    MockParameters,
)
from alfalab_contracts.registry import (
    OperationContract,
    build_operation_descriptor,
    load_operation_registry,
)

from alfalab.execution.context import OperationContext
from alfalab.modules.documents.implementations.prepare import BaselineMockPrepare, RealPrepare


@dataclass(frozen=True, slots=True)
class RegisteredImplementation:
    id: str
    version: str
    kind: str
    parameter_type: type
    execute: Callable[[PrepareInput, OperationContext], PrepareOutput]
    configuration: dict[str, object]


@dataclass(frozen=True, slots=True)
class RuntimeRegistry:
    contracts: dict[str, OperationContract]
    descriptors: dict[str, OperationDescriptor]
    implementations: dict[tuple[str, str, str], RegisteredImplementation]

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


def create_runtime_registry(environment: str) -> RuntimeRegistry:
    source_registry, contracts = load_operation_registry()
    prepare_implementations = (
        RegisteredImplementation(
            id="mock.baseline",
            version="1.0.0",
            kind="mock",
            parameter_type=MockParameters,
            execute=BaselineMockPrepare().execute,
            configuration={"scenario": "operation-default"},
        ),
        RegisteredImplementation(
            id="real.prepare",
            version="1.0.0",
            kind="real",
            parameter_type=RealPrepareParameters,
            execute=RealPrepare().execute,
            configuration={"algorithm": "documents-prepare-v1"},
        ),
    )
    implementations = {
        ("Documents.prepare", item.id, item.version): item
        for item in prepare_implementations
    }

    descriptors: dict[str, OperationDescriptor] = {}
    for entry in source_registry.operations:
        actual: list[ImplementationDescriptor] = []
        if entry.operation_id == "Documents.prepare":
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
        descriptors[entry.operation_id] = build_operation_descriptor(
            entry,
            actual,
            effects=[],
        )

    return RuntimeRegistry(
        contracts=contracts,
        descriptors=descriptors,
        implementations=implementations,
    )
