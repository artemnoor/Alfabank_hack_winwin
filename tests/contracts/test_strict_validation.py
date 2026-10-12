from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from alfalab_contracts import SCHEMA_TYPES
from alfalab_contracts.registry import load_operation_registry, validate_operation_request, validate_schema_json


def _example(examples: list[dict], operation_id: str) -> dict:
    return next(example for example in examples if example["operation_id"] == operation_id)


def test_request_rejects_extra_fields_and_numeric_coercion(examples: list[dict]) -> None:
    _, contracts = load_operation_registry()
    contract = contracts["Sources.fetch"]
    request = _example(examples, "Sources.fetch")["request"]

    extra = deepcopy(request)
    extra["internal_mode"] = "production"
    with pytest.raises(ValidationError):
        validate_operation_request(contract, json.dumps(extra))

    for invalid_limit in ("1", True, 0, 101):
        invalid = deepcopy(request)
        invalid["payload"]["limit"] = invalid_limit
        with pytest.raises(ValidationError):
            validate_operation_request(contract, json.dumps(invalid))

    # HTTP frameworks may pass a JSON-decoded dict rather than raw bytes. Enum
    # strings remain valid while strict scalar fields still reject coercion.
    decoded = contract.request_type.model_validate(request)
    assert decoded.payload.limit == 1
    with pytest.raises(ValidationError):
        contract.request_type.model_validate({**request, "payload": {**request["payload"], "limit": "1"}})


def test_required_nullable_is_distinct_from_omitted(examples: list[dict]) -> None:
    _, contracts = load_operation_registry()
    contract = contracts["Sources.fetch"]
    request = deepcopy(_example(examples, "Sources.fetch")["request"])

    del request["payload"]["cursor"]
    with pytest.raises(ValidationError):
        validate_operation_request(contract, json.dumps(request))

    request = deepcopy(_example(examples, "Sources.fetch")["request"])
    request["payload"]["cursor"] = None
    assert validate_operation_request(contract, json.dumps(request)).payload.cursor is None


def test_enum_and_identifier_constraints_are_strict() -> None:
    assert validate_schema_json("Identifier", '"news:source-1"') == "news:source-1"
    for value in ('""', '"with spaces"', '1', 'true'):
        with pytest.raises(ValidationError):
            validate_schema_json("Identifier", value)

    typed_value = validate_schema_json("TypedValue", '{"kind":"text","value":"unknown stays explicit"}')
    assert str(typed_value.kind) == "text"
    with pytest.raises(ValidationError):
        validate_schema_json("TypedValue", '{"kind":"sentiment","value":"positive"}')


def test_discriminated_unions_reject_unknown_discriminator_and_extra_properties() -> None:
    validate_schema_json("TypedValue", '{"kind":"unknown","reason":"not provided"}')
    with pytest.raises(ValidationError):
        validate_schema_json("TypedValue", '{"kind":"unknown","reason":"not provided","value":null}')
    with pytest.raises(ValidationError):
        validate_schema_json("ExecutionOptions", '{"mode":"batch","recording":"full"}')


def test_non_discriminated_one_of_accepts_each_declared_branch_once() -> None:
    parameters = SCHEMA_TYPES["ImplementationParameters"]
    mock = TypeAdapter(parameters).validate_json('{"scenario":"default"}', strict=True)
    real = TypeAdapter(parameters).validate_json("{}", strict=True)
    assert mock.scenario.value == "default"
    assert type(real).__name__ == "RealPrepareParameters"

    for invalid in ('{"scenario":"unknown"}', '{"scenario":"default","other":1}'):
        with pytest.raises(ValidationError):
            TypeAdapter(parameters).validate_json(invalid, strict=True)


def test_timestamp_is_wire_string_with_valid_utc_rfc3339() -> None:
    assert validate_schema_json("Timestamp", '"2026-10-12T00:00:00Z"') == "2026-10-12T00:00:00Z"
    assert validate_schema_json("Timestamp", '"2026-10-12T03:00:00+00:00"') == "2026-10-12T03:00:00+00:00"
    for invalid in (
        '"2026-10-12T00:00:00+03:00"',
        '"2026-02-30T00:00:00Z"',
        '"2026-10-12"',
        '1700000000',
    ):
        with pytest.raises(ValidationError):
            validate_schema_json("Timestamp", invalid)


def test_float_constraints_reject_bool_string_and_non_finite_values() -> None:
    topic_score = SCHEMA_TYPES["TopicScore"]
    valid = {
        "code": {"namespace": "topics", "version": "1.0.0", "code": "trade"},
        "raw_score": 1,
        "score_method": {"id": "raw-score", "version": "1.0.0", "hash": "sha256:" + "a" * 64},
        "calibrated": False,
    }
    parsed = topic_score.model_validate_json(json.dumps(valid), strict=True)
    assert parsed.raw_score == 1.0
    assert isinstance(parsed.raw_score, float)

    for raw_score in ("0.5", True, 1.01):
        invalid = {**valid, "raw_score": raw_score}
        with pytest.raises(ValidationError):
            topic_score.model_validate_json(json.dumps(invalid), strict=True)
    with pytest.raises(ValidationError):
        topic_score.model_validate({**valid, "raw_score": float("nan")}, strict=True)
