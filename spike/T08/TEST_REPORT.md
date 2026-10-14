# T08 — Jev: offline quality improvement report

**Snapshot:** 2026-10-14
**Branch:** `codex/spike-t08-jev-news-classification`
**Scope:** `spike/T08` only. No live Jev/API requests in this pass. Runtime, OpenAPI, main and other stages were not changed.

## Four independent verdicts

| Area | Verdict | What it means |
|---|---|---|
| Engineering quality | **PASS** | The offline analysis, input/hash checks, test suite and reports reproduce. |
| API compatibility | **PASS WITH LIMITS** | Historical saved Polza responses confirm that earlier client revision reached a Jev-compatible path. The current source revision was not live-tested; upstream identity is not cryptographically attested. |
| Model quality | **NOT MEASURED FOR A DECISION** | Current numbers are partial descriptive metrics on synthetic stories and draft labels from one author. No human-adjudicated blind benchmark exists. |
| Integration readiness | **NOT READY** | There is no runtime DTO adapter or production policy/provenance/history/replay integration. |

**Recommendation:** do not let Jev classify Russian business news automatically yet. Keep the spike isolated and require human review. Quality is not established.

## Fresh checks in this pass

| Check | Result |
|---|---|
| `python -m unittest discover -s spike/T08 -p "test_*.py" -v` | **110 passed, 0 failed, 0 skipped** |
| `ruff check spike/T08` | **PASS** |
| `ruff format --check spike/T08` | **PASS**, 17 Python files checked |
| `python spike/T08/run_spike.py` | **PASS**, 0 classifier calls; 49 non-empty plus 1 locally rejected empty case |
| `python spike/T08/quality_analysis.py --check` | **PASS**, machine analysis reproduces byte-for-byte |
| `python spike/T08/deep_corpus_audit.py --check` | **PASS**, deep corpus audit reproduces |
| Historical aggregate rebuild from pinned smoke + 8 staged files | **PASS**, 45 outputs and every field matches v4 except generation timestamp; temporary output removed |
| New Jev API requests | **0**, as required |

The offline tests prohibit standard Python network entrypoints and test that an exhausted live ledger refuses before calling the classifier. This is an application-level guard, not an operating-system egress firewall.

## What the saved Jev answers show

The original baseline and its results were kept unchanged. Hashes:

- Baseline corpus: `592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d7`
- Taxonomy `0.3.0-spike`: `855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d`
- Saved aggregate v4: `a5e95d2367cbe81fa62665e7ef42b201316136c6c08dbac23c35798996e82286`

There are 45 saved successful answers for 49 non-empty baseline stories. Missing: `e23-recall-battery, e35-multi-labor-investment, e41-uncertain-sanctions-talk, e43-uncertain-vague-delivery`. Missing calls are not counted as model false negatives.

| Metric against draft labels | Result |
|---|---:|
| Topic accuracy | 31/45 = 68.9% |
| Event micro precision / recall / F1 | 85.0% / 82.9% / 84.0% |
| Event macro F1 | 80.8% |
| Exact event-set match | 34/45 = 75.6% |
| Historical result status `uncertain/review` | 42/45 = 93.3% |
| Unlisted-event recall | 0/1; one draft positive only |
| `legal_enforcement` recall | 0; no positive answer for 3 draft positives |
| `shortage_capacity_constraint` recall | 1/3 |

The 45-answer descriptive metrics are not a valid independent estimate: labels are single-author drafts, categories have very small support, 4 outputs are missing, and the provider response origin is not signed.

### Errors against the current draft labels

- **14 topic mismatches.** Full text, intended labels, Jev choices and possible annotation disputes are listed in [ERROR_ANALYSIS.md](ERROR_ANALYSIS.md). IDs: e06-production-fire (industry_trade_supply → business_companies), e07-price-polymer (economy_finance → business_companies), e09-trade-export (politics_government → industry_trade_supply), e10-trade-import (law_regulation → industry_trade_supply), e12-sanctions-assets (politics_government → law_regulation), e14-regulation-tax (economy_finance → law_regulation), e18-labor-layoffs (business_companies → labor_employment), e24-recall-food (health → law_regulation), e28-disaster-drought (energy_resources → environment_disasters), e29-investment-plant (industry_trade_supply → business_companies), e33-multi-price-shortage (economy_finance → industry_trade_supply), e42-uncertain-price-forecast (economy_finance → energy_resources), e45-injection-rumor (industry_trade_supply → business_companies), e47-unlisted-contract-award (business_companies → politics_government).
- **6 event false positives:** e03-shortage-cells:production_operational_disruption, e27-disaster-flood:production_operational_disruption, e25-legal-fine:sanctions, e09-trade-export:regulation_tax_change, e10-trade-import:regulation_tax_change, e32-multi-fire-supply:environment_disaster_impact.
- **7 event false negatives:** e03-shortage-cells:shortage_capacity_constraint, e33-multi-price-shortage:shortage_capacity_constraint, e18-labor-layoffs:corporate_transaction_restructuring, e25-legal-fine:legal_enforcement, e26-legal-investigation:legal_enforcement, e34-multi-insolvency-legal:legal_enforcement, e28-disaster-drought:environment_disaster_impact.
- `e33`, `e34`, and `e35` need human adjudication. The AI reviewer’s model-blind first opinion is not human gold. Jev had no saved response for e35.

## Why 93.3% were sent to review

The triggers overlap; do not add these counts as if they were distinct cases:

| Active reason | Cases |
|---|---:|
| Choice confidence below 0.5 | 5 |
| Event score in the gray band (0.2–0.8) | 24 |
| Insufficient-evidence score above 0.2 | 17 |
| Unlisted-event score above 0.2 | 32 |

There are 28 cases with multiple triggers and 14 with one. Single-trigger cases: {'choice': 0, 'event_scores': 1, 'uncertainty': 5, 'unlisted': 8}. Combination counts: `{"choice+event_scores": 1, "choice+event_scores+unlisted": 1, "choice+uncertainty": 2, "choice+unlisted": 1, "event_scores": 1, "event_scores+uncertainty": 1, "event_scores+uncertainty+unlisted": 7, "event_scores+unlisted": 13, "uncertainty": 5, "uncertainty+unlisted": 2, "unlisted": 8}`.

Important: Noul’s middle band is **abstain**, not a calibrated probability. The saved unlisted signal had 33 abstains and 12 negatives, with no positive; the insufficient-evidence signal had 3 positive, 14 abstain and 28 negative. The active historical rule treats any score above 0.2 as review. For `other_uncertain`, legacy logic ignores the unlisted/event gates, which explains raw trigger counts of 5/25/17/33 versus active counts of 5/24/17/32.

### Counterfactual policy snapshots

All rows reuse the same 45 partially observed cases and single-author draft labels. These are diagnostic calculations, not recommendations or calibrated risk estimates.

| Policy | Auto accepted | Topic accuracy | Event F1 | Exact event set | Case error rate | Provisional consequential FP |
|---|---:|---:|---:|---:|---:|---:|
| Current strict gate | 3/45 | 66.7% | 80.0% | 66.7% | 33.3% | 0 |
| Ignore only insufficient-evidence gate | 8/45 | 87.5% | 80.0% | 87.5% | 12.5% | 0 |
| Ignore both evidence signal gates | 18/45 | 83.3% | 90.0% | 88.9% | 22.2% | 0 |
| Choice only | 40/45 | 75.0% | 82.7% | 72.5% | 40.0% | 3 |

The 93.3% review rate is partly a consequence of how we interpret abstention scores, but lowering the gates does not establish a safe automation rate. Choice-only accepts 40 cases and has 16 draft-label case errors plus 3 provisional high-consequence false positives. Changing only the unlisted gate does not auto-accept e47 because its corporate-transaction event score remains gray. Full per-threshold tables are in [THRESHOLD_COMPARISON.md](THRESHOLD_COMPARISON.md); machine calculations are in [QUALITY_ANALYSIS.json](QUALITY_ANALYSIS.json).

## Taxonomy, labels and benchmark

- Taxonomy v0.3 remains unchanged. A separate `0.4.0-spike` proposal refines boundary definitions but has the same codes/questions; it has not been tried with Jev and is not approved. See [TAXONOMY_PROPOSAL.md](TAXONOMY_PROPOSAL.md).
- The deep synthetic corpus contains 160 cases (A=76, B=36, C=24, D=24), with all 11 topic and all 15 event codes represented. Jev was not run on it.
- D is visible to the developer and is **not blind**. All labels are one-author drafts. Duplicate and near-duplicate flags are documented in [DEEP_CORPUS_AUDIT.json](DEEP_CORPUS_AUDIT.json); B24 needs adjudication.
- No second human annotator or adjudicator participated. [HUMAN_REVIEW_PACKET.md](HUMAN_REVIEW_PACKET.md) is awaiting the owner’s decisions; do not rewrite original labels.
- [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md) specifies two independent human annotators, adjudication, evidence spans and frozen blind data.

## API, cost, latency and security

The historical Polza route was `POST https://polza.ai/api/v1/systemone`, requested model `typesafe/jev`, with 45 saved answers reporting Jev 1.13.0. This pass made no request; current client compatibility has not been rechecked live. There were 4 sanitized failures in the staged run and their causes are unknown. The earlier three TypeSafe route checks returned HTTP 451; the root cause is **unknown**. No raw body was retained and no geo/proxy workaround was attempted.

Historical successful responses: mean latency 1298.58 ms, median 860 ms, nearest-rank P95 1313 ms (small n=45); reported usage was 285,443 tokens and 4.63313107 RUB. Failed-call cost is unknown. The full known request history is 50 pilot attempts plus 3 separate route checks if both count against one budget; no additional call was made here.

The runner uses a fixed endpoint, pinned synthetic request hashes, bounded responses/timeouts, refuses redirects, disables environment proxy discovery, does not retry and sanitizes errors. Keys, article texts, raw prompts, provider bodies and raw exceptions are not added to saved reports. Stored API origin/fallback cannot be independently attested. Offline socket guards do not replace an OS-level network block.

## Framework compatibility and limits

The spike uses one fixed-choice topic and independent event questions with finite category codes. It is **not** an implementation of the normative `Understanding.classify` DTO.

| Normative area | Compatibility | Remaining work |
|---|---|---|
| Jev is the only classifier; finite topic/event codes | **PARTIAL** | Spike uses Jev and fixed codes; no runtime dependency adapter exists. |
| `ClassificationInput`, material, taxonomy, `allowed_codes`, `multi_label` | **NOT COMPATIBLE** | Add a reviewed DTO-to-request adapter without changing OpenAPI. |
| `ClassificationOutput`, topics, `event_hints`, status, `missing_data` | **NOT COMPATIBLE** | Map and validate the Jev response against normative output invariants. |
| Trusted policy, provenance, history, replay | **NOT IMPLEMENTED** | Integrate only through existing runtime boundaries and policy gates. |
| Real stability, prompt-injection behavior, calibration | **NOT VERIFIED** | Requires a separately approved live protocol and a blind human benchmark. |

It must not be connected to runtime without a separate reviewed adapter and user approval.

Not measured: Jev on the 160-case corpus, live repeated/metamorphic stability, calibrated scores, real-world accuracy, current source revision against the live API, provider-side prompt-injection resistance, actual 451 cause, failed-call billing, and upstream/fallback attestation.

## Independent review and next action

AI Factory reviews used `/root/review_triggers`, `/root/blind_gold_taxonomy`, `/root/threshold_stats`, and `/root/final_review_t08_quality`. The final read-only review independently checked both 7-row review-gate sweeps, all 45 status reconstructions, pinned hashes and report consistency. It found doc synchronization and e47 wording issues; README, review log, threshold text and regression tests now cover them. AI opinions are not human labels. Details: [AI_REVIEW_LOG.md](AI_REVIEW_LOG.md).

### Important findings and disposition

- **HIGH — model quality is not established.** Reproduce with `python spike/T08/quality_analysis.py --check`; only 45/49 saved outputs exist and labels are draft, single-author. Keep Jev out of automated runtime until human adjudication and blind evaluation.
- **HIGH — API failures and budget remain unresolved.** `results/jev-live-aggregate-20261014-v4.json` has four sanitized failed attempts; the cause is unavailable. Three earlier TypeSafe checks returned 451 with no retained body. Do not retry without a separately approved budget.
- **HIGH — no blind gold.** `experiments/deep-v1/manifest.json` and `DEEP_CORPUS_AUDIT.json` show D is visible and all annotations are single-author. The audit reports no missing category coverage, but that is annotation coverage, not measured model recall.
- **MEDIUM — 93.3% review partly reflects gate semantics.** `quality_analysis.py` computes overlapping triggers; `quality_policy.py` preserves separate negative/abstain/positive states. Regression coverage is in `test_quality_analysis.py` and `test_quality_artifacts.py`. Loosening gates is not evidence of safe automation.
- **MEDIUM — taxonomy v0.4 is only a proposal.** `experiments/taxonomy-v0.4-proposal/manifest.json` pins it separately; no live Jev result supports a claim that it improves quality.

Next: human-adjudicate e33/e34/e35 and topic ties, freeze a genuinely blind gold set, pre-register risk and review criteria, then request a separate budget for the proposed 20-call paired v0.3/v0.4 comparison (10 fixed synthetic cases × 2 taxonomy versions). Do not run that experiment automatically. Twenty calls can compare prompt wording on those cases; it cannot establish production quality.

**Can we trust Jev to classify Russian business news now? No. The quality has not been proved.**

See [RESULTS_SUMMARY_RU.md](RESULTS_SUMMARY_RU.md), [ERROR_ANALYSIS.md](ERROR_ANALYSIS.md), [UNCERTAINTY_ANALYSIS.md](UNCERTAINTY_ANALYSIS.md), [THRESHOLD_COMPARISON.md](THRESHOLD_COMPARISON.md), and [NEXT_STEPS.md](NEXT_STEPS.md) for detailed evidence and owner decisions.
