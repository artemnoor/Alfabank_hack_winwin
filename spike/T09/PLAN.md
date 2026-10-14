# T09 plan and status

| Work item | Status | Evidence / note |
|---|---|---|
| Read Events operation cards and pinned Pydantic semantics | Done | `Events.propose_resolution`, `Events.apply`, and `Events.read`; no contract edits |
| Pin independent shared data and materialize contract inputs | Done | 32 provisional cases; dataset v1.0.1/hash explicitly pinned; versioned path overrides remain constrained under spike/_shared |
| Candidate retrieval before resolution | Done | Exact event type/version; participant ID and time features; same-role name similarity only ranks/defer candidates |
| Implement six decision kinds | Done | create, attach, correct, merge, split, defer; proposal validates through Framework DTOs |
| Guard false merges and false splits | Done, regression-hardened | incompatible time scopes and status/provenance variants defer; same-type distinct facilities split; actor/object inversion defers |
| Preserve field-specific unknowns through correction | Done, regression-hardened | only a recognized matching field fact clears its old MissingDatum; unrelated prior unknowns carry into successor |
| Review MEDIUM lifecycle and ID collisions | Done | merged records are excluded from candidates; sanitized event IDs append a digest when normalization/truncation would collide |
| Resolve request policy reference | Compatibility gap | `ResolutionInput.policy` is a `VersionedRef`, not a parameter DTO; runtime thresholds remain explicit experimental config pending owner policy binding |
| Negative, incomplete, contradiction, boundary, provenance, security, metamorphic tests | Done | See `tests/` and actual counts in `TEST_REPORT.md` |
| Algorithm measurements | Done, preliminary | Metrics against hand-authored provisional case expectations only; see `results/metrics-v1.json` |
| Real text-similarity/embedding/LLM comparison | Not measured | The normative input DTO does not carry raw title/body; no live model or egress was used |
| Independent review and follow-up fixes | Remediation complete; re-review pending | HIGH regressions and MEDIUM lifecycle/ID findings addressed locally; independent reviewer must verify the final branch |
| Integration into Framework runtime or `Events.apply` | Out of spike scope | The prototype only proposes; no DB, mutation, or HTTP endpoint |

## Hypotheses checked

1. Exact identity and event facts can support safe `attach`; superficial title or
   display-name similarity cannot.
2. A candidate mismatch involving identity, event time, assertion certainty, or
   contradictory value should defer or create, not force a canonical merge.
3. `correct`, `merge`, and `split` must retain predecessor lineage and obey the
   published decision cardinalities.
4. An article may contain multiple events without requiring a `split`. A split
   is appropriate only when a single existing aggregate is being repaired;
   same-type distinct facility mentions are treated as distinct events.
5. Facts, certainty, source provenance, and time scope must survive a merge;
   field-specific correction must preserve unknowns it did not resolve.
6. Reproducible, local rules are useful as a baseline, but 32 synthetic groups
   do not establish production algorithm quality.

## Version and reproducibility

Current materialized fixture set `scenarios-v1.json` refers to shared dataset
`t09-t13-independent-v1`, version `1.0.1`, canonical SHA-256
`f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
The shared dataset remains provisional. The loader also verifies the
canonical content digest and the exact bytes digest declared by its manifest.
To switch to a reviewed shared version, provide explicit version, hash, dataset
path, and read-fixture path through the `T09_SHARED_DATASET_*` and
`T09_SHARED_FIXTURES_DIR` environment variables, then regenerate the local
fixture file before running tests. The default never resolves a moving branch
or latest alias.
