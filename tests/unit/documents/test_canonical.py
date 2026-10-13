from __future__ import annotations

import pytest
from pydantic import BaseModel

from alfalab.modules.documents.storage.canonical import canonical_hash, canonical_json_bytes


class _CanonicalPayload(BaseModel):
    revision: int
    title: str


def test_canonical_json_and_hash_are_shared_across_mappings_and_models() -> None:
    mapping = {"title": "Альфа", "revision": 1}
    model = _CanonicalPayload(revision=1, title="Альфа")

    assert canonical_json_bytes(mapping) == canonical_json_bytes(model)
    assert canonical_hash(mapping) == canonical_hash(model)
    assert canonical_json_bytes(mapping) == '{"revision":1,"title":"Альфа"}'.encode("utf-8")


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})
