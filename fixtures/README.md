# Approved fixture data

`approved/` contains small, local-only synthetic datasets and operation cases. No live cassettes, external source records, secrets, or real company identifiers belong here.

The two versioned datasets, `radio-export-v1` and `steel-buffer-v1`, are synthetic state/input sets. The radio dataset includes repeated and contradictory reports; the steel dataset keeps buffer quantities unknown and labels its mitigation as hypothetical. Dataset manifests pin their data-file hashes. Every operation case pins the T01 operation schema hash, strict request model, trusted server scope, analytical time, seed, state references, and hashes of its request and expected-result rules.

Each operation has a shape-valid deterministic baseline request, an empty scenario, a schema-rejection case, and a controlled safe-failure case. Commands also have duplicate-key, changed-payload conflict, and restored-state cases. Reads have missing-object and foreign-sandbox cases. `expected_result` records contract and invariant checks; its `output_hash_rule` defines how to hash an actual response. The current fixtures do not approve algorithm-quality gold outputs. The hash in `hashes.expected_result` pins the expectation rules, not an algorithm response.

## Validate and update hashes

Run the validator with the pinned project environment:

```powershell
uv run --locked python fixtures/validate.py
```

When an approved fixture is deliberately changed after review, update its internal canonical hashes and regenerate the index with `--reindex`, then rerun validation:

```powershell
uv run --locked python fixtures/validate.py --reindex
uv run --locked python fixtures/validate.py
```

`--reindex` only refreshes byte hashes and the operation-registry fingerprint. It does not approve content or quality expectations. Fixture content changes still require code review and a new dataset/fixture version when the data itself changes.

`canonical-json-v1` means UTF-8 JSON serialized with recursively sorted object keys, compact separators, preserved array order, Unicode emitted directly, and non-finite numbers rejected. Request hashes cover the complete wire request. Deterministic input hashes additionally cover the trusted principal/scope, referenced before-state, analytical time, and seed. Output hashes cover the declared response scope after the listed JSON Pointer exclusions.
