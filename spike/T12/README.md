# T12 — Knowledge Graph projection spike

This is an offline algorithm prototype for projecting explicitly supplied Framework v1 knowledge into a versioned business-dependency graph. It is isolated under `spike/T12/`; it does not implement or write a production graph database.

## Input and output

`build_graph` receives a normative `BuildGraphInput` plus two explicit materialized source inputs: an exact `StatementRef` index and the corresponding immutable aggregate `ObjectRef`s. It returns a normative `BuildGraphOutput` plus spike-only sidecars for statements that the graph DTO cannot faithfully encode and per-edge valid-time context.

Entities are keyed only by the supplied entity IDs. A relation is created only when a supplied Statement has an entity target, an explicitly allowlisted predicate, a valid temporal window, and appropriate exact references. Similar organization names, product text, industries, or geography never create links or merge entities.

Direct edges keep the source `StatementRef`, evidence references, provenance and epistemic status. An inferred edge stays `inferred` and preserves its derivation method and exact input StatementRefs. Edge IDs are stable hashes over the statement ID, revision, and exact source refs, so distinct revisions do not collide. Unknown, hypothetical, disproved, and explicit-negative statements are preserved in the sidecar and represented as `MissingDatum`; they do not become positive edges. A disputed edge keeps the `disputed` status. Missing edges mean unknown, not “no dependency.”

The relation mapping is an explicit, versioned input. Temporal selection uses `known_as_of` and `valid_as_of` independently. Output ordering and hashes are deterministic. Partial and incomplete source data remain `partial` or `unknown`; no graph coverage score is claimed.

`query_graph` traverses only a passed snapshot using deterministic, bounded, weakly connected BFS. Edge direction is preserved in the result; traversal may follow either endpoint to find nearby nodes. Disproved edges are neither traversed nor returned. Graph content is selected by seeds, relation filters, depth and node bounds. `required_slices` declares freshness inputs only; it does not filter edges or strip node/edge provenance. StatementRef local identity is scoped by aggregate owner/object ID/revision plus local statement ID/revision; distinct aggregates may reuse local IDs. Under the same aggregate-scoped identity, complete StatementRefs (including aggregate and statement hashes) must agree or lineage fails closed. Selected node and edge StatementRefs must map uniquely to manifest slices included in the declared freshness scope. Business/Events source refs that identify materialized graph partitions are also checked. Other `source_refs` and `evidence_refs` remain intact as provenance pointers; Graph.query does not read those owner records or treat raw document/evidence refs as extra graph inputs. This follows the distinction in the operation contract between manifest slices used to build the graph and context-specific provenance references. A valid selected edge outside the freshness scope stays in the result with full provenance, while freshness becomes `unknown` and the missing source slice is reported; `current_required` rejects it. An edge with missing, conflicting, ambiguous or unresolvable lineage is quarantined before BFS and is never traversed or returned under any policy. If such an edge touches the selected nodes and matches the relation filter, the result includes a safe `MissingDatum(not_observed)` and freshness is `unknown`, including for an exact historical cut. Invalid edges outside the selected boundary or excluded by the relation filter do not affect freshness or add query diagnostics. A change to company C does not affect a company-B query when selected graph items do not depend on C, and C was not declared as a freshness input. Missing current data yields `unknown`; a changed declared slice yields `stale`; `current_required` rejects either non-current state. `historical` requires an exact manifest time cut.

`IsolatedGraphStore` models revision, idempotency and receipt behavior in local memory only. `publish` requires the candidate’s exact source StatementRefs to be explicitly passed as materialized input and verifies that every referenced source aggregate is present in the graph manifest. Stored revisions, receipts and idempotency results are returned as deep copies, preventing a caller from mutating published state through a readback. It performs no hidden owner read and persists nothing outside the Python object.

## Run

From the repository root, using the pinned project virtual environment:

```powershell
$env:PYTHONPATH = 'spike/T12/src;packages/contracts/src;spike/T12/tests'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T12/tests -q
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T12/experiments/run_graph_experiment.py
```

The experiment writes [`results/experiment-v1.0.1.json`](results/experiment-v1.0.1.json). Dataset identity and both canonical/physical hashes are pinned in [`fixtures/dataset-lock.json`](fixtures/dataset-lock.json). The input data remain provisional and are not approved gold labels.

## Contract compatibility

The operation cards are Graph.build (#14), Graph.publish (#15), and Graph.query (#16) in `docs/specs/framework-v1/03-operations.md`. The prototype's returned operation DTOs are validated against the pinned `Graph_buildRequest/Response`, `Graph_publishRequest/Response`, and `Graph_queryRequest/Response` contracts. It does not alter those contracts.

There is an explicit input compatibility gap: `BuildGraphInput.knowledge` contains Statements and KnowledgeSlices, but not the exact aggregate `ObjectRef`s needed by `StatementRef.aggregate_ref`. The normative JSON pointers are `#/components/schemas/BuildGraphInput/properties/knowledge`, `#/components/schemas/KnowledgeSnapshot/properties/statements`, `#/components/schemas/KnowledgeSnapshot/properties/slices`, `#/components/schemas/StatementRef/properties/aggregate_ref`, and `#/components/schemas/StatementRef/properties/hash`. Graph.build’s card says it reads inline KnowledgeSnapshot and produces graph edge StatementRefs. The prototype therefore takes exact refs and their source aggregate refs as additional, explicitly materialized experiment inputs. It never invents refs or hashes; an absent direct ref omits the edge and returns `MissingDatum(unavailable)`.

Two other gaps remain visible in sidecars: `GraphEdge` has no explicit negative-polarity field and no validity interval. Negative facts are not serialized as edges. Validity for emitted edges is retained in `TemporalEdgeContext`, while the graph manifest pins the projection cut. See [`LIMITATIONS.md`](LIMITATIONS.md) for the effect on integration readiness.

Scoped freshness follows `docs/specs/framework-v1/03-operations.md` §16: an unrelated company slice does not change a seeded company's freshness when selected graph items do not depend on it. StatementRef lineage maps by aggregate owner, partition ID, and revision to exactly one manifest slice; zero or multiple matches fail closed and the affected edge is quarantined. The Graph projection manifest and StatementRefs identify materialized dependencies. Generic `Provenance.source_refs` and `evidence_refs` are preserved as context-specific source pointers and are not independently resolved by Graph.query; raw document/evidence artifacts are not hidden query inputs. Business/Events source refs that identify manifest partitions are checked as materialized knowledge refs. The normative DTO does not expose `selection_key` or an aggregate hash on `KnowledgeSlice`, so the read operation cannot independently verify `StatementRef.aggregate_ref.hash` against the current owner materialization. The prototype does not change the approved DTO/OpenAPI; see [`LIMITATIONS.md`](LIMITATIONS.md) and [`results/SCOPED_FRESHNESS_REMEDIATION.md`](results/SCOPED_FRESHNESS_REMEDIATION.md).

## Status

- Engineering quality: 57 offline T12 tests pass; the 31-test contracts suite also passes. No external calls or new package dependencies. Regression tests cover scoped freshness, aggregate-scoped StatementRef identity and hash conflicts, missing/ambiguous/ref-less lineage quarantine, selected node StatementRef/materialized Business/Events provenance dependencies, context source/evidence provenance retention, unrelated-boundary and relation-filter gating, manifest/reference consistency, detached published readbacks, disproved-edge exclusion, and revision-safe edge IDs. The original independent review reports are preserved; an independent re-review of this remediation is pending.
- Algorithm quality: **PRELIMINARY**. The shared dataset is synthetic, provisional, and not gold; no real supplier network, human-approved benchmark, or accuracy estimate was used.
- Live model quality: **NOT MEASURED**. This deterministic prototype makes no model call.
- Integration readiness: **NOT READY** until the reference materialization and DTO sidecar gaps have approved Framework-level handling.

Further test, research, and unresolved issue details are in [`PLAN.md`](PLAN.md), [`TEST_REPORT.md`](TEST_REPORT.md), [`RESEARCH.md`](RESEARCH.md), and [`LIMITATIONS.md`](LIMITATIONS.md).
