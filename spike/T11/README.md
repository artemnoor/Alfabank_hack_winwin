# T11 — Evidence trust logic spike

T11 tests how the system should reason about cited evidence. It does not implement the Evidence owner, persist records, or write through `Evidence.register`.

## Input and output

The prototype accepts a strict Framework v1 `EvidenceRecord`, an explicitly supplied immutable source snapshot, and optional hand-authored source-assertion annotations. It returns three separate layers:

1. **Anchor integrity** — whether the exact source identity, revision, whole-source hash, and locator match the materialized source.
2. **Source assertion** — what the supplied annotation says that source states about a named claim. T11 does not extract or infer this relation from prose.
3. **Claim status** — `supported_unconfirmed`, `disputed`, `historical`, `unverified`, or `unknown`, based on the usable annotations and their time scope.

`verified` anchor means only that the quoted text is present in the supplied immutable snapshot. It does not establish that the publisher is truthful, that the claim is true, or that a company is exposed. The prototype never emits `confirmed`; a separate function can report that the exact code-pinned, provisional synthetic test policy permits owner review.

Historical assessments take independent `valid_as_of` and `known_as_of` cutoffs. `published_at` is checked against valid time; `collected_at` and, when present, `recorded_at` are checked against knowledge time. A missing or malformed registration timestamp makes that observation inapplicable. Owner-policy review rechecks the time slice against the current materialized source fields.

Repeated evidence is grouped by `publisher_root_id`. Ten outlets that share one source root count as one root. No source reliability score is calculated, and source reliability fields do not promote claims.

## Run

From the repository root, using the pinned Python environment:

```powershell
$env:PYTHONPATH='C:\CodexData\worktrees\alfabank-spike-t11-evidence\packages\contracts\src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest spike/T11/tests -p no:cacheprovider -q
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T11/experiments/run_offline.py
Remove-Item Env:\PYTHONPATH
```

The demo verifies canonical hashes for its pinned inputs and prints one JSON result per shared T11 property case. It makes no network or model calls and writes no data.

The experiment is pinned to `t09-t13-independent-v1` version `1.0.1`, canonical SHA-256 `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`. Its hand-authored case fixture is provisional and has canonical content hash `sha256:f0ed002a48a9da59baa9b56d9b47e147cbd5de344cfca3621debb4ac4b4de2d4`. Neither is an approved gold dataset.

## Current state

- Engineering checks: 53 offline tests pass, including strict Evidence.read exchange validation, Evidence.register input DTO shape validation, and bitemporal/policy-pin regressions.
- Algorithm quality: **PRELIMINARY** — only synthetic, hand-authored cases were used.
- Live model quality: **NOT MEASURED** — no model was invoked.
- Integration readiness: **NOT READY** — this is a trust-logic experiment, not an Evidence owner implementation or production policy.

See [PLAN.md](PLAN.md), [TEST_REPORT.md](TEST_REPORT.md), [RESEARCH.md](RESEARCH.md), and [LIMITATIONS.md](LIMITATIONS.md).
