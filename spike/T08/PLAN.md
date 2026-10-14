# AIF spike plan: T08 Jev news classification

## Goal

Evaluate whether Jev can classify short Russian-language news using a project-owned, explicitly defined two-level taxonomy: one broad topic selected with `Choice`, plus independent business-event questions asked with `Noul`. Jev is the only classifier in this experiment. The corpus labels are manually authored evaluation truth, not model-generated labels.

## Boundaries

- Keep all prototype files under `spike/T08/`.
- Do not register an application implementation or change API, CLI, Playground, OpenAPI, fixtures, or production dependencies.
- Use synthetic news text only for live API requests. Never send real, unknown, or user-provided material.
- Use the Jev System One API through Polza AI for native `Choice` and `Noul`. Read only `POLZA_AI_API_KEY`; never fall back to a direct TypeSafe host or follow redirects.
- Treat taxonomy and thresholds as experimental proposals pending review.
- Keep legal-event labels distinct from the primary event when the court or regulator is only carrying out its ordinary procedure; mark `legal_enforcement` only for a separate legal development.
- Empty text is rejected locally and is never sent to Jev.

## Work items

1. Define versioned topic and event labels with positive and negative boundaries.
2. Create 30–50 synthetic Russian examples with hand-labeled topics, events, and uncertainty cases.
3. Implement strict request and response validation for Jev `Choice`/`Noul`.
4. Cover malformed responses, unknown labels, threshold handling, multi-label behavior, prompt injection, empty/oversized input, timeouts, connection errors, HTTP status handling, oversized responses, and redirect/proxy refusal in an offline suite with socket entrypoints blocked.
5. Probe Polza with one pinned synthetic case. Any larger paid batch requires an explicitly approved budget; store only sanitized labels, scores, model/version, timing, token usage, and `cost_rub`. Never switch classifier or use live network fallback.
6. Report per-topic accuracy, per-event precision/recall/F1, uncertainty/review rates, and limitations.
7. Independently review architecture, taxonomy, and security before proposing any integration.
8. Maintain the original fixed baseline unchanged and add a separately versioned 150–200-case synthetic set split into benchmark, boundary, metamorphic, and holdout-control files.

## Acceptance

- Taxonomy has 10–15 business-event categories and an explicit `other_uncertain` path.
- Corpus has 49 non-empty synthetic news cases plus local empty-input coverage; every event category has positive and negative examples, and the pilot includes uncertain-evidence and unlisted-event gold labels.
- The deep evaluation artifact contains 150–200 synthetic cases with exact manifests; its labels are independently adjudicated before supporting quality claims, and its D split is never used for tuning.
- No alternative classifier, external news API, or live article is used.
- All offline tests pass; the test module blocks standard Python socket entrypoints and verifies the guard. This is a process-level test guard, not a sandbox guarantee against arbitrary native code.
- A live result is called a pilot only. It is not evidence of production-level quality or a calibrated threshold.

## Current results

- Baseline `corpus.json` remains unchanged at 49 synthetic news cases plus one locally rejected empty input. Taxonomy `0.3.0-spike` remains unchanged at 11 topic options and 15 business-event labels.
- New `experiments/deep-v1/` contains 160 cases: A 76, B 36, C 24, D 24 (158 non-empty). Its labels are single-annotator drafts. B24 has an unresolved rule conflict and must be excluded from scoring pending adjudication. D is separate and unused for tuning, but its labels are visible and were seen by its author; it is not a blind holdout.
- Current offline suite: 70 tests pass, 0 fail, 0 skipped. The test file covers response contract rules, malformed JSON, socket guard, no retry/fallback, Polza key/model pinning, cost metadata, partial-run metrics suppression, status-only sanitized provider errors, threshold sweeps, deep-set hashes/labels, boundary coverage, and metamorphic gold relations. Offline metric tests use controlled fixtures and do not measure Jev quality.
- Official Polza docs specify `POST https://polza.ai/api/v1/systemone`, Bearer auth, Jev model ID `typesafe/jev`, optional `provider`, `usage.cost_rub`, up to 255 Choice options and 1–256 questions. Polza docs list the resolved response model as `jev-1.13.0`. Choice confidence has no documented arithmetic formula; the harness validates only its numeric range.
- One historical live request to Polza succeeded on pinned synthetic case `e01-supply-rail`, returning a schema-valid Jev `jev-1.13.0` response. Usage: 5,905 input tokens, 492 output tokens, 0.10391619 ₽, 844 ms. It matched the draft topic/event labels but emitted an unlisted-event score of 0.53 and was routed to review. This is a one-case observation, not a quality metric; aggregate metrics are withheld for partial runs. The current request hash matches the recorded smoke, but current client/runner code has not made another live request. The request sets `provider.allow_fallbacks=false`, but effective provider-side routing/fallback behavior was not independently verified.
- The live runner now defaults to one request; `--max-calls` is a per-invocation cap, and cumulative usage across invocations is not persisted. Do not repeat billable calls without separately approved budget.
- Historical 451 statuses came from the previous direct TypeSafe route and do not diagnose Polza. One additional failed request to the old route was caused by a regression-test fixture exposing the legacy TypeSafe key to the old runner; only a sanitized error was saved. The test now proves that `POLZA_AI_API_KEY` is required and legacy variables cannot trigger a request.
- Model quality, per-category precision/recall/F1, calibration, stability, and prompt-injection behavior remain **NOT MEASURED**. One smoke case cannot establish Russian classification quality. The expanded corpus still has single-annotator draft labels, non-blind D, and B24 ambiguity.
- Compatibility with Framework `Understanding.classify` is partial only. The spike is an isolated experiment and does not implement normative DTO `allowed_codes`, taxonomy references, `multi_label`, result DTO, provenance, policy, Run History, or replay.
- No application runtime, public contract, production dependency, or main-branch file is changed by this spike. Full details: `TEST_REPORT.md` and `TEST_REPORT.json`.
- No application runtime, public contract, production dependency, or main-branch file is changed by this spike.
