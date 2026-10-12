"""Typed source-operation registry and runtime contract bindings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, TypeAliasType

from pydantic import ConfigDict, Field, StrictInt, StrictStr, TypeAdapter

from ._base import OpenAPIModel
from ._generated import ImplementationDescriptor, OperationDescriptor
from .models import SCHEMA_TYPES
from .semantics import validate_operation_semantics

RegistryCheck: TypeAlias = Literal[
    "contract",
    "http",
    "mock",
    "fixtures",
    "independent",
    "playground",
    "history",
    "provenance",
    "replay",
    "negative",
    "boundaries",
    "idempotency",
    "state_conflict",
    "receipt_recovery",
]
Owner: TypeAlias = Literal[
    "sources",
    "documents",
    "understanding",
    "events",
    "business",
    "graph",
    "matching",
    "impact",
    "recommendations",
    "evidence",
    "runs",
    "cases",
    "evaluation",
]
OperationKind: TypeAlias = Literal["source", "compute", "read", "command"]
ReplayProfile: TypeAlias = Literal[
    "restore_state",
    "recorded_owner_read",
    "recorded_dependencies",
    "fixed_input",
]
SchemaType: TypeAlias = type[OpenAPIModel] | TypeAliasType


class RegistryModel(OpenAPIModel):
    """Strict model for operations.json, distinct from the public API DTO."""

    model_config = ConfigDict(extra="forbid", strict=True)


class OperationRegistryEntry(RegistryModel):
    number: StrictInt = Field(ge=1, le=25)
    operation_id: StrictStr = Field(min_length=1, max_length=120)
    owner: Owner
    kind: OperationKind
    path: StrictStr = Field(min_length=1, max_length=300)
    method: Literal["POST"]
    contract_version: StrictStr = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    request_model: StrictStr
    input_model: StrictStr
    output_model: StrictStr
    response_model: StrictStr
    mock: StrictStr
    initial_real: StrictStr | None
    checks: list[RegistryCheck] = Field(min_length=1, max_length=20)
    replay_profile: ReplayProfile
    schema_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    purpose: StrictStr
    domain_dependencies: StrictStr
    reads_state: StrictStr
    writes_state: StrictStr
    semantic_invariants: StrictStr
    fixture_recipes: StrictStr


class OperationRegistry(RegistryModel):
    version: StrictStr = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    closed_operation_count: Literal[25]
    operations: list[OperationRegistryEntry] = Field(min_length=25, max_length=25)


@dataclass(frozen=True, slots=True)
class OperationContract:
    """Typed request/input/output/response binding for a public operation."""

    descriptor: OperationRegistryEntry
    request_type: type[OpenAPIModel]
    input_type: SchemaType
    output_type: SchemaType
    response_type: type[OpenAPIModel]


def _component_closure_hash(openapi: dict, root_names: tuple[str, str]) -> str:
    schemas = openapi["components"]["schemas"]
    pending = list(root_names)
    closure: set[str] = set()
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        if name not in schemas:
            raise ValueError(f"operation references unknown OpenAPI schema {name!r}")
        closure.add(name)
        pending.extend(_schema_references(schemas[name]))
    canonical = {name: schemas[name] for name in sorted(closure)}
    wire = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(wire).hexdigest()


def _schema_references(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.append(ref.removeprefix("#/components/schemas/"))
        for child in value.values():
            found.extend(_schema_references(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_schema_references(child))
    return found


def load_operation_registry(
    registry_path: Path | None = None,
    openapi_path: Path | None = None,
) -> tuple[OperationRegistry, dict[str, OperationContract]]:
    """Load strict source descriptors and verify them against normative OpenAPI."""
    root = Path(__file__).resolve().parents[4]
    registry_path = registry_path or root / "docs/specs/framework-v1/contracts/operations.json"
    openapi_path = openapi_path or root / "docs/specs/framework-v1/contracts/openapi.json"
    registry = OperationRegistry.model_validate_json(registry_path.read_bytes(), strict=True)
    openapi = json.loads(openapi_path.read_text(encoding="utf-8"))

    entries = registry.operations
    operation_ids = [entry.operation_id for entry in entries]
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("operation registry contains duplicate operation IDs")
    if [entry.number for entry in entries] != list(range(1, 26)):
        raise ValueError("operation registry numbers must be contiguous from 1 through 25")

    openapi_operations: dict[str, tuple[str, str, str, str]] = {}
    for path, path_item in openapi["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                raise ValueError(f"OpenAPI execution route {method.upper()} {path} has no operationId")
            request_ref = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("$ref")
            response_ref = operation.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("$ref")
            if not request_ref or not response_ref:
                raise ValueError(f"OpenAPI operation {operation_id} has incomplete JSON request/response schemas")
            openapi_operations[operation_id] = (path, method.upper(), request_ref.rsplit("/", 1)[-1], response_ref.rsplit("/", 1)[-1])

    if set(operation_ids) != set(openapi_operations):
        raise ValueError("registry operation IDs do not exactly match /api/v1 OpenAPI operations")

    contracts: dict[str, OperationContract] = {}
    for entry in entries:
        path, method, request_name, response_name = openapi_operations[entry.operation_id]
        expected = (entry.path, entry.method, entry.request_model, entry.response_model)
        if expected != (path, method, request_name, response_name):
            raise ValueError(f"registry/OpenAPI route mismatch for {entry.operation_id}")
        if _component_closure_hash(openapi, (request_name, response_name)) != entry.schema_hash:
            raise ValueError(f"schema closure hash mismatch for {entry.operation_id}")
        names = (entry.request_model, entry.input_model, entry.output_model, entry.response_model)
        missing = [name for name in names if name not in SCHEMA_TYPES]
        if missing:
            raise ValueError(f"generated schema types are missing for {entry.operation_id}: {missing}")
        types = tuple(SCHEMA_TYPES[name] for name in names)
        request_type, input_type, output_type, response_type = types
        if not all(
            isinstance(value, type) and issubclass(value, OpenAPIModel)
            for value in (request_type, response_type)
        ):
            raise ValueError(f"request/response schemas must be objects for {entry.operation_id}")
        if not all(
            isinstance(value, (type, TypeAliasType))
            for value in (input_type, output_type)
        ):
            raise ValueError(f"input/output schema is not an executable type for {entry.operation_id}")
        if request_type.model_fields["payload"].annotation is not input_type:
            raise ValueError(f"request payload type does not match registry for {entry.operation_id}")
        if response_type.model_fields["payload"].annotation is not output_type:
            raise ValueError(f"response payload type does not match registry for {entry.operation_id}")
        contracts[entry.operation_id] = OperationContract(
            descriptor=entry,
            request_type=request_type,
            input_type=input_type,
            output_type=output_type,
            response_type=response_type,
        )
    return registry, contracts


def build_operation_descriptor(
    entry: OperationRegistryEntry,
    implementations: list[ImplementationDescriptor],
    effects: list[str],
) -> OperationDescriptor:
    """Project registry metadata into the public descriptor using actual status.

    Availability and effect strings are explicit inputs so the projection never
    invents that an implementation is installed or runnable.
    """
    request_schema_id = entry.request_model
    response_schema_id = entry.response_model
    return OperationDescriptor(
        operation_id=entry.operation_id,
        contract_version=entry.contract_version,
        path=entry.path,
        method=entry.method,
        kind=entry.kind,
        request_schema_id=request_schema_id,
        response_schema_id=response_schema_id,
        implementations=implementations,
        effects=effects,
        replay_profile=entry.replay_profile,
    )


def validate_operation_request(contract: OperationContract, wire_json: str | bytes) -> OpenAPIModel:
    """Strictly validate a complete operation request from its wire JSON."""
    return contract.request_type.model_validate_json(wire_json, strict=True)


def validate_operation_response(contract: OperationContract, wire_json: str | bytes) -> OpenAPIModel:
    """Strictly validate a complete successful operation response."""
    return contract.response_type.model_validate_json(wire_json, strict=True)


def validate_operation_exchange(
    contract: OperationContract,
    request_json: str | bytes,
    response_json: str | bytes,
) -> tuple[OpenAPIModel, OpenAPIModel]:
    """Validate a request/response pair, including operation-level invariants.

    The future execution mechanism should use this boundary after computing a
    response. It validates both wire envelopes before applying cross-payload
    rules; it does not call implementations or access owner state.
    """
    request = validate_operation_request(contract, request_json)
    response = validate_operation_response(contract, response_json)
    validate_operation_semantics(contract.descriptor.operation_id, request, response)
    return request, response


def validate_schema_json(schema_name: str, wire_json: str | bytes) -> object:
    """Validate a payload alias or object schema in strict JSON mode."""
    try:
        schema_type = SCHEMA_TYPES[schema_name]
    except KeyError as exc:
        raise KeyError(f"unknown OpenAPI component schema {schema_name!r}") from exc
    return TypeAdapter(schema_type).validate_json(wire_json, strict=True)
