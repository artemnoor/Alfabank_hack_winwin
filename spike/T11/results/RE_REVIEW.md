# T11 remediation — independent re-review

- **Review worktree / branch:** `C:\CodexData\worktrees\alfabank-review-t11-rerun` / `codex/review-t11-remediation-rerun`
- **Reviewed integration base:** `de0278378e1efd370f46c57c6c7d01fca27daebb`
- **Original findings:** `spike/T11/results/INDEPENDENT_REVIEW.md` (HIGH point-in-time knowledge cutoff; MEDIUM mutable owner-policy allow-list)
- **Scope:** read-only inspection and targeted reproduction of the original remediation; this report is the only intended change. No implementation or fixture edits were made.

## Result

| Original finding | Re-review result | Evidence |
|---|---|---|
| HIGH — a source published before `known_as_of` but collected/recorded after it was included in the historical assessment | **Not reproduced; remediation verified for the reviewed probes.** | Late registration now yields `unknown`, `applicable_as_of=false`, and `source_registered_after_knowledge_snapshot`. The owner-policy gate rechecks the same time slice. |
| MEDIUM — caller-edited `authorized_statement_ids` could pass a named synthetic policy | **Not reproduced; remediation verified.** | Changing only the allow-list produces `not_eligible` and `policy_content_hash_mismatch`, because the complete canonical policy is pinned to the code digest. |
| Automatic `confirmed` status | **Not present in the reviewed assessment path.** | `ClaimStatus` has no `confirmed` member; assessment and policy result expose `final_status="not_confirmed"`, including when the pinned test policy returns owner-review eligibility. |

No open CRITICAL or HIGH issue was reproduced in the requested remediation scope. This is a targeted re-review, not a claim that synthetic T11 annotations establish real-world truth or that T11 is production-ready.

## Reproductions

The original HIGH probe was repeated with `published_at=2026-10-13T08:00:00Z`, `collected_at=2026-10-15T08:00:00Z`, and both cutoffs at `2026-10-14T00:00:00Z`. Result: `status=unknown`, `applicable_as_of=False`, reasons include `source_registered_after_knowledge_snapshot`. Removing both `collected_at` and `recorded_at` also returns `unknown` / `False`, with `source_registration_time_missing`; publication time is not used as a registration-time substitute.

The original MEDIUM probe was repeated by changing only the pinned policy's `authorized_statement_ids` to `not-authorized-claim`. Result: `decision=not_eligible`, reason `policy_content_hash_mismatch`, `final_status=not_confirmed`. With the unchanged, authorized test policy and its eligible synthetic statement, the function returns `eligible_for_explicit_owner_review`, while both assessment and policy result remain `not_confirmed`.

The registered-time implementation uses the later of available `collected_at` and `recorded_at`; missing or malformed registration timestamps fail closed. The implementation separates the valid-time `published_at` cutoff from the knowledge-time registration cutoff. The relevant new regression tests cover late collection, missing registration, malformed/naive timestamps, later `recorded_at`, policy rechecking, and caller-edited policy content.

## Commands and results

Environment: pinned workspace Python 3.12.15, `-B`, pytest cache disabled, no network/model/database calls.

```powershell
$env:PYTHONPATH='spike/T11/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest spike/T11/tests -p no:cacheprovider -q
# 53 passed, 0 failed, 0 skipped

$env:PYTHONPATH='packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider -q tests/contracts
# 31 passed, 0 failed, 0 skipped

& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
# exit 0; 13 checks passed, 0 failed; five strict operation fixtures passed
```

The shared validator rewrote its report with identical content; `git status` and `git diff` confirmed no shared-file changes. The worktree was clean before this report was added. `git diff --check` passed.

## Remaining limits

- Dataset and assertions are synthetic, hand-annotated, and provisional; algorithm quality remains **PRELIMINARY** and live-model quality is **NOT MEASURED**.
- Anchor integrity only establishes that the cited span is present in the supplied snapshot. T11 does not establish source truth or entailment from the cited prose.
- The pinned owner policy is a local test gate, not a trusted production owner registry. Eligibility means a separate owner review may be considered; it does not confirm a fact.
- Integration readiness remains **NOT READY** pending production Evidence ownership/persistence, policy agreement, and separate integration review.
