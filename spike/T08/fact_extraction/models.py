"""Strict private schema for extraction-only model output.

The provider never writes OpenAPI DTOs directly. This small schema is validated,
anchored to exact prepared-text quotes, and then mapped to the existing
``ExtractionOutput`` contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FactClaim(_StrictModel):
    value: StrictStr = Field(min_length=1, max_length=1000)
    quote: StrictStr = Field(min_length=1, max_length=3000)


class ParticipantClaim(_StrictModel):
    value: StrictStr = Field(min_length=1, max_length=300)
    quote: StrictStr = Field(min_length=1, max_length=3000)
    role: Literal["actor", "affected", "other"]
    kind: Literal["organization", "person", "place", "government", "group", "unknown"]


class ExtractedMention(_StrictModel):
    """One occurrence aligned to a preselected Jev code, without code selection."""

    event: FactClaim
    assertion_status: Literal[
        "reported", "rumored", "planned", "denied", "negated", "disputed", "unknown"
    ]
    status_quote: StrictStr = Field(min_length=1, max_length=3000)
    company: FactClaim | None
    company_role: (
        Literal["subject", "actor", "affected", "reporter", "mentioned", "unknown"]
        | None
    ) = None
    date: FactClaim | None
    location: FactClaim | None
    participants: list[ParticipantClaim] = Field(max_length=50)
    circumstances: list[FactClaim] = Field(max_length=50)


class ModelExtraction(_StrictModel):
    mentions: list[ExtractedMention] = Field(max_length=100)
