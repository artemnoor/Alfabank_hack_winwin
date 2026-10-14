# T08 spike plan — Jev Russian news classification

## Current status — 2026-10-15

- Policy v2.1 is frozen as an experimental routing rule for the saved pilot. It produced 40 unconfirmed candidates in 32/45 successful responses and no evidence/unlisted review tasks at the configured 0.80 cutoffs. It also produced 6 candidate FP and 7 FN disagreements with preliminary labels; this does not establish safe automation.
- Offline error audit covers all 6/7 disagreements. Taxonomy 0.4.1 is a separate unapproved, untested proposal; source taxonomy 0.3 and saved Jev outputs remain unchanged.
- The human annotation packet now contains all 49 non-empty baseline stories without source IDs, draft labels, or model outputs. It is blind to saved model answers, but not to the repository owner; no human annotators have completed it.
- The separate 60-story visible validation set is unlabelled, unscored, and cannot become a blind benchmark because its inputs were visible to developers.
- **Ready for T09 experimental handoff only. Not production-ready.** No runtime/OpenAPI integration or new Jev requests were made.
- Latest checks: 118 offline unit tests and 19 Policy/visualization/Playwright tests; Ruff, offline runner and reproducibility checks passed. See `TEST_REPORT.md` and `TEST_REPORT.json`.

## Quality improvement pass — 2026-10-14

- Reproduced v4 from stored outputs and preserved original corpus/taxonomy hashes. No live API calls were made.
- Added a versioned offline tri-state Noul interpretation and case-level calculation of current review triggers. Exact status: 42/45 review; active reasons overlap (Choice 5, event band 24, insufficient evidence 17, unlisted 32); 28/42 have multiple reasons.
- Added counterfactual coverage/risk tables; they are not threshold recommendations and are not production-ready.
- Added detailed error review, human adjudication packet, deep-v1 structural audit, benchmark freeze plan and a separate v0.4 taxonomy proposal. Source v0.3, original corpus and saved responses remain unchanged.
- Added offline regression tests for aggregation, missing cases, review triggers, tri-state boundaries, no-network analysis, spent-budget refusal, corpus hashes and proposal separation.
- Current statuses after the final offline pass: engineering quality **PASS** (118 unit tests, 19 browser/policy tests, Ruff, offline runner and artifact checks); current-revision API compatibility **BLOCKED** pending an authorized live verification; model quality **NOT MEASURED FOR DECISION**; T09 experimental candidate handoff **READY**, production integration **NOT READY**.

## Goal and limits

Оценить единственный classifier Jev с project-owned taxonomy: одна общая тема через Choice и независимые бизнес-события через Noul. Изолированно в spike/T08. Только synthetic stories; никакого main runtime, OpenAPI, другого classifier или live real news.

## Completed implementation and review

- Polza System One client pins official HTTPS endpoint, Bearer env key, typesafe/jev, request fields, Choice/Noul validation including the official Choice confidence formula, usage schema, bounded timeout/response, allowlisted synthetic hashes, redirect/proxy refusal, no retries, and sanitized failures.
- Offline test module blocks ordinary Python socket entrypoints during offline suite.
- Taxonomy 0.3.0-spike and original corpus remain unchanged and hash-pinned.
- Separate deep corpus has 160 synthetic cases across A/B/C/D. Jev was not called on it. Labels are single-author drafts, B24 is unresolved, D is visible/nonblind.
- Added aggregate v4 with source/report hash checks, partial-result accounting, mock-transport metrics suppression, aggregate-mode assertion, historical failed-call accounting, explicit unknown failed-call billing, and official Choice confidence validation.
- Cumulative attempt ledger now seeds all 49 baseline request hashes and the known legacy TypeSafe POST, so a fresh state reflects the exhausted 50-attempt pilot. Existing local Windows state was reconciled to 50. Three older TypeSafe HTTP 451 route checks are outside the pilot ledger; the overall known history is 53 calls if those share the same cap. Ledger is still best-effort local state and can be reset/edited.
- Added the same Choice-confidence consistency validation to the live response parser and result aggregator. All 45 stored responses pass the formula check within rounding tolerance; the current client revision did not make a live call.
- Corrected independent-review record: e34/e35 are event-label boundary questions, not topic ties; model-blind label discussion is kept separate from model metrics.
- Added concurrent ledger reservation regression test (24 parallel local reservations, no network).
- Copied previous report v1.2.0 unchanged into results/archive before writing final versioned report.

## Earlier API pilot verification (historical snapshot; superseded by current quality pass)

- At that time: unittest 86 passed, Ruff and offline runner passed.
- Aggregate v4: 45 valid outputs, 50 pilot attempts, five failures including one legacy TypeSafe failure; metrics match v3.
- That historical run is preserved in `results/archive/TEST_REPORT-2.1.0-pre-quality.*`.
- Historical 451 diagnosis remains unknown.

Current tests and calculations are recorded in `TEST_REPORT.md`, `TEST_REPORT.json`, and `QUALITY_ANALYSIS.json`. Report version 3.0.0 is preserved in `results/archive/TEST_REPORT-3.0.0-pre-policy-v2.1-handoff.*`; the current report records the 2026-10-15 T09-handoff preparation.

Detailed results: TEST_REPORT.md; machine details and metrics: TEST_REPORT.json.

## Live pilot facts

Jev 1.13.0 was returned by 44 staged Polza responses and the earlier pinned smoke. The current client validation and runner differ from the live-tested source revision; request hashes remain pinned, and all stored responses were revalidated offline. No live retry was made.

Partial metrics for 45/49 baseline outputs: topic accuracy 31/45 (0.689), event micro-F1 0.840, macro-F1 0.808, multi-label exact 34/45 (0.756), 42/45 uncertain/review. They are conditioned on single-author draft labels and success-only coverage. Cost 4.63313107 RUB is known only for successful response usage; failed request cost is unknown. They do not prove quality or calibration.

## Open gates before any future integration

1. Adjudicate e33 and topic tie-breaks independently; retain current baseline unchanged.
2. Make a new versioned gold set with blind holdout; do not tune on D.
3. If another live evaluation is desired, obtain an explicit new budget/protocol; never infer failures from sanitized errors or retry automatically.
4. Design and test mapping to normative Understanding.classify DTO, trusted policy, provenance, history and replay boundaries.
5. Evaluate review/abstention usability and provider identity/fallback claims before discussing production use.

Do not start later framework stages or integrate this prototype automatically.
