# T13 limitations and approval gaps

- The common dataset is synthetic, provisional, and not approved as gold. Its 30 T13 expectations and the T13 event-target mappings are test hypotheses, not verified ground truth.
- Event target metadata beyond the materialized `Events.read` records is assembled from the shared synthetic event catalog for offline scenarios. It is not a T09 algorithm result.
- The shared graph is partial. No path means unknown within this graph snapshot and profile scope; it cannot establish absence of business exposure.
- `strict`, `balanced`, and `broad` are spike-local traversal policies. Their status allowlists and depth limits need owner review before any production use.
- The stored edge orientation is used as a T13 traversal policy. The normative pair validator guarantees topological edge continuity but does not itself define relation direction; confirm the desired ontology traversal semantics before connecting this policy to Framework runtime.
- Graph edge `epistemic_status` is consumed as supplied. T13 does not independently prove a statement, operate the Evidence owner, or derive truth from a hash/anchor. A verified anchor establishes integrity of the cited span only. Exact owner/object/revision/hash refs are required, and disputed or unverified evidence cannot support a path claim.
- `confirmed` exposure requires a pinned experimental policy reference, a confirmed trust result, and an explicit owner-confirmation decision. The prepared T11 policy produces only `supported_unconfirmed`/`not_confirmed` or review eligibility, so no prepared case is confirmed. The spike cannot authenticate a caller-created owner decision; a trusted owner registry/result and runtime DTO handoff are required before relying on this gate.
- `source_reliability` remains separate from analytical confidence; disputed evidence is blocked and unassessed evidence can support only conditional potential findings when the other explicit path gates pass. No universal numeric threshold or reliability-to-confidence conversion is implemented.
- Approach C is a schema/path/evidence validator around deterministic controlled responses. There was no live model call; model accuracy, latency, cost, prompt robustness, and deployment suitability are **NOT MEASURED**.
- Approach D's event-type mechanisms are deliberately small and hand-authored. They require subject-matter review and broader adversarial datasets.
- All scenario results have conservative null materiality/financial quantity. The separate explicit calculator reports gross procurement exposure (not expected loss) for one synthetic assumption set.
- The normative `ImpactInput` has event, profile, match, graph, evidence, rules, and `as_of`, but no explicit numeric scenario input field. The `FinancialScenario` output requires input `StatementRef`s. The shared numerical scenario is a separate test object, not a Business Statement; this prototype therefore does not place its amount into the normative assessment. Adding or reinterpreting contract fields requires the contract owner and is outside this spike.
- The informational action list is local experimental policy. It is not a production action catalog. No action is executed, no bank condition is changed, and no external system is notified.
- Recommendations can still be too broad if a future caller supplies an overbroad assessment/evidence set. The Framework owner should choose the approved catalog, audience rules, and review conditions.
- Offline integration checks use materialized fixtures and do not call production owners. No performance/latency/cost benchmark, expert-labeled coverage report, or live model evaluation was run.

## Requires owner decision

1. Confirm whether directed edge traversal is the normative matching policy.
2. Decide how explicitly supplied financial scenario assumptions should enter `ImpactInput` as statements/references without changing OpenAPI in this experiment.
3. Approve versioned matching policy semantics and the trusted event/graph status interpretation.
4. Provide an approved informational action catalog and audience/approval rules.
