from __future__ import annotations

import json
from copy import deepcopy

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from alfalab_contracts.conformance import compare_openapi_components, export_component_schemas
from alfalab_contracts.registry import (
    build_operation_descriptor,
    load_operation_registry,
    validate_operation_request,
    validate_operation_response,
)


def _component_validator(openapi: dict, component_name: str) -> Draft202012Validator:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "components": openapi["components"],
        "$ref": f"#/components/schemas/{component_name}",
    }
    return Draft202012Validator(schema)


def test_registry_is_exactly_the_25_normative_operations(openapi: dict) -> None:
    registry, contracts = load_operation_registry()
    operations = {
        operation["operationId"]
        for path, path_item in openapi["paths"].items()
        if path.startswith("/api/v1/")
        for method, operation in path_item.items()
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }

    assert registry.closed_operation_count == 25
    assert len(registry.operations) == len(contracts) == 25
    assert set(contracts) == operations
    for operation_id, contract in contracts.items():
        assert contract.request_type.model_fields["payload"].annotation is contract.input_type
        assert contract.response_type.model_fields["payload"].annotation is contract.output_type
        assert contract.descriptor.operation_id == operation_id


def test_runtime_descriptor_requires_actual_implementation_status() -> None:
    from alfalab_contracts import SCHEMA_TYPES

    registry, _ = load_operation_registry()
    entry = registry.operations[0]
    implementation = SCHEMA_TYPES["ImplementationDescriptor"].model_validate_json(
        json.dumps(
            {
                "id": "mock.baseline",
                "version": "1.0.0",
                "kind": "mock",
                "available": False,
                "reason": "not registered in this execution profile",
                "parameter_schema_id": "MockParameters",
                "capabilities": [],
                "environments": ["development", "testing"],
            }
        )
    )
    descriptor = build_operation_descriptor(entry, [implementation], [entry.writes_state])
    assert descriptor.operation_id == entry.operation_id
    assert descriptor.implementations[0].available is False
    assert descriptor.effects == [entry.writes_state]


def test_pydantic_export_matches_every_openapi_component() -> None:
    assert compare_openapi_components() == []


def test_declared_discriminator_mappings_are_part_of_conformance(openapi: dict) -> None:
    altered = deepcopy(openapi)
    altered["components"]["schemas"]["TypedValue"]["discriminator"]["mapping"] = {
        "boolean": "#/components/schemas/UnknownValue"
    }
    diffs = compare_openapi_components(altered)
    assert any(diff.startswith("/components/schemas/TypedValue:") for diff in diffs)

    altered = deepcopy(openapi)
    altered["components"]["schemas"]["ImplementationParameters"]["oneOf"].pop()
    diffs = compare_openapi_components(altered)
    assert any(diff.startswith("/components/schemas/ImplementationParameters:") for diff in diffs)


def test_operation_exchange_checks_inline_cross_payload_invariants(examples: list[dict]) -> None:
    from copy import deepcopy

    from alfalab_contracts.registry import load_operation_registry, validate_operation_exchange

    _, contracts = load_operation_registry()
    by_id = {example["operation_id"]: example for example in examples}

    matching = deepcopy(by_id["Matching.match"])
    validate_operation_exchange(
        contracts["Matching.match"],
        json.dumps(matching["request"], ensure_ascii=False),
        json.dumps(matching["response"], ensure_ascii=False),
    )
    matching["response"]["payload"]["candidate_scope"] = ["outside-scope"]
    try:
        validate_operation_exchange(
            contracts["Matching.match"],
            json.dumps(matching["request"], ensure_ascii=False),
            json.dumps(matching["response"], ensure_ascii=False),
        )
    except ValueError as exc:
        assert "candidate_scope" in str(exc)
    else:
        raise AssertionError("Matching.match accepted a candidate outside the declared scope")

    impact = deepcopy(by_id["Impact.assess"])
    validate_operation_exchange(
        contracts["Impact.assess"],
        json.dumps(impact["request"], ensure_ascii=False),
        json.dumps(impact["response"], ensure_ascii=False),
    )
    impact["response"]["payload"]["assessment"]["company"]["entity_id"] = "different-company"
    try:
        validate_operation_exchange(
            contracts["Impact.assess"],
            json.dumps(impact["request"], ensure_ascii=False),
            json.dumps(impact["response"], ensure_ascii=False),
        )
    except ValueError as exc:
        assert "match company" in str(exc) or "assessment company" in str(exc)
    else:
        raise AssertionError("Impact.assess accepted an assessment for a different company")

    impact = deepcopy(by_id["Impact.assess"])
    impact["request"]["payload"]["match"]["edge_paths"] = [["not-in-graph"]]
    try:
        validate_operation_exchange(
            contracts["Impact.assess"],
            json.dumps(impact["request"], ensure_ascii=False),
            json.dumps(impact["response"], ensure_ascii=False),
        )
    except ValueError as exc:
        assert "supplied graph" in str(exc)
    else:
        raise AssertionError("Impact.assess accepted a path edge absent from its graph")

    recommendations = deepcopy(by_id["Recommendations.propose"])
    request_payload = recommendations["request"]["payload"]
    action = {
        "code": {"namespace": "actions", "version": "1.0.0", "code": "review"},
        "title": "Review supplier exposure",
        "audiences": ["analyst"],
        "requires_approval": True,
    }
    request_payload["audience"] = "analyst"
    request_payload["allowed_actions"] = [action]
    assessment = request_payload["assessment"]
    recommendations["response"]["payload"]["recommendations"] = [
        {
            "recommendation_id": "recommendation-1",
            "assessment_id": assessment["assessment_id"],
            "action_type": action["code"],
            "title": "Review supplier exposure",
            "why": "The assessment identifies a possible supply dependency.",
            "priority": "medium",
            "conditions": [],
            "requires_approval": False,
            "evidence_refs": [],
            "provenance": assessment["provenance"],
        }
    ]
    try:
        validate_operation_exchange(
            contracts["Recommendations.propose"],
            json.dumps(recommendations["request"], ensure_ascii=False),
            json.dumps(recommendations["response"], ensure_ascii=False),
        )
    except ValueError as exc:
        assert "cannot lower" in str(exc)
    else:
        raise AssertionError("Recommendations.propose lowered the action approval requirement")


def test_export_has_only_normative_components_and_resolvable_refs(openapi: dict) -> None:
    exported = export_component_schemas()
    assert set(exported) == set(openapi["components"]["schemas"])

    def check(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
                assert reference.removeprefix("#/components/schemas/") in exported
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    for schema in exported.values():
        check(schema)


def test_all_25_request_and_response_examples_match_openapi_and_pydantic(
    openapi: dict,
    examples: list[dict],
) -> None:
    _, contracts = load_operation_registry()
    assert {example["operation_id"] for example in examples} == set(contracts)

    # examples.json explicitly supplies shape examples, not approved semantic
    # fixtures. Two ArtifactView examples omit content despite declaring
    # availability. Zero-length TextSpan bounds remain allowed by the current
    # contract because no minimum-length semantic rule is specified.
    expected_semantic_rejections = {
        ("Cases.save", "response"): "content_json",
        ("Evaluation.evaluate", "request"): "content_json",
    }
    observed_semantic_rejections: set[tuple[str, str]] = set()

    for example in examples:
        operation_id = example["operation_id"]
        contract = contracts[operation_id]
        for kind, schema_name, payload, validate in (
            ("request", contract.descriptor.request_model, example["request"], validate_operation_request),
            ("response", contract.descriptor.response_model, example["response"], validate_operation_response),
        ):
            _component_validator(openapi, schema_name).validate(payload)
            wire_json = json.dumps(payload, ensure_ascii=False)
            try:
                validate(contract, wire_json)
            except ValidationError as exc:
                key = (operation_id, kind)
                assert key in expected_semantic_rejections, f"unexpected invalid example {key}: {exc}"
                assert expected_semantic_rejections[key] in str(exc)
                observed_semantic_rejections.add(key)

    assert observed_semantic_rejections == set(expected_semantic_rejections)


def test_implementation_parameters_one_of_is_exclusive(openapi: dict) -> None:
    branches = openapi["components"]["schemas"]["ImplementationParameters"]["oneOf"]
    valid_cases = ({"scenario": "default"}, {})
    invalid_cases = ({"scenario": "unknown"}, {"scenario": "default", "extra": True})

    for case in valid_cases:
        matches = 0
        for branch in branches:
            schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "components": openapi["components"],
                **branch,
            }
            matches += Draft202012Validator(schema).is_valid(case)
        assert matches == 1
    for case in invalid_cases:
        matches = 0
        for branch in branches:
            schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "components": openapi["components"],
                **branch,
            }
            matches += Draft202012Validator(schema).is_valid(case)
        assert matches != 1
