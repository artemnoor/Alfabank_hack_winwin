import Ajv, { type AnySchema, type ValidateFunction } from "ajv";
import { useMemo, useRef, useState } from "react";
import prepareExamples from "../../../../docs/specs/framework-v1/contracts/examples.json";
import type { components, paths } from "../api/openapi";

type Catalog = components["schemas"]["CatalogOutput"];
type OperationDescriptor = components["schemas"]["OperationDescriptor"];
type PrepareRequest = components["schemas"]["Documents_prepareRequest"];
type PrepareResponse = components["schemas"]["Documents_prepareResponse"];
type PreparePost = NonNullable<paths["/api/v1/documents/prepare"]["post"]>;
type PrepareRequestFromPath = NonNullable<PreparePost["requestBody"]>["content"]["application/json"];
type PrepareResponseFromPath = PreparePost["responses"][200]["content"]["application/json"];

const OPENAPI_ID = "http://alfalab.local/runtime-openapi.json";
const prepareExample = prepareExamples.examples.find(
  (example) => example.operation_id === "Documents.prepare",
);
const initialRequest = JSON.stringify(
  { ...prepareExample?.request, sandbox_id: "demo-a" },
  null,
  2,
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function localApiUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username !== "" ||
      url.password !== "" ||
      url.search !== "" ||
      url.hash !== "" ||
      !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    ) {
      return null;
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

function responseSchemas(document: unknown): Record<string, unknown> | null {
  if (!isRecord(document) || !isRecord(document.components)) return null;
  if (!isRecord(document.components.schemas)) return null;
  return document.components.schemas;
}

function makeValidator<T>(document: unknown, schemaId: string): ValidateFunction<T> | null {
  const schemas = responseSchemas(document);
  if (!schemas || !Object.hasOwn(schemas, schemaId)) return null;
  try {
    const ajv = new Ajv({ allErrors: true, strict: false, validateFormats: false });
    ajv.addSchema(document as AnySchema, OPENAPI_ID);
    return ajv.compile<T>({ $ref: `${OPENAPI_ID}#/components/schemas/${schemaId}` });
  } catch {
    return null;
  }
}

function safeErrorMessage(value: unknown): string {
  if (!isRecord(value) || !isRecord(value.error)) {
    return "The API returned an unexpected error response.";
  }
  const message = value.error.safe_message;
  const fieldPaths = value.error.field_paths;
  if (typeof message !== "string" || message.length > 300) {
    return "The API returned an unexpected error response.";
  }
  if (Array.isArray(fieldPaths)) {
    const safePaths = fieldPaths.filter(
      (item): item is string => typeof item === "string" && item.length > 0 && item.length <= 300,
    );
    if (safePaths.length > 0) return `${message} Fields: ${safePaths.join(", ")}`;
  }
  return message;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export function App() {
  const [apiUrl, setApiUrl] = useState("http://127.0.0.1:8000");
  const [apiToken, setApiToken] = useState("");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [openApi, setOpenApi] = useState<unknown>(null);
  const [sandboxId, setSandboxId] = useState("demo-a");
  const [implementationId, setImplementationId] = useState("mock.baseline");
  const [requestText, setRequestText] = useState(initialRequest);
  const [requestError, setRequestError] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Connect to the local API to load the request schema.");
  const requestEditor = useRef<HTMLTextAreaElement>(null);

  const prepareDescriptor: OperationDescriptor | undefined = useMemo(
    () => catalog?.operations.find((operation) => operation.operation_id === "Documents.prepare"),
    [catalog],
  );
  const availableImplementations = prepareDescriptor?.implementations.filter(
    (item) => item.available,
  ) ?? [];

  function focusRequestError(message: string) {
    setRequestError(message);
    setStatus("Request needs attention before it can run.");
    requestEditor.current?.focus();
  }

  async function connectToApi(): Promise<boolean> {
    const normalizedUrl = localApiUrl(apiUrl.trim());
    if (!normalizedUrl) {
      setStatus("Use a local API address: localhost, 127.0.0.1, or ::1.");
      return false;
    }
    if (!apiToken.trim()) {
      setStatus("Enter the local developer token to load the API catalog.");
      return false;
    }

    setBusy(true);
    setStatus("Loading the local operation catalog and OpenAPI schema…");
    try {
      const headers = { Authorization: `Bearer ${apiToken}` };
      const [catalogResponse, schemaResponse] = await Promise.all([
        fetch(`${normalizedUrl}/system/catalog`, { headers, redirect: "error" }),
        fetch(`${normalizedUrl}/openapi.json`, { redirect: "error" }),
      ]);
      const [catalogBody, schemaBody] = await Promise.all([
        readJson(catalogResponse),
        readJson(schemaResponse),
      ]);
      if (!catalogResponse.ok) {
        setStatus(safeErrorMessage(catalogBody));
        return false;
      }
      if (!schemaResponse.ok || !responseSchemas(schemaBody)) {
        setStatus("The local API did not provide a usable OpenAPI schema.");
        return false;
      }

      const catalogValidator = makeValidator<Catalog>(schemaBody, "CatalogOutput");
      if (!catalogValidator || !catalogValidator(catalogBody)) {
        setStatus("The local API catalog does not match the published contract.");
        return false;
      }
      const operation = catalogBody.operations.find(
        (entry) => entry.operation_id === "Documents.prepare",
      );
      if (!operation || operation.implementations.every((implementation) => !implementation.available)) {
        setStatus("Documents.prepare has no available implementation in this API build.");
        return false;
      }

      setApiUrl(normalizedUrl);
      setCatalog(catalogBody);
      setOpenApi(schemaBody);
      const firstSandbox = catalogBody.allowed_sandboxes[0];
      if (firstSandbox) setSandboxId(firstSandbox);
      const firstImplementation = operation.implementations.find((item) => item.available);
      if (firstImplementation) setImplementationId(firstImplementation.id);
      setStatus(`Connected. ${operation.implementations.filter((item) => item.available).length} prepare implementation(s) available.`);
      return true;
    } catch {
      setStatus("Could not reach the local API. Check that it is running and try again.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  function updateRequestSelection(field: "sandbox_id" | "implementation", value: string) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(requestText);
    } catch {
      focusRequestError("Fix the JSON before changing request controls.");
      return;
    }
    if (!isRecord(parsed)) {
      focusRequestError("The request must be a JSON object.");
      return;
    }
    if (field === "sandbox_id") {
      parsed.sandbox_id = value;
      setSandboxId(value);
    } else {
      const implementation = availableImplementations.find((item) => item.id === value);
      if (!implementation) return;
      parsed.implementation = {
        id: implementation.id,
        version: implementation.version,
        parameters: implementation.kind === "mock" ? { scenario: "default" } : {},
      };
      setImplementationId(value);
    }
    setRequestText(JSON.stringify(parsed, null, 2));
    setRequestError("");
    setStatus("Request controls updated the JSON editor.");
  }

  function loadExample() {
    if (!prepareExample) {
      setStatus("No Documents.prepare example is available in the contract examples file.");
      return;
    }
    const example = JSON.parse(JSON.stringify(prepareExample.request)) as Record<string, unknown>;
    example.sandbox_id = sandboxId;
    const implementation = availableImplementations.find((item) => item.id === implementationId);
    if (implementation) {
      example.implementation = {
        id: implementation.id,
        version: implementation.version,
        parameters: implementation.kind === "mock" ? { scenario: "default" } : {},
      };
    }
    setRequestText(JSON.stringify(example, null, 2));
    setRequestError("");
    setResult("");
    setStatus("Loaded the synthetic schema example. Review the request before running it.");
  }

  async function runPrepare() {
    setResult("");
    setRequestError("");
    let body: unknown;
    try {
      body = JSON.parse(requestText);
    } catch {
      focusRequestError("This is not valid JSON. Correct the syntax and try again.");
      return;
    }
    if (!prepareDescriptor || !openApi || !catalog) {
      setStatus("Connect to the local API first so the request can be validated against its schema.");
      return;
    }
    const requestValidator = makeValidator<PrepareRequest>(openApi, prepareDescriptor.request_schema_id);
    if (!requestValidator) {
      setStatus("The request schema is missing from the loaded OpenAPI document.");
      return;
    }
    if (!requestValidator(body)) {
      focusRequestError("The JSON does not match the Documents.prepare request schema.");
      return;
    }

    const normalizedUrl = localApiUrl(apiUrl.trim());
    if (!normalizedUrl || !apiToken.trim()) {
      setStatus("Enter a local API address and developer token before running.");
      return;
    }

    setBusy(true);
    setStatus("Running Documents.prepare…");
    try {
      const response = await fetch(`${normalizedUrl}${prepareDescriptor.path}`, {
        method: prepareDescriptor.method,
        redirect: "error",
        headers: {
          Authorization: `Bearer ${apiToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body satisfies PrepareRequestFromPath),
      });
      const responseBody = await readJson(response);
      if (!response.ok) {
        const message = safeErrorMessage(responseBody);
        setResult(message);
        setStatus("The operation returned a safe API error.");
        return;
      }

      const responseValidator = makeValidator<PrepareResponse>(
        openApi,
        prepareDescriptor.response_schema_id,
      );
      if (!responseValidator || !responseValidator(responseBody)) {
        setResult("The API response did not match its published response schema.");
        setStatus("The API returned a response that could not be verified.");
        return;
      }
      const typedResponse: PrepareResponseFromPath = responseBody;
      setResult(JSON.stringify(typedResponse, null, 2));
      setStatus(`Documents.prepare completed. Run ${typedResponse.meta.run_id}.`);
    } catch {
      setResult("Could not reach the local API. Check that it is running and try again.");
      setStatus("The operation could not reach the local API.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">AlfaLab · Local developer tool</p>
          <h1>Prepare workbench</h1>
          <p className="intro">
            Validate and run <code>Documents.prepare</code> against the local API. The schema and
            operation catalog come from this API build.
          </p>
        </div>
        <span className="contract-mark">Framework v1</span>
      </header>

      <section className="connection-panel" aria-labelledby="connection-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Connection</p>
            <h2 id="connection-title">Local API</h2>
          </div>
          <button type="button" onClick={() => void connectToApi()} disabled={busy}>
            {catalog ? "Reload API schema" : "Load API schema"}
          </button>
        </div>
        <div className="connection-fields">
          <label>
            API address
            <input
              type="url"
              value={apiUrl}
              onChange={(event) => setApiUrl(event.target.value)}
              autoComplete="url"
              spellCheck={false}
            />
          </label>
          <label>
            Developer token
            <input
              type="password"
              value={apiToken}
              onChange={(event) => setApiToken(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <span className="field-note">Kept in memory for this tab only.</span>
          </label>
        </div>
      </section>

      <p className="status-line" role="status" aria-live="polite" aria-atomic="true">
        <span className={busy ? "status-dot is-busy" : "status-dot"} aria-hidden="true" />
        {status}
      </p>

      <div className="workbench-grid">
        <section className="panel request-panel" aria-labelledby="request-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Operation · POST /api/v1/documents/prepare</p>
              <h2 id="request-title">Request JSON</h2>
            </div>
            <button className="secondary-button" type="button" onClick={loadExample}>
              Load schema example
            </button>
          </div>

          <div className="request-controls">
            <label>
              Implementation
              <select
                aria-label="Implementation"
                value={implementationId}
                disabled={availableImplementations.length === 0}
                onChange={(event) => updateRequestSelection("implementation", event.target.value)}
              >
                {availableImplementations.map((implementation) => (
                  <option key={implementation.id} value={implementation.id}>
                    {implementation.id} · {implementation.kind}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Sandbox
              <select
                aria-label="Sandbox"
                value={sandboxId}
                disabled={!catalog || catalog.allowed_sandboxes.length === 0}
                onChange={(event) => updateRequestSelection("sandbox_id", event.target.value)}
              >
                {catalog?.allowed_sandboxes.map((sandbox) => (
                  <option key={sandbox} value={sandbox}>{sandbox}</option>
                ))}
                {!catalog && <option value="demo-a">demo-a</option>}
              </select>
            </label>
          </div>

          <label className="editor-label" htmlFor="request-editor">Complete typed request</label>
          <textarea
            id="request-editor"
            ref={requestEditor}
            className="json-editor"
            value={requestText}
            onChange={(event) => {
              setRequestText(event.target.value);
              if (requestError) setRequestError("");
            }}
            aria-invalid={requestError ? true : undefined}
            aria-describedby="request-error"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
          />
          <p id="request-error" className={requestError ? "editor-error" : "editor-help"}>
            {requestError || "The editor is checked against the loaded OpenAPI request schema before sending."}
          </p>
          <div className="request-actions">
            <button type="button" onClick={() => void runPrepare()} disabled={busy || !catalog}>
              {busy ? "Working…" : "Run prepare"}
            </button>
            <span className="privacy-note">Request data stays on the configured loopback API.</span>
          </div>
        </section>

        <section className="panel result-panel" aria-labelledby="result-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Verified response</p>
              <h2 id="result-title">Result</h2>
            </div>
            {result && <span className="result-badge">Local run</span>}
          </div>
          {result ? (
            <pre className="result-output" tabIndex={0}>{result}</pre>
          ) : (
            <div className="empty-result">
              <span className="empty-mark" aria-hidden="true">{`{ }`}</span>
              <p>Run the operation to inspect its typed response and measured metadata.</p>
            </div>
          )}
        </section>
      </div>
      <footer className="page-footer">
        <span>Normative request and response shapes are generated from framework-v1 OpenAPI.</span>
        <span>Developer token is never saved to browser storage.</span>
      </footer>
    </main>
  );
}
