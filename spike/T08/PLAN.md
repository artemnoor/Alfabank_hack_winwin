# AIF spike plan: T08 Jev news classification

## Goal

Evaluate whether Jev can classify short Russian-language news using a project-owned, explicitly defined two-level taxonomy: one broad topic selected with `Choice`, plus independent business-event questions asked with `Noul`. Jev is the only classifier in this experiment. The corpus labels are manually authored evaluation truth, not model-generated labels.

## Boundaries

- Keep all prototype files under `spike/T08/`.
- Do not register an application implementation or change API, CLI, Playground, OpenAPI, fixtures, or production dependencies.
- Use synthetic news text only for live API requests. Never send real, unknown, or user-provided material.
- Use the official TypeSafe System One API for native `Choice` and `Noul`. Never send the TypeSafe key to a different host or follow redirects.
- Treat taxonomy and thresholds as experimental proposals pending review.
- Keep legal-event labels distinct from the primary event when the court or regulator is only carrying out its ordinary procedure; mark `legal_enforcement` only for a separate legal development.
- Empty text is rejected locally and is never sent to Jev.

## Work items

1. Define versioned topic and event labels with positive and negative boundaries.
2. Create 30–50 synthetic Russian examples with hand-labeled topics, events, and uncertainty cases.
3. Implement strict request and response validation for Jev `Choice`/`Noul`.
4. Cover malformed responses, unknown labels, threshold handling, multi-label behavior, prompt injection, empty/oversized input, timeouts, connection errors, HTTP status handling, oversized responses, and redirect/proxy refusal in an offline suite with socket entrypoints blocked.
5. Probe the official endpoint first; if access is available, run the synthetic-only pilot and store only sanitized labels, scores, model/version, timing, and token usage. If it is unavailable, record the sanitized failure and do not switch providers.
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
- Current offline suite: 66 tests pass, 0 fail, 0 skipped. Ruff check and format check pass (10 Python files checked). Test coverage includes response contract rules, malformed JSON, socket guard, transport errors/no retries, formula arithmetic, threshold sweeps, deep-set hashes/labels, boundary coverage, and metamorphic gold relations. Offline metric tests use controlled fixtures and do not measure Jev quality.
- Current official docs confirm the `POST /v1/systemone` Bearer request shape, `jev-latest` alias (currently resolving to `jev-1.13.0`), `Choice`/`Noul`, required response `usage`, Choice confidence formula, 255 Choice option limit, and no documented total-question limit. The request shape is docs-compatible; no successful server response has been observed.
- Saved API evidence: authenticated `GET /v1/models` returned 451 and one synthetic POST for each of taxonomy versions 0.1.0 and 0.2.0 returned 451. The 451 source and cause remain unknown; no body or request ID was saved. The current 0.3 taxonomy and the 160-case set were not sent. This audit made zero live API calls.
- Model quality, latency, token usage, request cost, calibration, stability, category precision/recall/F1, and prompt-injection behavior are **NOT MEASURED**. The model provider says English is Jev’s strongest language and instructs users to test other languages; Russian use remains an empirical open question.
- Compatibility with Framework `Understanding.classify` is partial only. The spike is an isolated experiment and does not implement normative DTO `allowed_codes`, taxonomy references, `multi_label`, result DTO, provenance, policy, Run History, or replay.
- No application runtime, public contract, production dependency, or main-branch file is changed by this spike. Full details: `TEST_REPORT.md` and `TEST_REPORT.json`.
- No application runtime, public contract, production dependency, or main-branch file is changed by this spike.
