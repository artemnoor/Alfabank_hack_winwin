"""Semantic OpenAPI component export and conformance comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from ._base import OpenAPIModel
from .models import SCHEMA_NAMES, SCHEMA_TYPES


def export_component_schemas() -> dict[str, Any]:
    """Export generated Pydantic types as named OpenAPI component schemas."""
    schemas: dict[str, Any] = {}
    generated_name_to_component: dict[str, str] = {}
    for component_name, schema_type in SCHEMA_TYPES.items():
        model_name = getattr(schema_type, "__name__", None)
        if model_name and model_name != component_name:
            existing = generated_name_to_component.get(model_name)
            if existing is not None and existing != component_name:
                raise ValueError(f"generated Python type {model_name!r} maps to multiple OpenAPI components")
            generated_name_to_component[model_name] = component_name

    definitions: dict[str, Any] = {}
    for component_name, schema_type in SCHEMA_TYPES.items():
        if isinstance(schema_type, type) and issubclass(schema_type, BaseModel):
            schema = schema_type.model_json_schema(ref_template="#/components/schemas/{model}")
        else:
            schema = TypeAdapter(schema_type).json_schema(ref_template="#/components/schemas/{model}")
        component_definitions = schema.pop("$defs", {})
        for definition_name, definition in component_definitions.items():
            canonical_name = generated_name_to_component.get(definition_name, definition_name)
            previous = definitions.get(canonical_name)
            if previous is not None and _normalise(previous, definitions) != _normalise(definition, definitions):
                raise ValueError(f"Pydantic emitted conflicting definitions for {canonical_name!r}")
            definitions[canonical_name] = definition
        schemas[component_name] = schema

    for schema_name in (*definitions.keys(), *schemas.keys()):
        schema = definitions.get(schema_name, schemas.get(schema_name))
        if schema is not None:
            _remap_references(schema, generated_name_to_component)

    # JSON Schema permits anyOf for a non-discriminated union. This operation's
    # normative oneOf is exclusive because both parameter models are closed and
    # have disjoint shapes; keep the stronger published contract in the export.
    implementation_parameters = schemas.get("ImplementationParameters")
    if implementation_parameters and "anyOf" in implementation_parameters:
        implementation_parameters["oneOf"] = implementation_parameters.pop("anyOf")

    missing = sorted(set(SCHEMA_NAMES) - set(schemas))
    if missing:
        raise ValueError(f"Pydantic export is missing OpenAPI components: {missing}")
    all_schema_sources = {**definitions, **schemas}
    normative_names = set(SCHEMA_NAMES)
    result = {
        name: _inline_generator_helpers(schemas[name], all_schema_sources, normative_names, frozenset({name}))
        for name in SCHEMA_NAMES
    }
    return result


def compare_openapi_components(
    openapi: dict[str, Any] | None = None,
    *,
    openapi_path: Path | None = None,
) -> list[str]:
    """Return semantic diffs for every normative OpenAPI component schema."""
    if openapi is None:
        if openapi_path is None:
            root = Path(__file__).resolve().parents[4]
            openapi_path = root / "docs/specs/framework-v1/contracts/openapi.json"
        openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    normative = openapi["components"]["schemas"]
    exported = export_component_schemas()
    diffs: list[str] = []
    for name in sorted(normative):
        actual = exported.get(name)
        if actual is None:
            diffs.append(f"/components/schemas/{name}: missing from Pydantic export")
            continue
        # Pydantic may add optional discriminator mappings even when the
        # normative OpenAPI leaves them out. Ignore only such extra metadata;
        # when OpenAPI declares a mapping, the generated mapping is compared.
        expected_normalised = _normalise(actual=normative[name], components=normative)
        exported_normalised = _normalise(actual=actual, components=exported)
        exported_normalised = _align_optional_discriminator_metadata(exported_normalised, expected_normalised)
        if expected_normalised != exported_normalised:
            diffs.append(
                f"/components/schemas/{name}: Pydantic schema differs from normative OpenAPI\n"
                f"  expected={json.dumps(expected_normalised, ensure_ascii=False, sort_keys=True)}\n"
                f"  exported={json.dumps(exported_normalised, ensure_ascii=False, sort_keys=True)}"
            )
    return diffs


def _remap_references(value: Any, names: dict[str, str]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            target = ref.removeprefix("#/components/schemas/")
            if target in names:
                value["$ref"] = "#/components/schemas/" + names[target]
        for child in value.values():
            _remap_references(child, names)
    elif isinstance(value, list):
        for child in value:
            _remap_references(child, names)


def _inline_generator_helpers(
    value: Any,
    sources: dict[str, Any],
    normative_names: set[str],
    seen: frozenset[str],
) -> Any:
    """Inline codegen-only enum/type aliases while preserving normative refs."""
    if isinstance(value, list):
        return [_inline_generator_helpers(item, sources, normative_names, seen) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        target = ref.removeprefix("#/components/schemas/")
        if target not in normative_names and target in sources and target not in seen:
            resolved = _inline_generator_helpers(sources[target], sources, normative_names, seen | {target})
            siblings = {
                key: child
                for key, child in value.items()
                if key != "$ref"
            }
            if siblings:
                resolved = {**resolved, **_inline_generator_helpers(siblings, sources, normative_names, seen)}
            return resolved
    return {
        key: _inline_generator_helpers(child, sources, normative_names, seen)
        for key, child in value.items()
    }


def _normalise(actual: Any, components: dict[str, Any], seen: frozenset[str] = frozenset()) -> Any:
    """Dereference and canonicalise JSON Schema while preserving validation semantics."""
    if isinstance(actual, list):
        return [_normalise(item, components, seen) for item in actual]
    if not isinstance(actual, dict):
        if isinstance(actual, float) and actual.is_integer():
            return int(actual)
        return actual
    if "$ref" in actual:
        target = actual["$ref"].removeprefix("#/components/schemas/")
        if target in seen:
            return {"$recursiveRef": target}
        if target not in components:
            return {"$unresolvedRef": target}
        resolved = _normalise(components[target], components, seen | {target})
        siblings = {key: value for key, value in actual.items() if key != "$ref"}
        return {**resolved, **_normalise(siblings, components, seen)} if siblings else resolved

    ignored = {"title", "description", "examples", "example", "deprecated", "readOnly", "writeOnly"}
    result: dict[str, Any] = {}
    for key, value in actual.items():
        if key in ignored:
            continue
        if key == "required" and value == []:
            continue
        if key == "required" and isinstance(value, list):
            result[key] = sorted(value)
        elif key == "discriminator" and isinstance(value, dict):
            discriminator = {"propertyName": value.get("propertyName")}
            if "mapping" in value:
                discriminator["mapping"] = value["mapping"]
            result[key] = discriminator
        elif key == "enum" and isinstance(value, list):
            result[key] = sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
        elif key in {"oneOf", "anyOf", "allOf"} and isinstance(value, list):
            branches = [_normalise(item, components, seen) for item in value]
            result[key] = sorted(branches, key=lambda item: json.dumps(item, sort_keys=True))
        else:
            result[key] = _normalise(value, components, seen)
    return result


def _align_optional_discriminator_metadata(actual: Any, normative: Any) -> Any:
    """Drop only generated discriminator mappings absent from the normative schema."""
    if isinstance(actual, list) and isinstance(normative, list):
        # Preserve unmatched generated branches: truncating to the shorter list
        # would hide a missing or extra union branch from the comparison.
        return [
            (
                _align_optional_discriminator_metadata(actual_item, normative[index])
                if index < len(normative)
                else actual_item
            )
            for index, actual_item in enumerate(actual)
        ]
    if not isinstance(actual, dict) or not isinstance(normative, dict):
        return actual
    aligned: dict[str, Any] = {}
    for key, value in actual.items():
        normative_value = normative.get(key)
        if key == "discriminator" and isinstance(value, dict) and isinstance(normative_value, dict):
            discriminator = dict(value)
            if "mapping" not in normative_value:
                discriminator.pop("mapping", None)
            aligned[key] = discriminator
        else:
            aligned[key] = _align_optional_discriminator_metadata(value, normative_value)
    return aligned
