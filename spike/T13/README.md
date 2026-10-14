# T13: Matching, Impact and Recommendations

T13 answers: “How could this supplied event affect this supplied company, and why?” It runs only on the event/profile/graph/evidence values passed to it. It does not query a database or call another module.

## Inputs and outputs

- `matching/core.py` takes a materialized event context, graph snapshot, company profiles, mode, and limit. It returns the normative `MatchingOutput` shape and validates its event, scope, and graph edge references.
- `impact/approach_c.py` accepts a structured, controlled model-shaped response. It validates the exact graph path, entity IDs, evidence references, event state, and any quantity against explicitly supplied scenario inputs. The runner uses fixture-shaped data only; it does not call an LLM.
- `impact/approach_d.py` checks event status, exact evidence references, path status and provenance, evidence-anchor integrity and source reliability, graph freshness, and profile contradictions before returning an `ImpactOutput`-shaped assessment.
- `recommendations/propose.py` selects only informational actions from the caller's `allowed_actions`, further intersected with this spike's local informational allowlist. It preserves audience and `requires_approval`, and emits evidence-linked proposals without executing them.

`Exposure`, `Likelihood`, `Direction`, `Materiality`, `AnalyticalConfidence`, and source reliability are kept as separate fields. A verified anchor is an integrity check, not confirmation that a statement is true. `confirmed` exposure requires the spike's separately pinned owner-confirmation signal; the supplied T11 result only supports an unconfirmed/review-eligible state, so the prepared scenarios remain `potential` or `unknown`. A missing path in a partial graph is `unknown`; it is not a no-risk conclusion. An exact company mention with no graph mechanism is not treated as a business dependency.

## Matching policy versions

| Mode | Allowed graph edge status | Maximum path length | Stale graph |
|---|---|---:|---|
| `strict` | `confirmed` | 2 | No path emitted |
| `balanced` | `confirmed`, `user_declared` | 4 | No path emitted |
| `broad` | `confirmed`, `user_declared`, `inferred`, `hypothetical` | 5 | Existing paths are potential only |

Paths traverse actual edge IDs in their stored direction. `broad` does not turn hypothetical or inferred links into confirmed facts. Each output path must resolve from the supplied company node to a target entity in the supplied event context.

## Run locally

From the repository root, using the project's pinned interpreter:

```powershell
$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T13/tests
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T13/fixtures/build_scenario_matrix.py
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T13/experiments/run_offline.py
```

The fixture builder and offline runner use shared dataset v1.0.1, which remains provisional and is not a gold dataset. See `fixtures/scenario_matrix.json` and `results/approach-comparison.json` for the frozen test contexts and comparison output.

## Status

Runnable experimental prototype. Strict DTO compatibility is checked for the three operation output models and the repository's semantic pair validators. This is not a production integration or a measured live-model result. Policy binding, direction semantics, and the action catalog still need owner decisions. See `TEST_REPORT.md`, `RESEARCH.md`, and `LIMITATIONS.md`.
