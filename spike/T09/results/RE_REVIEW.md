# T09 remediation — independent re-review

- **Review worktree / branch:** `C:\CodexData\worktrees\alfabank-review-t09-rerun` / `codex/review-t09-remediation-rerun`
- **Reviewed integration base:** `3ec1934a8be4aaf1927334ce9c390d1f92bbe5b7`
- **Original report:** `spike/T09/results/INDEPENDENT_REVIEW.md`
- **Scope:** read-only review of the five original HIGH findings and the runtime policy-reference compatibility gap. No implementation, fixture, contract, or original-review files were changed.

## Result

The five requested HIGH probes no longer reproduce on this integration commit. The runtime policy-reference binding gap remains open and prevents integration readiness.

| Finding | Re-review result |
|---|---|
| T09-R1 — merge ignores incompatible event time | **Remediation verified for the original probe.** The merge path checks candidate time compatibility; the 2027 mention against 2026-10-01 records produced three `defer` decisions, no merge. The proposal passed `validate_resolution_pair`. |
| T09-R2 — disputed/disproved certainty and provenance are erased | **Remediation verified for the original probes.** A `disputed` or `disproved` predecessor blocks merge; a `disproved` incoming mention defers. The normal merge successor retained distinct `confirmed`/`observed` statement variants and their separate source refs. |
| T09-R3 — same-type events at distinct facilities stay in one aggregate | **Remediation verified.** The same-type two-fire aggregate split into two proposed records linked to the predecessor; pair validation passed. |
| T09-R4 — actor/object role inversion can attach | **Remediation verified for the original probe.** Swapping the mention actor/object arrays returned `defer`; pair validation passed. |
| T09-R5 — unrelated entity triggers correction and erases missing data | **Remediation verified for the original probe.** Replacing the supplier fact with `routes_through` a port did not clear `/event/successor_supplier`; the action was `defer`, not `correct`. |
| T09-R7 — declared policy ref is not bound to runtime policy | **Open compatibility gap.** The request carries an opaque `VersionedRef`; changing its ID alone leaves decisions unchanged, while changing the separately passed runtime window from 14 to 13 days changes `attach` to `create`. The implementation documents this and does not claim policy resolution. |

No open HIGH issue was reproduced among the five targeted probes. T09 remains **NOT READY for integration** until a trusted owner binds the request’s policy ref to approved runtime parameters (without changing the approved DTO absent agreement).

## Reproductions and implementation observations

- **Time scope:** changed incoming `effective_at` to `2027-01-01T00:00:00Z` and duplicate statement `valid_from` to `2026-10-01T00:00:00Z`, refreshing the modified EventRecord refs. All three decisions were `defer`; none was `merge`.
- **Certainty/provenance:** separately changed an existing duplicate statement to `disputed` and `disproved`; both runs returned only `defer`. Marking the incoming focus statement `disproved` also deferred. In the valid baseline merge, successor statements retained both `confirmed` and `observed` states and source refs for the distinct records. `_merge_statement_signature` includes both epistemic status and statement provenance.
- **Same-type split:** materialized one active aggregate with both fire mention IDs and the exact combined statements for `plant-north` and `plant-east`. T09 returned one `split` decision with two successors.
- **Role inversion:** exchanged `actors` and `objects` on the `same-export-ru-en` mention without changing its statements. It returned `defer`.
- **Correction scope:** removed the incoming `identifies_supplier` statement, supplied an unrelated `routes_through` port fact, and retained the predecessor’s supplier MissingDatum. It returned `defer`, not `correct`.
- **Policy ref:** changing only `ResolutionInput.policy.id` changed the proposal fingerprint but did not change decisions. With the same opaque ref, the separately supplied runtime policy window changed a boundary case from `attach` to `create`. This confirms the documented binding gap; the spike has no resolver/owner registry.

## Commands and results

Environment: pinned workspace Python 3.12.15, `-B`, pytest cache disabled; no network, external model, or database use.

```powershell
$env:PYTHONPATH='spike/T09/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider spike/T09/tests
# 113 passed, 0 failed, 0 skipped

$env:PYTHONPATH='packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider tests/contracts
# 31 passed, 0 failed, 0 skipped

& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
# 13 checks passed, 0 failed; all five materialized operation fixtures passed strict validation

$env:PYTHONPATH='spike/T09/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T09/experiments/evaluate.py
# 32/32 focus decisions; merge precision 1.0 and recall 1.0 (one positive merge case);
# false merges 0/31; false splits 0/31; defer 11/71 (0.15493)
```

The evaluator output `spike/T09/results/metrics-v1.json` remained byte-identical at SHA-256 `5E13118C5B9584F1E4A7979BE96851CDF7ACD13C330E15E784BF3CCD06295B39`. The shared validator report also remained unchanged. These metrics use 32 hand-authored provisional synthetic groups, not approved gold labels; the perfect in-sample focus agreement is not a production-quality estimate. Live model quality is **NOT MEASURED**.

## Remaining limits

- **Integration readiness: NOT READY** because policy-ref-to-runtime binding requires a trusted owner decision and mechanism. The local `ResolutionPolicy` is an experimental argument, not the resolved meaning of `ResolutionInput.policy`.
- **Algorithm quality: PRELIMINARY.** The inputs and expected properties are synthetic/provisional; only one positive merge case contributes to merge precision/recall.
- No production `Events.apply`, event store, policy registry, live text/model comparison, or external source service was exercised.
- The report is limited to the requested remediation probes plus the policy-ref gap; it does not claim a new full review of every T09 behavior.
