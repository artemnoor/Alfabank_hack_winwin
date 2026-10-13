# Local API slice

The T03 API and JSON CLI expose the typed `Documents.prepare` operation through the same execution runtime, registry, and `ExecutionService.invoke`. They have real and baseline mock implementations. Runs and spans are kept only in a bounded process-local metadata writer; request content is not retained, and replay is reported as unavailable.

Start from the repository root in PowerShell after bootstrapping the pinned toolchain:

```powershell
$env:ALFALAB_ENVIRONMENT = "development"
$env:ALFALAB_DEV_TOKEN = "local-development-token"
& .local/toolchain/bin/uv.exe run --locked --python .local/toolchain/python/cpython-3.12.15-windows-x86_64-none/python.exe uvicorn alfalab.bootstrap.app:app --app-dir apps/api/src --host 127.0.0.1 --port 8000
```

The token is configured in the server environment and entered into the Playground in memory. The local developer profile can be adjusted with `ALFALAB_ACTOR_ID`, `ALFALAB_TENANT_ID`, `ALFALAB_ALLOWED_SANDBOXES`, and `ALFALAB_PLAYGROUND_ORIGINS`. Production mode is deliberately unavailable in this slice.

The CLI is for trusted local processes. It derives the same developer principal and sandbox allowlist from the local environment; the JSON request cannot grant access. Pass one full `Documents.prepare` request DTO as a UTF-8 JSON file, or omit `--request` to read it from standard input:

```powershell
& .local/toolchain/bin/uv.exe run --locked --python .local/toolchain/python/cpython-3.12.15-windows-x86_64-none/python.exe python -m alfalab.cli prepare --request .\prepare-request.json
```

The CLI writes successful JSON response envelopes to standard output and sanitized error envelopes to standard error. It uses the same safe error schema, measured execution metadata, sandbox check, and request DTO validation as HTTP. A successful shell status is zero; validation failures use status 2; execution failures use status 1.

Check `/health/live`, `/health/ready`, `/system/catalog` (bearer token required), and `/openapi.json`. The runtime OpenAPI document advertises only implemented operation routes. Other operation descriptors remain unavailable.

The tests run with the pinned Python environment:

```powershell
& .local/toolchain/bin/uv.exe run --locked --python .local/toolchain/python/cpython-3.12.15-windows-x86_64-none/python.exe pytest tests/api -q
```
