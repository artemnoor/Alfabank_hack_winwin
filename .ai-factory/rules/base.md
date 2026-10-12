# Base Rules

- Follow the established package and module boundaries; contracts may depend
  only on the standard library and Pydantic.
- Keep normative OpenAPI as the input snapshot for initial model generation.
  Exported Pydantic schemas must pass a semantic conformance check against it.
- Use typed public APIs; avoid unvalidated dictionaries at operation boundaries.
- Add focused positive and negative tests for each contract behavior introduced.
- Run commands with the repository-pinned toolchain and report only checks that
  were actually executed.
- Keep documentation and status current, but do not edit unrelated user files.
