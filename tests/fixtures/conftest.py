from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = REPO_ROOT / "apps" / "api" / "src"
for source in (REPO_ROOT, API_SOURCE):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
