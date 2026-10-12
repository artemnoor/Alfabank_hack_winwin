# Executable contracts

`alfalab-contracts` contains the strict Pydantic v2 models generated from the
normative OpenAPI 3.1 snapshot in `docs/specs/framework-v1/contracts/openapi.json`.
The generated module and the exact-name component map are committed so runtime
users do not need the code generator. Pydantic is the only runtime dependency.

## Install and verify

Run T00 bootstrap first, then synchronize the locked Python environment and run
the T01 checks.

PowerShell:

```powershell
& .local/toolchain/bin/uv.exe sync --all-groups --locked --python 3.12.15
& .local/toolchain/bin/uv.exe run --locked --python 3.12.15 python tools/contracts_codegen.py --check
& .local/toolchain/bin/uv.exe run --locked --python 3.12.15 pytest tests/contracts -q
```

Linux / WSL:

```sh
.local/toolchain/bin/uv sync --all-groups --locked --python 3.12.15
.local/toolchain/bin/uv run --locked --python 3.12.15 python tools/contracts_codegen.py --check
.local/toolchain/bin/uv run --locked --python 3.12.15 pytest tests/contracts -q
```

`contracts_codegen.py` requires the exact locked `datamodel-code-generator`
version and fails when committed generated files differ from the normative
OpenAPI snapshot. `pytest` checks all 215 component schemas, 25 operation
bindings, all 50 request/response examples, strict validation, and DTO-local
semantic rules. No PostgreSQL, model SDK, API key, or network service is needed
for T01 checks after the lock dependencies are installed.

## Public Python surface

`SCHEMA_NAMES` and `SCHEMA_TYPES` map all normative OpenAPI component names to
their executable Pydantic model or type alias. The original OpenAPI names,
including names with underscores, are preserved as package attributes.

```python
from alfalab_contracts import SCHEMA_TYPES
from alfalab_contracts.registry import load_operation_registry

registry, contracts = load_operation_registry()
request_type = contracts["Sources.fetch"].request_type
request = request_type.model_validate_json(wire_json, strict=True)
```

`validate_operation_request`, `validate_operation_response`, and
`validate_schema_json` are strict wire-JSON helpers. Strings do not become
numbers, booleans do not become numbers, non-finite values are rejected, and
OpenAPI `number` fields continue to accept JSON integer tokens. Enum strings
work both from raw JSON and from a JSON-decoded mapping. Object models reject
undeclared properties. `validate_operation_exchange` validates both envelopes
and dispatches the cross-payload invariants for operations that define them.

## Validation boundary

Pydantic runs only checks decidable from the supplied typed values. The package
also exposes explicit pair validators for `Documents.prepare`, event
resolution, business profile proposals, matching, impact, recommendations,
and evaluation. Scope and hash
resolution, source trust, producer-run lookup, registered
ontology/calibration policies, immutable aggregate membership, and
artifact-schema lookup require trusted context or owner ports and are not
asserted by standalone DTO parsing. A `confirmed` Statement must carry at least
one ObjectRef owned by Evidence. DTO parsing does not resolve the ID/hash or
prove the fact. The Events/Business owner must resolve the reference through
the Evidence port, check scope/hash/anchor, then require an explicitly allowing
owner policy before persisting `confirmed`; otherwise the status remains
`unknown`/unverified. Anchor verification does not prove truth, and no universal
source-reliability threshold is defined. TextSpan bounds
must be ordered, while an empty `[n,n)` range remains accepted because the
normative contract does not currently forbid it. Unknown references or origins
must never be treated as verified.

Matching and Impact verify that every declared path uses edges in the supplied
graph and that consecutive edges share a node. The specification does not say
whether traversal follows edge direction, so this layer checks topology without
imposing direction. Impact's `none_found` → neutral/no-risk behavior cannot be
proven from DTO shape alone; the operation-level no-path fixture and algorithm
trace must verify that invariant in the later analytics task.

The only generated-code adaptation is the nested `Match.edge_paths` item bound
(`maxItems=5`), which generator 0.83.0 otherwise drops. Schema-conformance tests
fail if this or any other normative limit is lost. The non-discriminated
`ImplementationParameters` union is exported as `oneOf`; the two closed models
have disjoint shapes and are tested branch-by-branch.
