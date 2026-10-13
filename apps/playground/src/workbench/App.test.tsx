import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import normativeOpenApi from "../../../../docs/specs/framework-v1/contracts/openapi.json";
import examples from "../../../../docs/specs/framework-v1/contracts/examples.json";
import operationRegistry from "../../../../docs/specs/framework-v1/contracts/operations.json";
import type { components } from "../api/openapi";
import { App } from "./App";

type Catalog = components["schemas"]["CatalogOutput"];
type ErrorResponse = components["schemas"]["ErrorResponse"];
type PrepareResponse = components["schemas"]["Documents_prepareResponse"];
type OperationDescriptor = components["schemas"]["OperationDescriptor"];

const implementation: components["schemas"]["ImplementationDescriptor"] = {
  id: "mock.baseline",
  version: "1.0.0",
  kind: "mock",
  available: true,
  reason: null,
  parameter_schema_id: "MockParameters",
  capabilities: ["deterministic", "span_mapping"],
  environments: ["development", "testing"],
};

const operations: OperationDescriptor[] = operationRegistry.operations.map((entry) => ({
  operation_id: entry.operation_id,
  contract_version: entry.contract_version,
  path: entry.path,
  method: "POST",
  kind: entry.kind as OperationDescriptor["kind"],
  request_schema_id: entry.request_model,
  response_schema_id: entry.response_model,
  implementations: [
    "Sources.fetch",
    "Documents.prepare",
    "Documents.register",
    "Documents.read",
    "Runs.query",
  ].includes(entry.operation_id) ? [implementation] : [],
  effects: [],
  replay_profile: entry.replay_profile as OperationDescriptor["replay_profile"],
}));

const catalog: Catalog = {
  operations,
  environment: "testing",
  allowed_sandboxes: ["demo-a"],
  build_hash: `sha256:${"a".repeat(64)}`,
  readiness_report_hash: null,
};

const exampleResponse = examples.examples.find(
  (example) => example.operation_id === "Documents.prepare",
)?.response as PrepareResponse;
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(operationResponse: Response = jsonResponse(exampleResponse)) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/system/catalog")) return jsonResponse(catalog);
    if (url.endsWith("/openapi.json")) return jsonResponse(normativeOpenApi);
    if (url.endsWith("/api/v1/documents/prepare")) return operationResponse;
    const descriptor = operationRegistry.operations.find((entry) => url.endsWith(entry.path));
    if (descriptor) {
      const response = examples.examples.find(
        (example) => example.operation_id === descriptor.operation_id,
      )?.response;
      return jsonResponse(response ?? {});
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function connect(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Developer token/), "local-token");
  await user.click(screen.getByRole("button", { name: "Load API schema" }));
  await screen.findByText(/Connected\./);
}

describe("operation workbench", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    cleanup();
  });

  it("loads catalog and OpenAPI, then sends a schema-checked local request", async () => {
    const fetchMock = installFetch();
    const user = userEvent.setup();
    render(<App />);
    await connect(user);

    await user.click(screen.getByRole("button", { name: "Run operation" }));

    expect(await screen.findByText(/Documents\.prepare completed\./)).toBeInTheDocument();
    expect(screen.getByText(/"run_id": "example-run-2"/)).toBeInTheDocument();
    const operationCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/v1/documents/prepare"),
    );
    expect(operationCall).toBeDefined();
    expect(operationCall?.[1]?.method).toBe("POST");
    expect(String(operationCall?.[1]?.body)).toContain('"request_id":"example-2"');
  });

  it("selects Runs.query in the same workbench and sends its schema-checked request", async () => {
    const fetchMock = installFetch();
    const user = userEvent.setup();
    render(<App />);
    await connect(user);
    await user.selectOptions(screen.getByLabelText("Operation"), "Runs.query");
    await user.click(screen.getByRole("button", { name: "Run operation" }));

    expect(await screen.findByText(/Runs\.query completed\./)).toBeInTheDocument();
    expect(screen.getByText(/"operation_id": "Runs.query"/)).toBeInTheDocument();
    const operationCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/v1/runs/query"),
    );
    expect(operationCall?.[1]?.method).toBe("POST");
    expect(String(operationCall?.[1]?.body)).toContain('"include_artifacts":false');
  });

  it("selects Sources.fetch and Documents.register from the runtime catalog", async () => {
    const fetchMock = installFetch();
    const user = userEvent.setup();
    render(<App />);
    await connect(user);

    await user.selectOptions(screen.getByLabelText("Operation"), "Sources.fetch");
    await user.click(screen.getByRole("button", { name: "Run operation" }));
    expect(await screen.findByText(/Sources\.fetch completed\./)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/v1/sources/fetch")),
    ).toBe(true);

    await user.selectOptions(screen.getByLabelText("Operation"), "Documents.register");
    await user.click(screen.getByRole("button", { name: "Run operation" }));
    expect(await screen.findByText(/Documents\.register completed\./)).toBeInTheDocument();
    const registerCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/v1/documents/register"),
    );
    expect(registerCall?.[1]?.method).toBe("POST");
    expect(String(registerCall?.[1]?.body)).toContain('"expected_revision":0');
  });

  it("loads and schema-validates Run History without changing the selected operation", async () => {
    const fetchMock = installFetch();
    const user = userEvent.setup();
    render(<App />);
    await connect(user);
    await user.click(screen.getByRole("button", { name: "Load recent history" }));

    expect(await screen.findByText(/"operation_id": "Runs.query"/)).toBeInTheDocument();
    expect(screen.getByLabelText("Operation")).toHaveValue("Documents.prepare");
    const queryCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/v1/runs/query"),
    );
    expect(queryCall?.[1]?.method).toBe("POST");
    expect(String(queryCall?.[1]?.body)).toContain('"include_artifacts":false');
  });

  it("focuses the editor and connects an inline error for invalid JSON", async () => {
    installFetch();
    const user = userEvent.setup();
    render(<App />);
    await connect(user);

    const editor = screen.getByLabelText("Complete typed request");
    fireEvent.change(editor, { target: { value: "{not json}" } });
    await user.click(screen.getByRole("button", { name: "Run operation" }));

    expect(editor).toHaveFocus();
    expect(editor).toHaveAttribute("aria-invalid", "true");
    expect(editor).toHaveAttribute("aria-describedby", "request-error");
    expect(screen.getByText("This is not valid JSON. Correct the syntax and try again.")).toBeInTheDocument();
  });

  it("focuses the editor when valid JSON fails the loaded request schema", async () => {
    installFetch();
    const user = userEvent.setup();
    render(<App />);
    await connect(user);

    const editor = screen.getByLabelText("Complete typed request");
    fireEvent.change(editor, { target: { value: "{}" } });
    await user.click(screen.getByRole("button", { name: "Run operation" }));

    expect(editor).toHaveFocus();
    expect(editor).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("The JSON does not match the Documents.prepare request schema.")).toBeInTheDocument();
  });

  it("renders only the API safe message and field paths on failure", async () => {
    const error: ErrorResponse = {
      meta: null,
      error: {
        code: "INVALID_INPUT",
        category: "validation",
        retryable: false,
        safe_message: "The request does not satisfy the operation contract.",
        field_paths: ["payload.material.content_hash"],
        dependency_id: null,
        outcome: "not_applied",
      },
    };
    installFetch(jsonResponse(error, 422));
    const user = userEvent.setup();
    render(<App />);
    await connect(user);
    await user.click(screen.getByRole("button", { name: "Run operation" }));

    expect(await screen.findByText(/payload\.material\.content_hash/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("safe API error"));
    expect(screen.queryByText(/content hash.*sha256/i)).not.toBeInTheDocument();
  });

  it("does not send the token or request to a non-loopback address", async () => {
    const fetchMock = installFetch();
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByLabelText("API address"), "https://example.com");
    await user.type(screen.getByLabelText(/Developer token/), "local-token");
    await user.click(screen.getByRole("button", { name: "Load API schema" }));

    expect(screen.getByRole("status")).toHaveTextContent("Use a local API address");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
