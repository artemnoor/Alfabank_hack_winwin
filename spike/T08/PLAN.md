# T08 spike plan — Jev Russian news classification

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

## Current final checks

- unittest: 86 passed, 0 failed, 0 skipped.
- Ruff check / format check: PASS.
- Offline runner: PASS; 0 classifier calls.
- Aggregate v4: 45 valid outputs, 50 pilot attempts, five failures including one legacy TypeSafe failure; metrics match v3.
- No live calls made in this final correction pass.
- Historical 451 diagnosis remains unknown.

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
