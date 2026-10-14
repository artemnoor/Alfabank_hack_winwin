# Independent review — T09 Events

**Review target:** `codex/review-t09-events`, reviewed T09 implementation at `66832de6d4b53237e6bb66e508e4641c27092efe` against `c5f32e51a8745c390df821830abd684981b6ce0b` (T09-only diff). Shared input is provisional dataset v1.0.1. This report is independent of the T09 author; a separate read-only reviewer checked the normative-specification axis. No implementation, fixtures, contracts, or other review files were changed.

**Recommendation:** do not mark T09 integration-ready until the HIGH findings are fixed and regression-tested. No CRITICAL finding was identified.

## Findings

### HIGH — T09-R1: merge path ignores known event-time incompatibility

`retrieve_candidates` computes `time_compatible=False` when the event-time delta exceeds the policy window (`spike/T09/src/t09_events/resolution.py:287-318`). The duplicate-record merge path (`:669-706`) consumes exact shared candidates without checking that flag; only the later single-candidate path checks it (`:745`).

**Reproduction:** start with `merge-duplicate-export-records`; set `validity.valid_from` to `2026-10-01T00:00:00Z` on the duplicate records and incoming mention statements, set incoming mentions’ `effective_at` to `2027-01-01T00:00:00Z`, and recompute modified EventRecord refs. `propose_resolution` returns `merge`; `validate_resolution_pair` accepts the proposal. This is outside the default 14-day window and collapses temporally distinct/recurring events. Apply the time-compatibility rule to merge candidates or defer when the records cannot be safely separated.

### HIGH — T09-R2: `disproved` certainty is ignored and merge erases epistemic status

`_uncertain` defers hypothetical/disputed/unknown but omits the valid `disproved` enum (`resolution.py:402-410`; `_generated.py:205-212`). `_statement_signature` drops `epistemic_status` (`:201-218`), and successor deduplication then retains one version of the same assertion (`:439-477`).

**Reproduction:** in `merge-duplicate-export-records`, change the incoming `restricts_export` statements to `disproved`. The proposal still returns `merge`; the successor keeps the prior confirmed assertion and loses the incoming disproved state. Marking an existing duplicate’s same assertion disputed also does not prevent that merge. This lets a refuted claim support canonical merge and destroys the conflict/uncertainty distinction. Preserve certainty distinctions and defer or use an explicit resolution policy when statuses conflict. This conflicts with the contract rule that conflicting claims are preserved (`docs/specs/framework-v1/02-contracts.md`, Statement row) and with Events.apply’s requirement for explicit trusted owner policy (`docs/specs/framework-v1/03-operations.md:175`).

### HIGH — T09-R3: distinct same-type events can remain attached to one aggregate

The split precondition requires at least two event types (`resolution.py:628-632`). Event kind is not a sufficient partition key: two fires at different facilities, or two stops at different plants, can share one event type. The Events decision contract permits one target to have multiple successors (`docs/specs/framework-v1/02-contracts.md`, EventDecision row).

**Reproduction:** use the two mentions from `fire-same-title-north-east`, materialize one existing aggregate containing both mentions and both exact fact sets, then propose resolution. The result is two `attach` decisions to the same aggregate, accepted by `validate_resolution_pair`, instead of a split (or a safe defer). The aggregate continues to represent two independently identified fires. Partition exact source facts/lineage without requiring distinct event taxonomy, or defer rather than attaching both.

### HIGH — T09-R4: actor/object role inversion can still attach

Candidate identity is flattened across actor and object roles (`resolution.py:139-140`, `:275`); identity-conflict checks compare only same-role IDs (`:413-438`). `_facts_are_exact` can then match unchanged statements even if the mention’s explicit participant roles contradict them.

**Reproduction:** in `same-export-ru-en`, swap the mention’s `actors` and `objects` arrays while leaving its statements unchanged. Resolution still returns `attach` to `event-export-x-mk7`; the proposal passes `validate_resolution_pair`. This inconsistent role assignment must be rejected/deferred; role-preserving identity and consistency between mention participants and statements must be validated before attach/merge.

### HIGH — T09-R5: unrelated new entity can trigger `correct` and erase prior unknowns

`_fills_missing_detail` treats any added entity-valued statement as filling a missing path whose name contains supplier/component/facility/site/route/port (`resolution.py:334-383`), without checking predicate or entity kind. `_record_payload` replaces predecessor `missing_data` with only the incoming mention’s list (`:439-477`).

**Reproduction:** in `historical-supplier-change`, remove the incoming `identifies_supplier` statement, add an unrelated entity-valued `routes_through -> port-a1`, and leave the existing `/event/successor_supplier` missing datum on the predecessor. T09 proposes `correct` although no successor supplier was supplied; the successor also drops the prior missing datum. Require semantic path-to-predicate/entity matching and preserve unresolved predecessor unknowns unless the exact datum is supplied.

### MEDIUM — T09-R6: historical merged/split predecessors remain resolution targets

Candidate retrieval iterates the snapshot’s events without excluding non-active lifecycle records (`resolution.py:252-322`). The normative apply contract explicitly preserves predecessors with lifecycle after merge/split (`docs/specs/framework-v1/03-operations.md:175`), and Events.read snapshots may include history.

**Reproduction:** in `same-export-ru-en`, set the existing record lifecycle to `merged`. T09 still proposes `attach` to that historical event, and the pair validator accepts it. Exclude historical records from canonical candidates or surface them only as lineage context.

### MEDIUM — T09-R7: declared versioned resolution policy is not bound to behavior

`ResolutionInput.policy` is a `VersionedRef` (`packages/contracts/src/alfalab_contracts/_generated.py:1222-1229`). `propose_resolution` includes this ref in the proposal ID, but decision thresholds come from a separate runtime `ResolutionPolicy` argument (`resolution.py:596-615`). A request can therefore name one policy while executing the default or another policy without an explicit binding check. Resolve the declared version/hash to the runtime policy or reject a mismatch; do not silently treat the ref as descriptive metadata.

### MEDIUM — T09-R8: valid mention IDs can collide after output-ID sanitization

`_safe_id` replaces disallowed characters (`resolution.py:488-490`), so valid IDs `mention/1` and `mention-1` normalize to the same generated event-ID suffix. A shape-valid two-mention request then raises Pydantic `ValidationError` for duplicate proposed event IDs instead of returning a safe proposal/defer. Use collision-resistant encoding or handle the collision explicitly.

### LOW — T09-R9: test count disagrees within the report

`spike/T09/TEST_REPORT.md:11` reports 96 passed, while its Engineering quality row at line 47 says 95. The executed count is 96; align the documentation.

## Reposts and corroboration

The 11-mention `same-export-ten-reprints` fixture produces 11 attach decisions and retains separate evidence refs. The count of reposts is not used as a candidate score or certainty upgrade. The duplicate-record merge fixture can nevertheless merge using repost-derived mentions, and the result’s refs are not clustered by source root. Treat those refs as provenance references, not independent corroboration; independence and source trust belong to the Evidence/trusted-owner policy. No false merge driven solely by repost count was observed in these cases.

## Verification performed

Pinned interpreter: Python 3.12.15 / Pydantic 2.14.1. Commands run from the review worktree:

```powershell
$env:PYTHONPATH = 'spike/T09/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T09/tests
# 96 passed, 0 failed, 0 skipped

$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider tests/contracts
# 31 passed, 0 failed, 0 skipped

& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
# 13 passed checks, 0 failed; shared dataset hash sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725

$env:PYTHONPATH = 'spike/T09/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T09/experiments/evaluate.py
# focus decisions 32/32; merge precision/recall 1/1 on one positive merge case; 0/31 provisional non-merge false merges; 11/71 defers
```

The evaluator was repeated; `spike/T09/results/metrics-v1.json` remained byte-identical (SHA-256 `5E13118C5B9584F1E4A7979BE96851CDF7ACD13C330E15E784BF3CCD06295B39`). `validate_resolution_pair` accepted each reproduced shape-valid proposal, showing that DTO shape/cardinality validation does not catch the semantic defects above. `git diff --check c5f32e5..HEAD -- spike/T09` passed. No live model, network service, or real-news quality experiment was run.

## Quality assessment

- **Engineering:** prototype and suite execute deterministically; DTO compatibility is shape-checked. The 96 passing tests do not cover the reproduced semantic failures.
- **Algorithm:** **PRELIMINARY**. The 32 groups are hand-authored provisional synthetic cases; merge precision/recall are each measured on a single positive merge case, without an independent gold corpus or real news. Model quality is **NOT MEASURED**.
- **Integration:** **NOT READY** pending HIGH fixes, lifecycle/policy handling, and another independent review. No production state or contracts were changed by this review.