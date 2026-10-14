from __future__ import annotations

import sys
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
for entry in (ROOT / "packages" / "contracts" / "src", ROOT / "spike" / "T13"):
    sys.path.insert(0, str(entry))

from experiments.run_offline import LOCAL_MATRIX, load_materialized_inputs, make_context

@pytest.fixture(scope="session")
def materialized():
    return load_materialized_inputs()

@pytest.fixture(scope="session")
def scenario_rows():
    return json.loads(LOCAL_MATRIX.read_text(encoding="utf-8"))["scenarios"]

@pytest.fixture(scope="session")
def contexts(materialized, scenario_rows):
    return {row["case_id"]: make_context(row, materialized) for row in scenario_rows}
