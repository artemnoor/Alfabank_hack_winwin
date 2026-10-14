# T12 — Final Independent Re-review: Aggregate-scoped Lineage

**Review date:** 2026-10-14
**Implementation reviewed:** `2a40e81cdf026504534ae431d8424b4c7cc04495`
**Previous implementation baseline:** `188e902748636b5e383e1435ed3f8e203d34c8bb`
**Review branch/worktree:** `codex/review-t12-aggregate-scope-final` / `C:\CodexData\worktrees\alfabank-review-t12-aggregate-scope-final`
**Review mode:** read-only; this branch contains only this report.

## Contract interpretation

`Graph.query` is limited to `GraphRepository` and `KnowledgeReadPorts` for scoped freshness comparison. Its content selection is controlled by seeds, relations, depth, and bounds; `seed_ids=[]` means the full snapshot. `required_slices` is a freshness input, not a response-content filter. I found no normative requirement to strip graph edges or provenance merely because their source slice is outside `required_slices`. (Framework v1, [03-operations.md §16](../../../docs/specs/framework-v1/03-operations.md#L300); [02-contracts.md, Graph and freshness](../../../docs/specs/framework-v1/02-contracts.md#L72).)

The Provenance contract scopes `StatementRef.statement_id/revision/hash` inside the referenced immutable aggregate. Contextual `Provenance.source_refs` do not themselves prove scope, existence, or hash; trusted owner ports do. Graph.query therefore must not introduce hidden raw Documents/Evidence reads. ( [02-contracts.md §Provenance](../../../docs/specs/framework-v1/02-contracts.md#L66), especially lines 74 and 84.)

## Findings by severity

| Severity | Status | Finding |
|---|---|---|
| CRITICAL | None | No critical findings. |
| HIGH | **Closed** in `188e902` | A confirmed edge with missing, ambiguous, conflicting, or unresolvable StatementRef lineage could previously be returned under `allow_stale`/`historical`. `_safe_edges` now quarantines it before BFS, selected affected queries report unknown freshness and `not_observed`, and `current_required` returns `VERSION_CONFLICT`. Regression matrix covers unknown aggregate, ambiguous slice, conflicting statement/aggregate hash, and ref-less lineage under both policies. |
| MEDIUM | **Closed** in `2a40e81` | Query identity previously used only `(statement_id, revision)`, incorrectly treating valid local IDs from separate aggregates as a conflict and dropping both edges. `_statement_identity` now includes aggregate owner, object ID, and revision; it still compares full refs to detect conflicting hashes within one aggregate revision. Positive distinct-aggregate and negative same-aggregate hash-conflict regressions pass. |
| LOW | **Open; diagnostic gap** | An unresolved StatementRef on a selected node makes freshness `unknown`, but `allow_stale` retains that node/reference without a node-specific `MissingDatum` or `missing_slices` entry. `current_required` rejects the result. Framework §16 does not explicitly require node-level diagnostics, so this is not a contract violation or an ungrounded edge finding; it can make the reason for `unknown` less actionable. |

### Reproduction of the remaining LOW

Starting from the shared T12 graph, replace a selected non-seed node (`node-port-vega`) StatementRef aggregate object ID with an unknown ID. Query company B with `allow_stale`, seed `node-company-b`, depth 1. Observed: `freshness=unknown`, the node and unresolved reference remain in the response, and `current_required` raises `VERSION_CONFLICT`; no node-specific diagnostic identifies that reference. This behavior is documented for follow-up; no implementation change is included in this review.

## Re-review probes

- **Aggregate-local IDs:** Query company B with seeds `node-company-b` and `node-supplier-b-x`, depth 0, relation `purchases_from`. Baseline and modified snapshot both return the B edge with `freshness=current` when an unrelated C edge has the same local statement ID/revision under a different aggregate.
- **Same-aggregate conflict:** Give the competing reference the same aggregate owner/object/revision and local ID/revision but a different aggregate hash. The affected edge is quarantined, freshness is `unknown`, and the edge is not returned. The corresponding statement-hash conflict case is also covered by the T12 test matrix.
- **Original safety matrix:** Unknown aggregate, ambiguous slice, conflicting statement hash, conflicting aggregate hash, and ref-less edge are excluded before traversal under `allow_stale` and exact-cut `historical`; affected freshness is unknown and `current_required` rejects with `VERSION_CONFLICT`.
- **Scope and traversal:** An invalid edge outside the selected boundary does not change B freshness. A relation filter that excludes it does not create a diagnostic. A selected valid C edge remains byte-for-byte equivalent with all provenance; freshness becomes unknown, C is reported missing from the required freshness scope, and `current_required` rejects. This confirms `required_slices` is not a content filter.
- **Node/source dependencies:** Selected-node StatementRefs and materialized Business/Events source refs participate in freshness. I independently checked an Events source slice at revision 1 (`current`) then revision 2 (`stale`, `event-probe` listed). A malformed selected-node ref produces the LOW diagnostic behavior above.
- **Historical/full snapshot and completeness:** With `seed_ids=[]`, an exact-cut historical query excludes a ref-less edge and returns `freshness=unknown`; graph completeness remains `partial` and is not promoted.
- **No hidden source reads:** The query receives only materialized graph snapshots and current slices. The test retains Documents/Evidence provenance pointers without reading those owners or treating them as graph dependencies.

## Independent reviews

- **Spec audit** (agent other than patch author): confirmed the original HIGH fix and the aggregate-scope MEDIUM fix; identified the MEDIUM before remediation and verified that required slices remain freshness-only.
- **Standards audit** (agent other than patch author): found no documented hard violations; confirmed changes stay within `spike/T12/`. It identified the open LOW node-diagnostic gap and the documented Business/Events ObjectRef-to-slice integration limitation.

## Verification run on reviewed commit

Environment: project Python 3.12 venv; pytest plugin autoload disabled as in the T12 offline test instructions; no external network, live model, or database used.

| Check | Result |
|---|---:|
| `spike/T12/tests` | **57 passed** |
| `tests/contracts` | **31 passed** |
| `spike/_shared/validation/validate.py` | **13 passed, 0 failed**; dataset `t09-t13-independent-v1`, canonical hash `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725` |
| `git diff --check 188e902748636b5e383e1435ed3f8e203d34c8bb 2a40e81cdf026504534ae431d8424b4c7cc04495` | **passed** |

Exact test invocations (PowerShell):

```powershell
$env:PYTHONPATH='spike/T12/src;packages/contracts/src;spike/T12/tests'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T12/tests -q --tb=short

$env:PYTHONPATH='packages/contracts/src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider tests/contracts -q --tb=short

& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py

git diff --check 188e902748636b5e383e1435ed3f8e203d34c8bb 2a40e81cdf026504534ae431d8424b4c7cc04495
```

## Readiness

- **Engineering:** PASS for the scoped regression, T12, contract, and shared-data checks.
- **Algorithm quality:** PRELIMINARY; evidence is from deterministic synthetic fixtures, not production data or a live model.
- **Integration:** **NOT READY.** `KnowledgeSlice` has no aggregate hash, and `StatementRef` has no selection key. Graph.query can fail closed on zero/ambiguous slice mappings but cannot independently verify an unambiguous aggregate hash against current owner materialization. Business/Events ObjectRef-to-slice matching is likewise limited to the available owner/partition/revision fields. Keep the documented trusted-owner validation gate at the build/publish boundary. No DTO/OpenAPI change or hidden owner read is proposed.
- **External model quality:** NOT MEASURED; T12 is deterministic and makes no model call.

**Overall:** No open CRITICAL/HIGH/MEDIUM findings. One LOW node-diagnostic gap remains. Do not mark T12 integration-ready until the existing owner-resolution/DTO limitations are addressed at the approved Framework boundary.
