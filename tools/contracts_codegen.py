"""Generate executable Pydantic contracts from the normative OpenAPI file."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "docs/specs/framework-v1/contracts/openapi.json"
PACKAGE = ROOT / "packages/contracts/src/alfalab_contracts"
GENERATED = PACKAGE / "_generated.py"
MODELS = PACKAGE / "models.py"
CODEGEN_VERSION = "0.83.0"


def _pascalize_component(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


def _bound_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            names.add(node.name.id)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return names


def generate() -> tuple[str, str]:
    try:
        installed = version("datamodel-code-generator")
    except PackageNotFoundError as exc:
        raise SystemExit("Install T01 development dependencies with `uv sync --all-groups`.") from exc
    if installed != CODEGEN_VERSION:
        raise SystemExit(f"Expected datamodel-code-generator {CODEGEN_VERSION}, found {installed}.")

    openapi = json.loads(OPENAPI.read_text(encoding="utf-8"))
    component_names = sorted(openapi["components"]["schemas"])

    with tempfile.TemporaryDirectory(prefix="alfalab-contracts-") as directory:
        output = Path(directory) / "_generated.py"
        command = [
            "datamodel-codegen",
            "--input", str(OPENAPI),
            "--input-file-type", "openapi",
            "--output", str(output),
            "--output-model-type", "pydantic_v2.BaseModel",
            "--base-class", "alfalab_contracts._base.OpenAPIModel",
            "--target-python-version", "3.12",
            "--target-pydantic-version", "2.12",
            "--extra-fields", "forbid",
            "--strict-types", "str", "int", "float", "bool",
            "--type-overrides", json.dumps({"Timestamp": "alfalab_contracts._types.Timestamp"}),
            "--use-type-alias-type",
            "--use-union-operator",
            "--use-standard-collections",
            "--use-exact-imports",
            "--strict-refs",
            "--strict-nullable",
            "--use-schema-description",
            "--disable-timestamp",
            "--formatters", "builtin",
        ]
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        if completed.returncode:
            raise SystemExit(
                "Pydantic generation failed:\n"
                + completed.stdout
                + completed.stderr
            )
        source = output.read_text(encoding="utf-8")

    # datamodel-code-generator 0.83.0 emits the nested Match.edge_paths item
    # schema as a plain list alias and drops its normative maxItems=5. Keep the
    # generated alias constrained; conformance tests fail if this drifts.
    nested_array_alias = "type EdgePath = list[Identifier]"
    if source.count(nested_array_alias) != 1:
        raise SystemExit("Expected exactly one generated EdgePath alias; review the OpenAPI/codegen change.")
    source = source.replace(
        nested_array_alias,
        "type EdgePath = Annotated[list[Identifier], Field(min_length=0, max_length=5)]",
    )

    bound = _bound_names(source)
    aliases: list[str] = []
    for component_name in component_names:
        if component_name in bound:
            continue
        generated_name = _pascalize_component(component_name)
        if generated_name not in bound:
            raise SystemExit(
                f"OpenAPI component {component_name!r} has no generated type; "
                f"expected {generated_name!r}."
            )
        aliases.append(f"{component_name} = {generated_name}")
    source = source.rstrip() + "\n\n# Stable aliases preserve exact OpenAPI component identifiers.\n"
    source += "\n".join(aliases) + "\n"

    names_block = "\n".join(f"    {name!r}," for name in component_names)
    models_source = (
        '"""Public component-name map generated from the normative OpenAPI snapshot."""\n\n'
        "from __future__ import annotations\n\n"
        "from . import _generated\n\n"
        "SCHEMA_NAMES = (\n"
        f"{names_block}\n"
        ")\n"
        "SCHEMA_TYPES = {name: getattr(_generated, name) for name in SCHEMA_NAMES}\n"
        "__all__ = [*SCHEMA_NAMES, \"SCHEMA_NAMES\", \"SCHEMA_TYPES\"]\n\n"
        "def __getattr__(name: str):\n"
        "    try:\n"
        "        return SCHEMA_TYPES[name]\n"
        "    except KeyError as exc:\n"
        "        raise AttributeError(name) from exc\n"
    )
    return source, models_source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if committed generated files are stale")
    args = parser.parse_args()
    generated_source, models_source = generate()
    expected = {GENERATED: generated_source, MODELS: models_source}
    stale = []
    for path, source in expected.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != source:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.write_text(source, encoding="utf-8", newline="\n")
            print(f"generated {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("generated contract files are stale: " + ", ".join(stale), file=sys.stderr)
        print("run `uv run python tools/contracts_codegen.py` and review the diff", file=sys.stderr)
        return 1
    if args.check:
        print("generated Pydantic contracts match OpenAPI and pinned generator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
