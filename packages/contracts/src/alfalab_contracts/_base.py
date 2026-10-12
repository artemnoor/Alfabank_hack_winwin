"""Base class for generated closed, strict OpenAPI DTOs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from .semantics import validate_dto


class OpenAPIModel(BaseModel):
    """Generated DTO base: closed objects, strict scalars, semantic checks."""

    # Primitive OpenAPI fields are generated with strict Pydantic types. Keeping
    # global strict mode off lets JSON-origin enum strings validate after an
    # HTTP framework has decoded the request body into a Python mapping.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate_contract_semantics(self) -> OpenAPIModel:
        validate_dto(self)
        return self


def validate_json(model_type: type[OpenAPIModel], data: str | bytes) -> OpenAPIModel:
    """Validate wire JSON in strict JSON mode; no permissive Python coercion."""
    return model_type.model_validate_json(data, strict=True)
