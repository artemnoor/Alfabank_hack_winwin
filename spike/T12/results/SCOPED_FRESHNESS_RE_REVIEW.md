# T12 scoped freshness: independent re-review

**Reviewed commit:** `b1bbe77e0e8c72599ebf65446f78c8c4e6abec7c`
**Base:** `5d88098c05f8988027af42236e1eb5e92f2fbae7`
**Review worktree/branch:** `C:\CodexData\worktrees\alfabank-review-t12-scoped-freshness`, `codex/review-t12-scoped-freshness`
**Review mode:** read-only implementation review. Only this report was added.

## Result

One open **HIGH** finding prevents safe downstream use of the query result when edge lineage is unresolved. The test suites pass, but they do not close this behavior: a test currently asserts that the unresolved edge remains in the response.

| Severity | Finding | Status |
|---|---|---|
| HIGH | An unresolved or ambiguous edge can remain a `confirmed` edge in `allow_stale` and `historical` results. | OPEN |
| MEDIUM | The README's claim that scoped provenance is omitted is not true for every provenance field. | OPEN; prototype behavior gap |

## Findings

### HIGH — Unresolved lineage remains a confirmed path

In [`query.py`](../src/t12_graph_spike/query.py#L115), an edge is selected when `resolved` is false. `_freshness` marks the response `unknown`, but the selected `GraphEdge` is returned unchanged by the result projection ([lines 348–355](../src/t12_graph_spike/query.py#L348)); its `epistemic_status` is not downgraded or otherwise gated. `current_required` rejects non-current freshness, but `allow_stale` returns the edge. The historical branch returns `historical` before inspecting edge lineage ([lines 163–169](../src/t12_graph_spike/query.py#L163)).

**Reproduction:** start from `_published_graph()`, select a company-B edge incident to `node-company-b`, and change only its `StatementRef.aggregate_ref.object_id` to `unknown-company`. With a company-B seeded `allow_stale` request, `query_graph` returns the same edge with `freshness=unknown`, `epistemic_status=confirmed`, and a reference whose aggregate is `unknown-company`. With `freshness_policy=historical` and the exact manifest time cut, it returns that same confirmed edge with `freshness=historical`.

This is also encoded in the new regression: [`test_query.py`](../tests/test_query.py#L306) names the case “fails closed”, but asserts the unresolved target edge is still present ([line 342](../tests/test_query.py#L342)). The check only closes the `current_required` freshness gate. A downstream consumer that examines the edge/path without independently rejecting the whole result can still treat an ungrounded relation as confirmed. That conflicts with the task's requirement that unresolved lineage not ground a confirmed business relation.

**Regression proposal:** for missing, unknown, and ambiguous StatementRef-to-slice mappings, assert that no returned/traversable edge can retain `epistemic_status=confirmed`; cover both `allow_stale` and exact-cut `historical`. Keep the existing `current_required` `VERSION_CONFLICT` assertion. The safe response may omit the edge or otherwise make it unusable as confirmed; do not infer a replacement source or change the approved DTO.

### MEDIUM — README's scoped node-provenance filtering claim is only partly implemented

The README says a seeded query omits out-of-scope node provenance ([`README.md`](../README.md#L15)). `_scoped_node` filters only `statement_refs` and `provenance.input_statement_refs` ([`query.py`](../src/t12_graph_spike/query.py#L145)); it leaves `provenance.source_refs` and `provenance.evidence_refs` unchanged. Returned edges and their provenance are also passed through unchanged. A local probe appended the actual company-C aggregate `ObjectRef` to the company-B seed node's `provenance.source_refs`; a company-B query returned a current result with only company-B `StatementRef`s on the node but the company-C ref still present in provenance.

The normative Graph.query card specifies scoped revision checks and whole-snapshot behavior for `seed_ids=[]` but does **not** make `required_slices` a response-content filter or redaction policy ([`03-operations.md` §16](../../../docs/specs/framework-v1/03-operations.md#L300), [`05-storage.md` “Граф и актуальность”](../../../docs/specs/framework-v1/05-storage.md#L76)). This is therefore a gap against the prototype README's scoped-provenance claim, not a normative Graph.query violation. Do not treat `required_slices` as an authorization boundary without an explicit policy; no contract change is proposed.

Minimal probe shape:

```python
b_node = next(n for n in snapshot.nodes if n.node_id == "node-company-b")
c_ref = next(r.aggregate_ref for e in snapshot.edges for r in e.statement_refs
             if r.aggregate_ref.object_id == "company-c")
changed = b_node.model_copy(update={"provenance": b_node.provenance.model_copy(
    update={"source_refs": [*b_node.provenance.source_refs, c_ref]}
)})
out = query_graph(company_b_query, snapshots={key: changed_snapshot},
                  current_slices=snapshot.manifest.input_slices).subgraph
assert any(ref.object_id == "company-c"
           for node in out.snapshot.nodes for ref in node.provenance.source_refs)
```

## Probes that passed or were not treated as defects

- Seeded company B remains `current` when only company C's current revision changes; changing company B makes it `stale`, and `current_required` raises `VERSION_CONFLICT`.
- Missing company-B current materialization and empty/unresolvable required scope yield `unknown`; `current_required` rejects them.
- Ref-less edges are omitted and make freshness unknown when they touch the selected result.
- Ambiguous owner/partition/revision-to-slice mapping yields `unknown`; however, its edge remains in the response, covered by the HIGH finding above.
- The returned `GraphSnapshot.completeness` is copied verbatim; the tested partial snapshot remains `partial`. I did not reproduce a false completeness promotion.
- `seed_ids=[]` means the whole snapshot per §16. A full-snapshot response with only company B in `required_slices` returns other snapshot edges and is `unknown`; that behavior alone is not a normative scope leak. Historical freshness requires the exact manifest `TimeSlice`.
- `KnowledgeSlice` has no aggregate hash and `StatementRef` has no `selection_key`. The prototype documents that it cannot compare the source aggregate hash to the current owner read. No contract change is proposed. Ambiguous mapping is detected, but its edge still being returned is part of HIGH above.

## Verification

Python 3.12.15 pinned workspace environment; no network, model, database, or source edits.

| Check | Result |
|---|---|
| T12 suite | 40 passed, 0 failed, 0 skipped |
| Framework contract suite | 31 passed, 0 failed, 0 skipped |
| Shared fixture validator | 13 passed, 0 failed; strict operation fixtures valid |
| Offline T12 artifact reproduction | Generated SHA-256 `6353aa8d52ecf1597d70ba2e48f4d11bb2ecd49c3514eed75c17765b9c02d88f`; equals the reviewed commit's artifact blob |
| `git diff --check b1bbe77^ b1bbe77` | Passed |

Commands:

```powershell
$env:PYTHONPATH='spike/T12/src;packages/contracts/src;spike/T12/tests'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T12/tests -q --tb=short

$env:PYTHONPATH='packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider tests/contracts -q --tb=short
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py

git diff --check b1bbe77^ b1bbe77
```

## Readiness

- **Engineering:** PASS for the reviewed test and validation suites; coverage was not measured.
- **Algorithm:** NOT READY for downstream confirmed-path use until the HIGH lineage gate is fixed and independently re-reviewed. Synthetic corpus only; quality remains PRELIMINARY.
- **Integration:** NOT READY. The approved DTO does not expose enough information to independently compare aggregate hashes or map a StatementRef to a selection key; this remains a documented owner/contract limitation.
- **Live model quality:** NOT MEASURED; T12 is deterministic and offline.
