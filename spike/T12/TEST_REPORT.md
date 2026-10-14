# T12 test report

**Run date:** 2026-10-14
**Dataset:** `t09-t13-independent-v1` v1.0.1, provisional/not gold
**Runtime:** Python 3.12.15, pinned workspace venv, existing Pydantic v2 / pytest
**Result:** 57 passed, 0 failed, 0 skipped. Coverage was not measured.

## Commands and result

From the repository root:

```powershell
$env:PYTHONPATH = 'spike/T12/src;packages/contracts/src;spike/T12/tests'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T12/tests -q --tb=short
```

Observed final output: `57 passed in 1.47s`; the final verification was run after all code and test changes. Pytest plugin auto-discovery was disabled after an unrelated plugin import raised `MemoryError`; the suite uses core pytest only. Coverage was not measured.

This run includes five independent-review regression tests:

- `test_current_required_needs_exact_required_and_current_slices_for_full_graph` rejects a full-graph `current_required` query when required/current materializations omit manifest slices, returns `unknown` for missing current slices, and accepts the exact complete slice set.
- `test_publish_rejects_grounded_references_without_manifest_slices` rejects a grounded candidate whose manifest omits all or one referenced source aggregate.
- `test_published_revision_and_receipt_readbacks_are_detached` mutates nested snapshot, receipt, idempotency and mapping readbacks and verifies stored history and projection hash remain unchanged.
- `test_disproved_relationship_is_neither_projected_nor_traversed` verifies build-sidecar preservation and fail-closed query behavior for a disproved edge.
- `test_multiple_revisions_of_one_statement_get_distinct_edge_ids` verifies revisions 1 and 2 retain separate refs and edge IDs.

The existing near-name test was adjusted to assert against graph endpoint IDs rather than the previous human-readable edge-ID format.

The lineage-safety regressions verify that unknown aggregate refs, ambiguous manifest slice mappings, conflicting full refs for one aggregate-qualified statement identity (both changed statement hash and changed aggregate hash), and ref-less edges are omitted before traversal under both `allow_stale` and `historical`; relevant omissions add `MissingDatum(reason=not_observed)`, return freshness `unknown`, and cause `current_required` to raise `VERSION_CONFLICT`. A positive regression reuses the same local statement ID/revision across distinct aggregates, both across edges and between an edge's statement/input refs; all refs stay valid and a scoped company-B query remains current. Unrelated invalid edges and invalid edges excluded by the relation filter are quarantined globally but do not affect selected query freshness or add a query-specific diagnostic. A separate test confirms that a valid company-C edge reached by a company-B query remains in the result with its full StatementRefs and provenance when C is outside `required_slices`; freshness becomes `unknown` and reports the C slice. The unrelated-company regression uses a depth-zero B query, so neither a C edge nor a shared node carrying C StatementRefs is selected; changing only C's current revision leaves B current. Selected node StatementRefs and materialized Business/Events source refs are freshness dependencies too. Generic source/evidence refs remain intact as context-specific provenance and do not trigger hidden owner reads; this follows Graph.query's operation boundary (scoped KnowledgeReadPorts only) and the contracts' owner-specific scope-resolution rules. Thus `required_slices` is freshness-only and does not filter graph content or provenance.

The shared-data validator was also run with the v1.0.1 corrected freeze:

```powershell
$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
```

Observed output: 13 checks passed, 0 failed; five shared operation fixtures validated. This validator does not call T12 code. T12 separately ran strict operation request/response exchange checks for Graph.build, Graph.publish, and Graph.query against the pinned operation registry.

The full contract suite passed in the remediation run: `31 passed in 4.96s`. The shared-fixture validator passed `13` checks with `0` failures, including strict validation of all five shared operation fixtures. `tools/contracts_codegen.py --check` passed in the previous T12 verification. The first codegen-check invocation could not locate `datamodel-codegen` because the isolated worktree's tool directory was not on `PATH`; rerunning with the project `.venv\Scripts` directory prepended produced `generated Pydantic contracts match OpenAPI and pinned generator`. No contract or OpenAPI files were modified.

The deterministic experiment runner was executed twice and produced identical [`results/experiment-v1.0.1.json`](results/experiment-v1.0.1.json) content. Its LF-normalized SHA-256 is `sha256:6353aa8d52ecf1597d70ba2e48f4d11bb2ecd49c3514eed75c17765b9c02d88f`; the checkout's CRLF conversion may change the physical file hash without changing canonical content. Re-running the tests verifies repeated build/query equality; the experiment does not use a live model or external data.

## Coverage inventory

| Category | Evidence in tests |
|---|---|
| Positive | 15 explicit direct edges; inferred edge with method and exact input refs; direct and indirect query paths; isolated publish. |
| Negative/security | Missing ref does not create edge; bad hash/aggregate source ref rejected; near-name and parent/subsidiary IDs stay distinct; no unasserted edges; unknown seed rejected; source ref missing/tampered publish is rejected; log payload sentinel is absent. |
| Incomplete/unknown | Unknown supplier and volume remain `MissingDatum`; no path is not a negative dependency; unknown freshness blocks `current_required`. |
| Contradiction | Disputed stock claims remain two separate sidecar statements; no invented inventory edge. |
| Time | `recorded_at` leakage check, valid-from/valid-to membership, expired supplier exclusion, historical supplier restoration, current/stale/unknown freshness and exact historical cut. |
| Ontology | Unmapped relation is omitted; alternate ontology is explicit and remapped; relation-filtered traversal only returns allowed edge codes. |
| Boundaries | BFS max depth and max node truncation, missing graph result, unknown seed failure, optimistic revision conflict, idempotency conflict and repeat. |
| Determinism/reproducibility | Reordered Statements/entities/slices and reference input produce identical snapshot hashes; repeated query output is byte-equivalent at DTO JSON level; frozen dataset version and hashes are checked. |
| Metamorphic | Irrelevant text and display-name changes do not alter edge membership; a meaningful valid-time cut changes membership. |
| Provenance/contract | Exact StatementRef hashes and aggregate refs checked; inferred input refs/method retained; all three Graph operation envelopes validated against the current pinned schema registry. |
| Remediation regressions | Scoped freshness ignores unrelated company partitions only when selected materialized graph items do not use them; aggregate-local IDs across aggregates do not collide; aggregate/statement hash conflicts under the same local identity are quarantined; selected edges outside declared freshness slices are preserved but unknown; invalid lineage is quarantined for allow-stale and historical; unrelated-boundary and relation-excluded invalid edges do not affect scope; contextual source/evidence refs remain preserved without hidden reads; empty/unresolvable scope cannot be current; publish rejects refs outside declared slices; stored readbacks are detached; disproved edges are excluded; edge IDs distinguish statement revisions. |

## Shared T12 cases

All 15 shared T12 property cases are exercised across the tests and deterministic experiment:

- `direct-country-supplier-company-path`, `direct-company-to-port`, `indirect-company-c-route` — build assertions and bounded company B/company C BFS tests.
- `no-supplier-path-for-a`, `unknown-is-not-negative`, `stock-conflict` — no-path, MissingDatum and contradiction tests.
- `current-projection`, `relevant-update-stales-projection`, `unrelated-partition-update` — projection counts and scoped freshness tests.
- `historical-supplier-edge` — exact source reference materialization, historical rebuild, and old/new supplier edge membership.
- `alias-does-not-merge-legal-entities` — separate exact company/parent/subsidiary/near-name node IDs with no implied edge.
- `alternate-ontology`, `hypothetical-only`, `inferred-relation-grounding`, `explicit-negative-not-positive-dependency` — explicit mapping, status handling, inferred grounding, and negative-sidecar tests.

## Quality interpretation

- **Engineering quality:** Offline unit/negative/boundary/contract tests pass. No package dependency, network access, model call, persistence, or production change is involved.
- **Algorithm quality:** **PRELIMINARY / NOT ACCURACY-MEASURED.** The shared cases are hand-authored provisional properties, not independently approved labels. No precision, recall, edge coverage, or real supply-chain correctness metric can be claimed from these tests.
- **Integration readiness:** **NOT READY.** Exact StatementRef/ObjectRef materialization and GraphEdge negative/time representation require Framework owner decisions. The original independent review reports are committed; an independent re-review of this lineage-safety remediation is pending. Scoped partition comparison now follows the operation card's unrelated-company rule; `StatementRef.aggregate_ref.hash` still cannot be compared with a `KnowledgeSlice` in the Graph.query DTO.
- **Live model quality:** **NOT MEASURED.** The spike is deterministic and has no model adapter.

## Known limits

See [`LIMITATIONS.md`](LIMITATIONS.md): especially the fact that `BuildGraphInput.knowledge` alone lacks exact aggregate refs; negative assertions and per-edge validity are held outside normative GraphSnapshot DTOs; and the isolated store cannot validate source records without explicitly supplied materialized reads.
