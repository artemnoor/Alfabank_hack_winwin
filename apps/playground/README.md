# Documents.prepare workbench

This React/TypeScript/Vite workbench loads the local API catalog and runtime OpenAPI document, validates the JSON request against the advertised T01 schema, and validates the success response against the corresponding schema. Its request example comes from the normative examples file and is labeled as a synthetic schema example, not an expected algorithm result.

The UI accepts loopback API addresses only (`localhost`, `127.0.0.1`, or `::1`). It sends requests only after the user presses **Run prepare**. The bearer token remains in tab memory; it is not written to browser storage. API errors display only the server's safe message and field paths.

Start the API first using [the API instructions](../api/README.md), then run from the repository root in PowerShell:

```powershell
$node = (Resolve-Path .local/toolchain/node/node-22.23.3-windows-x64/node-v22.23.3-win-x64).Path
$env:PATH = "$node;$env:PATH"
& "$node/npm.cmd" ci --prefix apps/playground
& "$node/npm.cmd" --prefix apps/playground run dev
```

Open `http://127.0.0.1:5173`, enter the server's developer token, and load the API schema. The application does not store the token after the tab closes.

The pinned frontend checks are:

```powershell
& "$node/npm.cmd" --prefix apps/playground run typecheck
& "$node/npm.cmd" --prefix apps/playground test
& "$node/npm.cmd" --prefix apps/playground run build
```

`build` regenerates the TypeScript API types from `docs/specs/framework-v1/contracts/openapi.json` before bundling.
