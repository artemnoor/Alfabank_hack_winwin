# T12 plan and hypothesis status

## Objective

Test whether a deterministic graph projection built from materialized statements can preserve the evidence/status/time needed for impact explanations without inferring links from names or industry. Shared inputs are pinned to dataset v1.0.1 and remain provisional.

## Experiments and status

| Experiment | Hypothesis | Status / artifact |
|---|---|---|
| Exact-ID projection | Only explicit, allowlisted, entity-valued statements create edges; IDs remain distinct regardless of display-name similarity. | Implemented; `test_build.py`; no fuzzy matching or alias merge. |
| Provenance and epistemic state | Direct edges keep exact StatementRefs, evidence refs and source provenance; inferred edges retain method/input refs; unknown, hypothetical and negative facts do not become positive edges. | Implemented; tested offline. Negative polarity is sidecar-only because GraphEdge has no polarity field. |
| Temporal projection | A statement is eligible only after its recorded time and inside valid-time bounds; historical cuts can restore a previously valid edge. | Implemented; `TemporalEdgeContext` retains source bounds outside GraphEdge. |
| Partial knowledge | Missing suppliers and stock conflicts remain missing/disputed; absence of a path does not prove absence of dependency. | Implemented; shared unknown and conflict cases pass. |
| Query | Sorted bounded BFS is deterministic; relation, depth, node and freshness policies are explicit. | Implemented; content follows seed/relation/depth/node bounds. `required_slices` is freshness-only. StatementRef local IDs are aggregate-qualified; distinct aggregates may reuse local IDs while hash conflicts within one aggregate-qualified identity fail closed. Selected graph StatementRefs and mapped materialized Business/Events source refs participate in freshness; generic source/evidence references stay intact as contextual provenance without hidden owner reads. Selected valid edges with source slices outside that list stay visible with complete provenance but make freshness unknown; missing/ambiguous/conflicting lineage edges are quarantined before traversal under every policy. Unrelated-boundary and relation-excluded invalid edges do not change scoped freshness. Current, stale, unknown, historical, no-path, truncated, missing-graph and receipt cases pass. |
| Publish model | Isolated revision store enforces optimistic revision and idempotency while checking explicitly materialized source refs against the candidate manifest. | Implemented in memory only; all grounded refs must resolve to a declared slice; published snapshots/receipts are detached deep copies; no persistence or hidden owner calls. |
| Remediation regressions | Close review findings around graph freshness, manifest references, mutable readbacks, disproved edges and revision identity. | Implemented; scoped/unrelated, aggregate-qualified identity, hash conflict, changed/missing, empty/unresolvable and unknown/ambiguous/ref-less lineage regressions pass, as do the full 57-test T12 suite and contracts suite. Invalid relevant edges produce `not_observed` missing data and unknown freshness in allow-stale/historical modes; unrelated or relation-excluded invalid edges do not. Final independent re-review closed HIGH/MEDIUM; one LOW node-diagnostic gap remains. |
| Framework compatibility | Operation exchanges conform to the frozen operation registry/OpenAPI. | Strict request/response exchange tests pass for Graph.build, Graph.publish and Graph.query; input reference materialization remains a documented gap. |
| Vendor/OSS landscape | Vendor graph ideas can inform experiments without importing commercial data or copying closed implementations. | Desk research completed in `RESEARCH.md`; no vendor service/data used. |

## Design boundary

All executable code, tests, experiments, fixtures, results, and documentation are within `spike/T12/`. No production module, shared fixture, OpenAPI schema, contract package, AI Factory setting, or T08 file is modified. No dependency was added. The shared corpus was read at its v1.0.1 frozen hash and not edited.

## Exit criteria

- [x] Runnable pure build/query prototypes.
- [x] Isolated publish-state model.
- [x] Shared graph scenarios, incomplete/conflicting inputs, negative and boundary checks.
- [x] Strict normative operation exchange checks.
- [x] Deterministic repeat and metamorphic checks.
- [x] Reproducible experiment output and test report.
- [x] Explicit known-contract-gap and limitation reports.
- [x] Independent author-separate review performed; HIGH findings and feasible MEDIUM findings remediated with regression tests.
- [ ] Independent re-review of remediation by a different reviewer.
- [ ] Independent re-review of scoped freshness remediation and Framework owner review of exact-reference materialization and graph DTO sidecars.
- [ ] Human review of provisional fixture expectations before any gold-set use.

No acceptance, production status, or algorithm accuracy is claimed while the unchecked items remain.
