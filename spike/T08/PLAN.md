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
4. Cover malformed responses, unknown labels, threshold handling, multi-label behavior, prompt injection, empty input, timeouts, and redirect refusal without network access.
5. Probe the official endpoint first; if access is available, run the synthetic-only pilot and store only sanitized labels, scores, model/version, timing, and token usage. If it is unavailable, record the sanitized failure and do not switch providers.
6. Report per-topic accuracy, per-event precision/recall/F1, uncertainty/review rates, and limitations.
7. Independently review architecture, taxonomy, and security before proposing any integration.

## Acceptance

- Taxonomy has 10–15 business-event categories and an explicit `other_uncertain` path.
- Corpus has 49 non-empty synthetic news cases plus local empty-input coverage; every event category has positive and negative examples, and the pilot includes uncertain-evidence and unlisted-event gold labels.
- No alternative classifier, external news API, or live article is used.
- All offline tests pass and no offline test can access the network.
- A live result is called a pilot only. It is not evidence of production-level quality or a calibrated threshold.

## Current results

- Offline fixture: 49 hand-labeled synthetic Russian news cases plus one locally rejected empty input; 10 named topics plus `other_uncertain` (11 Choice options) and 15 business-event labels. Each event has at least two positive examples.
- Offline unit suite: 33 tests pass. Ruff check and format check pass.
- Current taxonomy `0.3.0-spike` clarifies `legal_enforcement` as a distinct legal development and pins gold-label expectations for bankruptcy procedure, sanctions confirmation, and a separate creditor filing. The current taxonomy was not sent to the API.
- Official TypeSafe `GET /v1/models` returned HTTP 451. Two single-case synthetic classification POST attempts made with earlier taxonomy revisions (`0.1.0-spike` and `0.2.0-spike`) also returned HTTP 451; no Jev result was received. No Jev output or quality metrics are available. Russian-language model quality remains unmeasured.
- No application runtime, public contract, production dependency, or main-branch file is changed by this spike.
