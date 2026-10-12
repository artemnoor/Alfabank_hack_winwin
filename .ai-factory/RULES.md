# Project Rules

- Treat `docs/specs/framework-v1/README.md` and its linked architecture,
  contracts, operation cards, and implementation plan as normative. Do not
  redesign accepted architecture or change wire semantics for implementation
  convenience.
- For a specification conflict, cite the exact document section or OpenAPI
  JSON Pointer, describe the minimum correction, and stop only the dependent
  work until the contract owner resolves it.
- Keep T01 limited to executable Pydantic v2 contracts, operation descriptors,
  schema export/conformance, semantic validation, and their tests. Do not start
  T02–T18.
- Contracts reject coercion, undeclared fields, and invented defaults. Missing,
  null, unknown, and empty are distinct where the normative schema says so.
- Keep DTO-local validation separate from checks that require trusted context,
  another owner, or persisted state. Never claim a context check passed without
  the required trusted dependency.
- Preserve the pinned T00 toolchain. Lock every added dependency; justify any
  tool not named in the approved stack by a concrete T01 requirement.
- Do not commit, push, publish, or merge unless the user separately asks.
- Do not edit `.agents/`, `.local/`, `.venv/`, `node_modules/`, or
  `skills-lock.json`; these are machine-local support state.
