# Shared T09–T13 provisional fixtures

Dataset: `t09-t13-independent-v1` version `1.0.1`.

The dataset is synthetic and provisional; it is not an approved or gold dataset. It is independent of T08 and of T09–T13 implementations. All five materialized operation fixtures are prepared offline, validated strictly with the repository's pinned Pydantic v2 contracts, and do not call a model, network service, database, or module implementation.

## Contents

- `datasets/t09-t13-independent-v1/data.json` — companies, documents, evidence, profiles, event catalog, graph, and 100+ hand-authored property cases.
- `datasets/t09-t13-independent-v1/manifest.json` — version, source refs, hashes, status, inputs, expectations, and limitations.
- `fixtures/t09-t13-independent-v1/` — prepared request/response payloads for `Understanding.extract`, `Events.read`, `Business.read`, `Evidence.read`, and `Graph.query`.
- `contracts/t09-t13-independent-v1/` — frozen operation closures, OpenAPI component snapshot, immutable approved-fixture pointers, synthetic test-owner policy, and gap report.
- `validation/validate.py` — offline checks using standard-library hashes, source refs, provenance, and the existing pinned Pydantic package.

## Offline validation

Run from repository root with the existing pinned Python environment (Python 3.12 and the workspace's Pydantic v2 installation):

```powershell
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
```

The validator reads the contract package and approved fixtures from this checkout. It does not access a database or network. No environment file, `.venv`, or global contract is changed. Generated text/JSON artifact hashes use LF-normalized bytes; the dataset also has a separate canonical JSON hash. The read-only approved index hashes are retained verbatim alongside portable local content hashes.

## Freeze protocol

Version `1.0.1` is the active frozen provisional corpus. It supersedes the historically preserved `1.0.0` snapshot from commit `db48cd37491e8fab8a9f122ae4b100da72197a81`, whose artifact SHA checks depended on Windows checkout line endings and whose T12 inferred case did not resolve to an executable graph input. The physical dataset ID path is retained to avoid duplicating the large corpus; Git history preserves the previous files. Future changes require a new semantic version and a separately reviewed freeze. The builder refuses to overwrite by default; its only correction mode is `--supersede 1.0.0`, which first verifies that exact predecessor version.

The dataset's canonical SHA-256 is `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`. Base commit: `ce640214be7c5ff2fdb451b9e290135a11b512a6`. The source PDF was reviewed at pages 4–9 and is pinned by SHA-256 in the dataset manifest.

## Scope and limitations

The corpus tests false merges, sparse profiles, source conflicts, exact-anchor integrity, time-bounded facts, open-world graph paths, stale/partial knowledge, and impact questions with unknowns. It contains no real company data and no model output is used to make labels. The property expectations are provisional and require independent content review before any gold use.

Publisher-root/syndication groups, the explicit test-only confirmed policy, and the T12 negative-edge semantics live only in local experimental metadata because normative DTOs do not carry those semantics; see `contracts/t09-t13-independent-v1/COMPATIBILITY_GAPS.md`. Confirmed synthetic examples do not imply a universal reliability score or production trusted-owner policy.
