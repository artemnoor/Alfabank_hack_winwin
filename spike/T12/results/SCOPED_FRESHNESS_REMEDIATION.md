# T12 scoped freshness and aggregate-local lineage safety remediation

**Base:** `188e902748636b5e383e1435ed3f8e203d34c8bb`
**Branch:** `codex/spike-t12-lineage-safety`
**Scope:** `spike/T12/**` only. Framework contracts, OpenAPI, shared fixtures and other modules are unchanged.

## Corrected behavior

The earlier scoped-freshness note incorrectly treated `required_slices` as a graph-content filter and allowed edges with unresolved references to remain visible under `allow_stale`. This remediation removes both assumptions.

Graph content is selected by seed IDs, relation filters, depth and node bounds. `required_slices` is freshness input only: it does not filter edges and does not strip node or edge provenance. A valid selected edge whose source slice is outside `required_slices` remains in the response with its complete StatementRefs, evidence references and provenance. The query reports freshness `unknown`, lists that source slice in `missing_slices`, and rejects `current_required` with `VERSION_CONFLICT`.

StatementRef local identity is aggregate-qualified by owner/object ID/revision plus local statement ID/revision. Distinct aggregates can reuse local IDs without conflicting. The full refs must agree under one aggregate-qualified identity; a mismatch in aggregate hash or statement hash fails closed. Edges with missing, conflicting, ambiguous or unresolvable StatementRef lineage are excluded before BFS. They are never traversed or returned under `allow_stale`, `historical`, or other policies. If a quarantined edge touches the selected nodes and matches the relation filter, its omission adds a safe `MissingDatum` with `reason=not_observed`; freshness is `unknown`, including for an exact historical time cut. `current_required` rejects the result. An invalid edge outside the selected boundary does not affect the query.

Freshness validates each explicitly declared required slice against the snapshot manifest and current materialization. It also requires selected graph StatementRefs and materialized Business/Events `source_refs` to map uniquely to the manifest and be included in the required set. Generic source/evidence refs are context-specific provenance pointers, retained in full without treating their artifacts as hidden Graph.query inputs. An unrelated company-C revision does not affect a company-B result when the selected graph items do not depend on C and C was not explicitly required. This is not a content-filtering rule: if the selected BFS includes a valid C edge or node with C StatementRefs/materialized partition refs, it and all its provenance remain visible while freshness becomes `unknown`.

## Regression coverage

- Five forms of unsafe edge lineage (unknown aggregate ref, ambiguous manifest slice, changed statement hash under one aggregate identity, changed aggregate hash under one aggregate identity, no StatementRefs) are checked under both `allow_stale` and `historical`: no traversal or returned edge, related `not_observed` diagnostic, `unknown` freshness, and `current_required` rejection.
- Two valid refs with identical local statement ID/revision but distinct aggregate refs remain independently usable, both across edges and between an edge statement ref and input ref; altered aggregate or statement hashes under the same aggregate-qualified identity are quarantined.
- Invalid edges outside the selected node boundary or rejected by the relation filter do not add query diagnostics or change scoped freshness; globally quarantined invalid edges still cannot be traversed.
- A bounded company-B query remains current after an unrelated company-C revision changes when BFS excludes C edges and nodes carrying C provenance.
- A company-B query that reaches a company-C edge preserves that edge and its full provenance, reports the omitted freshness slice and returns `unknown`.
- Selected node StatementRefs and materialized Business/Events source refs participate in freshness. Generic document/evidence refs remain preserved without hidden owner reads.
- Existing changed/missing/empty/unresolvable scope regressions remain in the T12 suite.

The Graph.query operation card (`docs/specs/framework-v1/03-operations.md`, §16) allows `KnowledgeReadPorts` only for scoped freshness and defines current scoped partition revisions as the read state. `docs/specs/framework-v1/05-storage.md`, “Граф и актуальность,” defines graph freshness using the projection manifest's materialized `KnowledgeSlice`s. `docs/specs/framework-v1/02-contracts.md`, “Provenance,” says `source_refs` are context-specific and do not by themselves establish owner existence or scope; it also says `StatementRef.aggregate_ref` is owned by Events or Business and carries graph-statement lineage. Therefore this prototype checks selected node/edge StatementRefs and Business/Events source refs that map to graph materialized partitions. It preserves generic document/evidence source refs and does not resolve them through hidden owner reads. This is an experimental interpretation of Graph.query's allowed data dependencies, not a new normative contract rule.

## Contract limitation

`StatementRef.aggregate_ref` is an `ObjectRef` with a hash (`#/components/schemas/StatementRef/properties/aggregate_ref`). `ProjectionManifest.input_slices` and `SubgraphSelection.required_slices` contain `KnowledgeSlice` (`#/components/schemas/ProjectionManifest/properties/input_slices`, `#/components/schemas/SubgraphSelection/properties/required_slices`), whose fields include owner, partition ID, revision and selection key but no aggregate hash. StatementRef does not carry the selection key. Graph.query can uniquely map an edge ref using owner/partition/revision and fail closed on zero or multiple matches, but cannot independently compare `aggregate_ref.hash` with the current owner materialization. No DTO or OpenAPI change is proposed.

## Verification

Using the pinned Python 3.12 workspace venv:

```powershell
$env:PYTHONPATH = 'spike/T12/src;packages/contracts/src;spike/T12/tests'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T12/tests -q --tb=short

$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider tests/contracts -q --tb=short

$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
```

Results: T12 `57 passed in 1.47s`; contracts `31 passed in 4.96s`; shared validator `13 passed, 0 failed`. Pytest plugin auto-discovery was disabled after an unrelated plugin import raised `MemoryError`; this suite uses core pytest only. The deterministic offline graph experiment output is frozen at LF-normalized SHA-256 `sha256:6353aa8d52ecf1597d70ba2e48f4d11bb2ecd49c3514eed75c17765b9c02d88f`. The experiment exercises build projections, not the query remediation itself. No model, external network, database or production write was used.

**Status:** the regression behavior is implemented and tested locally. Engineering checks do not establish real-world graph accuracy; algorithm quality remains preliminary. Integration readiness awaits independent re-review and owner resolution of the documented reference-materialization/DTO limitation.
