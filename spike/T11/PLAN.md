# T11 plan and status

## Experiment hypotheses

1. Rechecking an anchor can establish source and locator integrity, but cannot prove the source assertion true.
2. A prepared source-assertion relation can be audited independently from the claim's overall status.
3. Reposts with one `publisher_root_id` should not count as independent corroboration.
4. Contradictory current values should remain disputed; historical or unavailable sources should not be promoted to current claims.
5. A named synthetic owner policy can define a local review gate, but the gate must not set `confirmed` or create a universal reliability threshold.

## Scope

- Read-only logic under `spike/T11/**` only.
- Inputs: Framework v1 Evidence DTOs, the shared materialized Evidence read fixture, immutable synthetic source snapshots, a local hand-authored assertion annotation fixture, and the separately named synthetic policy.
- Dependencies: Python standard library, existing Pydantic contracts package, and pytest for tests. No new project dependency.
- No database, HTTP client, model, source crawl, persistent Evidence operation, or shared-contract change.

## Execution status

| Work | Status | Result |
|---|---|---|
| Read `Evidence.register` / `Evidence.read` operation cards and confirmed-statement requirements | Complete | `verified_anchor` is treated as anchor integrity only. |
| Pin shared input and local annotation fixture | Complete | Shared dataset v1.0.1, canonical hash recorded in fixture; both remain provisional. |
| Implement strict anchor integrity check | Complete | Exact document id, version, content hash, Unicode code-point span and quote hash; whole-artifact hash path. |
| Implement separate assertion and claim-status layers | Complete | Pre-annotated relations only; conflicts and unknowns remain explicit. Valid time and knowledge time use separate cutoffs; missing/invalid registration is fail-closed. |
| Deduplicate syndicated roots | Complete | Count distinct publisher roots; no score is calculated. |
| Exercise explicit test-only owner policy | Complete | Exact pinned id/version/canonical hash required; returns review eligibility only, never `confirmed`. |
| Unit/negative/boundary/provenance/security/reproducibility tests | Complete | 53 passed; includes bitemporal and caller-edited policy regressions; details in `TEST_REPORT.md`. |
| Research and limitations | Complete | Official sources and license distinction in `RESEARCH.md`. |
| Independent author-independent review | Complete for reviewed findings | HIGH late-registration and MEDIUM mutable-policy findings were independently re-checked; confirmation still requires a trusted owner policy and governed persistence/read integration. |
| Production Evidence owner integration | Out of scope | No storage/register/read implementation included. |

## Result classification

- Engineering quality: **PASS** on the pinned offline suite.
- Algorithm quality: **PRELIMINARY**; synthetic cases do not measure real-world factual accuracy.
- Integration readiness: **NOT READY**; DTO compatibility checks are limited to the existing Evidence read exchange and register input shape.
- Live model quality: **NOT MEASURED**.

The local annotation fixture remains version 1.0.0 and explicitly pins shared corpus v1.0.1/hash. Dataset identity and local fixture version are separate.
