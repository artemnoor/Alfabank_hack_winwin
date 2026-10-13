from __future__ import annotations

import ast
from pathlib import Path

IMPLEMENTATIONS = Path(__file__).parents[2] / "apps/api/src/alfalab/modules"
FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "httpx",
    "requests",
    "socket",
}
FORBIDDEN_IMPORTS = {
    "http.client",
    "alfalab.common.artifacts",
    "alfalab.execution.gateway",
    "alfalab.modules.runs.storage",
}
FORBIDDEN_IMPORTED_NAMES = {
    "ArtifactStore",
    "ControlledDependencyGateway",
    "PostgresRunsRepository",
    "RunsRepository",
}


def test_operation_implementations_cannot_bypass_effect_ports() -> None:
    violations: list[str] = []
    for source in sorted(IMPLEMENTATIONS.glob("*/implementations/**/*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
                imported_names = []
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                imported_names = [alias.name for alias in node.names]
            else:
                if isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name) and node.func.id == "__import__"
                ):
                    violations.append(f"{source}: dynamic import")
                continue

            for module in modules:
                root = module.partition(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS or module in FORBIDDEN_IMPORTS:
                    violations.append(f"{source}: forbidden import {module}")
            for name in imported_names:
                if name in FORBIDDEN_IMPORTED_NAMES:
                    violations.append(f"{source}: forbidden imported name {name}")

    assert not violations, "\n".join(violations)
