from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "docs/specs/framework-v1/contracts"


@pytest.fixture(scope="session")
def openapi() -> dict:
    return json.loads((CONTRACTS / "openapi.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def examples() -> list[dict]:
    content = json.loads((CONTRACTS / "examples.json").read_text(encoding="utf-8"))
    return content["examples"]
