# T12 remediation — independent re-review

- **Review worktree / branch:** `C:\CodexData\worktrees\alfabank-review-t12-final` / `codex/review-t12-remediation-rerun`
- **Reviewed integration HEAD:** `80da94e12518d2aeb794e4dca9b3578c6b7d9763` (includes fix `e973676` and rebase)
- **Original findings:** `spike/T12/results/INDEPENDENT_REVIEW.md`
- **Scope:** read-only review of the original two HIGH and three MEDIUM probes, documented compatibility gaps, and the Graph.query freshness/operation-card tension. This report is the only intended change.

## Finding results

| Finding | Re-review result |
|---|---|
| T12-R1 HIGH — empty `required_slices` let `current_required` claim current freshness | **Remediation verified.** With all manifest and required slices omitted from explicit current reads, query raises `VERSION_CONFLICT`; a partial current read returns `unknown` with missing slices. |
| T12-R2 HIGH — publish accepted StatementRefs whose aggregates were absent from manifest | **Remediation verified for the original probe.** An otherwise valid candidate with all manifest slices removed raises `SourceReferenceMismatch`; isolated store remains empty. The store still cannot prove that an unrelated, unreferenced input slice was omitted without an independent expected-slice set. |
| T12-R3 MEDIUM — mutable readbacks changed stored revisions | **Remediation verified.** Mutating nested snapshot readback and returned receipt did not change stored projection hash or idempotency recovery. |
| T12-R4 MEDIUM — `disproved` edge participated in traversal | **Remediation verified.** Build preserves the source statement in its sidecar without emitting an edge; query also excludes a manually supplied `disproved` edge from BFS and output. |
| T12-R5 MEDIUM — edge IDs collided for revisions of one statement | **Revision case fixed; aggregate-scope limitation remains.** The same statement ID at revisions 1 and 2 produces two distinct edge IDs. A duplicate `(statement_id, revision)` from separate aggregates is still rejected fail-closed because the adapter/index keys statements by that pair; `StatementRef` itself includes `aggregate_ref`. This remains a documented compatibility limit, not a claim of full aggregate-local ID support. |

No open CRITICAL/HIGH issue was reproduced in the requested regression probes. T12 is still **NOT READY for integration** because of the unresolved Graph.query scope conflict and normative reference/DTO gaps below.

## Independent probes

- **R1 freshness:** built and published the shared graph, then queried `current_required` with empty `required_slices` and `current_slices`. Result: `VERSION_CONFLICT`. Omitting one current slice under `allow_stale` returned `freshness=unknown` and one missing slice.
- **R2 publish references:** removed all `manifest.input_slices` from a candidate while retaining its graph refs and passed the exact materialized source StatementRef index. Result: `SourceReferenceMismatch` for the absent manifest aggregate; no revision was stored.
- **R3 immutability:** changed a nested node entity name through `store.snapshot(...)`, then changed the first returned receipt. Subsequent snapshot hash, saved name, receipt recovery, and stored receipt remained unchanged.
- **R4 disproved traversal:** changed `b-buys-microkaskad` to `disproved` and updated its exact StatementRef hash. Build preserved it as `disproved_not_projected` and emitted no edge for it. A separately constructed snapshot containing that edge returned neither the edge nor its neighboring supplier node from BFS.
- **R5 revision-safe IDs:** built revisions 1 and 2 of `b-buys-microkaskad` with exact corresponding StatementRefs. Both edges were returned with distinct IDs. Adding a duplicate local `(statement_id, revision)` pair is explicitly rejected by the current adapter.

## Open Graph.query operation-card tension

The remediation requires every slice in `GraphSnapshot.manifest.input_slices` to be present and exactly match the current revision before returning `freshness=current`, even when the request supplies a narrower `required_slices` set. This is a conservative behavior-level conflict with `docs/specs/framework-v1/03-operations.md` §16 (`Graph.query`): it specifies current **scoped** partition revisions and says unrelated company partitions do not affect the result. `docs/specs/framework-v1/05-storage.md` also describes freshness over scoped partitions.

I reproduced the conflict with a company-B seed query whose required slices omitted company C. Changing only company C’s current slice made the `allow_stale` response `unknown`; the same scoped `current_required` query raised `VERSION_CONFLICT`. Therefore the original empty-requirement bug is closed, but the rule currently over-requires the full manifest for scoped queries. Framework owners must decide whether to scope freshness by requested dependencies, add a safe dependency mapping, or retain the stricter behavior and revise the normative card. No spec or DTO was changed during this review.

## Other remaining contract and implementation limits

- **Graph.build exact references:** `BuildGraphInput.knowledge` (`#/components/schemas/BuildGraphInput/properties/knowledge`) has inline Statements and KnowledgeSlices but no aggregate `ObjectRef` hash needed by `StatementRef.aggregate_ref` and `StatementRef.hash` (`#/components/schemas/StatementRef/properties/aggregate_ref`, `/properties/hash`). The spike requires explicitly materialized `statement_ref_index` and `aggregate_refs`; absent refs fail closed. This is not the normative Graph.build function signature.
- **Graph.publish source reads:** `PublishGraphInput` carries candidate and expected revision; it has no materialized owner-read refs. The in-memory simulator takes `source_statement_refs` as an explicit additional input and makes no hidden reads. Its local validation can check referenced aggregates against declared owner/partition/revision slices, but cannot prove completeness of unrelated input slices without an independently supplied expected set.
- **GraphEdge representation:** the normative `GraphEdge` has no polarity or per-edge valid-time interval. Explicit negative statements remain sidecar/MissingDatum data, and `TemporalEdgeContext` carries validity outside the DTO. Historical membership requires rebuilding at the requested cut.
- **Aggregate-local statement IDs:** the KnowledgeSnapshot adapter rejects duplicate `(statement_id, revision)` keys, even if two aggregate-scoped StatementRefs would distinguish them. Until an approved aggregate-qualified input mapping is available, this remains fail-closed and may omit otherwise valid source statements.
- Entity resolution is exact-ID only; taxonomy mapping is a narrow allowlist and one constrained inference rule. The prototype does not prove source assertions true, compute graph coverage, or test real supplier networks. Dataset expectations remain synthetic/provisional; algorithm quality is **PRELIMINARY**, live-model quality **NOT MEASURED**.

## Commands and results

Pinned workspace Python 3.12.15, `-B`, pytest cache disabled; no network, model, database, or contract changes.

```powershell
$env:PYTHONPATH='spike/T12/src;packages/contracts/src;spike/T12/tests'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T12/tests -q --tb=short
# 36 passed, 0 failed, 0 skipped

$env:PYTHONPATH='packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider -q tests/contracts
# 31 passed, 0 failed, 0 skipped

& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
# 13 checks passed, 0 failed; five shared operation fixtures passed strict validation

$env:PYTHONPATH='spike/T12/src;packages/contracts/src;spike/T12/tests'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T12/experiments/run_graph_experiment.py
# exit 0; regenerated experiment JSON equals the HEAD artifact blob
```

The experiment artifact’s generated blob SHA-256 was `6353aa8d52ecf1597d70ba2e48f4d11bb2ecd49c3514eed75c17765b9c02d88f`, matching the committed blob. Its working-copy line-ending form was restored after the run; no result or shared validation report change remains. The 15 shared T12 expectations are provisional and do not establish real-world graph accuracy.

## Review conclusion

- **Engineering:** requested suites and validators pass; all five original regression probes are covered and independently reproduced against the fix.
- **Algorithm quality:** **PRELIMINARY**, synthetic only; no accuracy estimate.
- **Integration readiness:** **NOT READY** pending owner resolution of scoped freshness versus all-manifest checking, exact ref materialization, sidecar-only polarity/validity, and aggregate-local statement identity.
- **Review boundary:** only this report is changed. No push or cherry-pick was performed.
