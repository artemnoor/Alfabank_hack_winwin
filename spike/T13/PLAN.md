# T13 implementation plan and status

All work stays under `spike/T13/**`. Shared v1.0.1 input files are read-only and referenced by version/hash. The same `EventContext`, profile, graph, evidence set, and explicit numeric inputs are supplied to the C and D experiment paths for each case.

| Work item | Hypothesis | Status | Artifact |
|---|---|---|---|
| Match only explicit graph paths | False positive matches fall when event targets must be connected to the company by exact directed edge IDs | Implemented; tests pass | `matching/core.py` |
| Separate certainty modes | Mode changes should affect only eligible edge statuses/depth/staleness and preserve uncertainty | Implemented; tests pass | `matching/core.py`, `tests/test_matching.py` |
| C: model plus KG | A structured proposal can be blocked if its entity/path/evidence/quantity is unsupported | Implemented as controlled-response adapter; no live model | `impact/approach_c.py` |
| D: rules and scenarios | Explicit evidence/status/freshness/contradiction checks should block unsupported current mechanisms | Implemented; offline rule harness | `impact/approach_d.py` |
| No invented financial figures | Output quantity remains null unless normative input carries references for the numeric assumptions | Implemented; auxiliary arithmetic tested separately | `impact/common.py` |
| Informational recommendations | A proposal must be allowed, audience-compatible, evidence-linked, approval-preserving, and non-executing | Implemented; tests pass | `recommendations/propose.py` |
| Compare C and D on the same corpus | Structural guards and scenario outcomes can be compared offline without claiming model quality | Implemented for 30 provisional cases | `results/approach-comparison.json` |
| Strict operation compatibility | Each module can build/validate the existing DTO pair without modifying OpenAPI | Implemented for operation models and semantic pair validators | `tests/test_impact.py`, `tests/test_matching.py`, `tests/test_recommendations.py` |
| Framework connection | Connect owners, runtime, and approved action catalog only after separate review | Not started; outside spike scope | — |

## Experimental decisions

- Matching paths are traversed in stored edge direction. Modes are local policy versions and are not universal score guarantees.
- `none_found` is only emitted if the graph is current and complete for its declared slice. Partial, stale, truncated, or sparse inputs remain `unknown`/missing.
- Approach C receives a controlled model-shaped JSON fixture. The fixture builder is deterministic and does not train, call, or evaluate a model.
- A verified anchor is never treated as factual confirmation. T13 checks full immutable Evidence refs, blocks disputed/unverified path evidence, and permits `confirmed` exposure only when an explicit owner-confirmation result is supplied under the pinned experimental policy reference. The prepared T11 materialization has no such confirmation, so results stay potential/unknown.
- The local numerical scenario is an explicit gross procurement exposure calculation, not a loss forecast. Its amount is not emitted in the normative assessment because the operation input has no corresponding StatementRefs.
- Recommendations are constrained to a local informational allowlist in addition to the request allowlist; no bank transaction or external notification code exists.
