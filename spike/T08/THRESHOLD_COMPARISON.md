# Threshold and selective-classification comparison

All rows below are counterfactual re-reads of the same 45 saved Jev responses from aggregate v4. They use draft single-author labels, are not independent evaluation, and do not calibrate Jev scores. No score or provider result was changed. The 4 failed calls are excluded; they are not false negatives.

## Coverage versus observed risk

Here, **coverage** is the fraction automatically accepted by a simulated policy. **Observed case error** means topic mismatch or thresholded event-set mismatch among accepted examples. It is not a calibrated deployment risk estimate. “High-impact FP” uses a provisional, unapproved grouping of six event codes; inspect per-code outputs in `QUALITY_ANALYSIS.json`.

| Offline policy | Accepted / 45 | Coverage | Topic accuracy among accepted | Event P / R / F1 | Exact event set | Joint exact | Case error among auto | Provisional high-impact FP | Unsafe gold accepted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A — current strict gate | 3 | 6.7% | 66.7% | 66.7 / 100 / 80.0% | 66.7% | 66.7% | 33.3% (1/3) | 0 | none in this sample |
| B — ignore unlisted gate | 11 | 24.4% | 72.7% | 88.9 / 88.9 / 88.9% | 81.8% | 63.6% | 36.4% (4/11) | 0 | accepts four draft non-exact cases, including an enforcement FN |
| C — ignore insufficient-evidence gate | 8 | 17.8% | 87.5% | 66.7 / 100 / 80.0% | 87.5% | 87.5% | 12.5% (1/8) | 0 | accepts 2 `uncertain` and 1 `other` draft-status cases |
| D — ignore both signal gates | 18 | 40.0% | 83.3% | 90.0 / 90.0 / 90.0% | 88.9% | 77.8% | 22.2% (4/18) | 0 | accepts the same 3 `uncertain`/`other` draft-status cases |
| E — Choice gate only | 40 | 88.9% | 75.0% | 83.8 / 81.6 / 82.7% | 72.5% | 60.0% | 40.0% (16/40) | 3 | accepts 3 `uncertain` + 1 `other`, including out-of-list e47 |

The exact accepted-case IDs and all event-level FP/FN are in the JSON. “Ignore” policies are diagnostic counterfactuals, not recommended settings. Policies B–E remove a protection without knowing whether a score is calibrated. In particular, policy E creates three provisional high-impact false positives in only 40 accepted cases.

### Interpretation

- Current strict review is not proof of 93.3% model failure: 28 of 42 review cases have multiple triggers. Only three cases pass every gate; one of those three has a topic/event error.
- Removing only the unlisted gate raises sample coverage from 6.7% to 24.4%, while the observed joint exact rate falls to 63.6% on accepted rows. It also accepts a legal-enforcement miss.
- Removing only the insufficient-evidence gate raises coverage to 17.8%, but allows cases whose draft gold says evidence is insufficient to pass automatically. That is a policy failure even if their topic/event fields happen to match.
- Removing both signal gates gives 40% coverage and 77.8% joint exact on this selected subset, but accepts uncertain and `other` cases and is not safe to deploy.
- Choice-only gets the most coverage, 88.9%, but 40% of the accepted rows contain a topic or event-set mismatch; three provisional high-impact event FPs occur.

No defensible answer to “how much manual review can be removed without increasing dangerous errors?” can be inferred from these 45 partial responses and unadjudicated labels. The strict gate currently avoids the provisional high-impact FP group, but it leaves only 3/45 auto cases. Relaxation does not have enough independent evidence to guarantee that the dangerous error rate will stay constant.

## Separate threshold sweeps

### Choice confidence only

These rows apply the Choice cutoff to topic confidence and ignore all other review reasons. Topic accuracy is measured only among accepted rows.

| Choice cutoff | Accepted / 45 | Coverage | Topic accuracy | Topic errors among accepted |
|---:|---:|---:|---:|---:|
| 0.30 | 45 | 100.0% | 68.9% | 14 |
| 0.40 | 44 | 97.8% | 70.5% | 13 |
| 0.50 | 40 | 88.9% | 75.0% | 10 |
| 0.60 | 35 | 77.8% | 80.0% | 7 |
| 0.70 | 31 | 68.9% | 83.9% | 5 |
| 0.80 | 27 | 60.0% | 85.2% | 4 |

The increase is descriptive selection behavior, not evidence that these confidence values are calibrated probabilities. Raising a threshold makes the accepted subset easier at the cost of lower coverage; there is no unseen validation set here.

### Insufficient-evidence review gate

Vary only the rule `uncertainty_score > cutoff → review`. Choice, event gray-band and unlisted gates stay at the historical v0.3 settings. `Event F1` and exact-set are measured on the automatically accepted subset.

| Uncertainty review cutoff | Accepted / 45 | Coverage | Topic accuracy | Event F1 | Exact event set | Case error rate | Non-classified gold status auto-accepted |
|---:|---:|---:|---:|---:|---:|---:|---|
| >0.20 | 3 | 6.7% | 66.7% | 80.0% | 66.7% | 33.3% | none |
| >0.30 | 6 | 13.3% | 83.3% | 80.0% | 83.3% | 16.7% | e46 (`other`) |
| >0.40 | 6 | 13.3% | 83.3% | 80.0% | 83.3% | 16.7% | e46 (`other`) |
| >0.50 | 6 | 13.3% | 83.3% | 80.0% | 83.3% | 16.7% | e46 (`other`) |
| >0.60 | 6 | 13.3% | 83.3% | 80.0% | 83.3% | 16.7% | e46 (`other`) |
| >0.70 | 6 | 13.3% | 83.3% | 80.0% | 83.3% | 16.7% | e46 (`other`) |
| >0.80 | 6 | 13.3% | 83.3% | 80.0% | 83.3% | 16.7% | e46 (`other`) |

Moving this one gate from >0.20 to >0.30 releases three more cases, but one is the `other` topic case e46. The result is only a counterfactual over a tiny, draft-labeled subset and is not a recommendation.

### Out-of-list review gate

Vary only the `unlisted_score > cutoff → review` threshold. The other gates stay unchanged. Scores in the middle band do not become positive classifications; this table only shows how a review gate changes acceptance.

| Unlisted review cutoff | Accepted / 45 | Coverage | Topic accuracy | Event F1 | Exact event set | Case error rate | Unlisted gold case accepted |
|---:|---:|---:|---:|---:|---:|---:|---|
| >0.20 | 3 | 6.7% | 66.7% | 80.0% | 66.7% | 33.3% | no |
| >0.30 | 3 | 6.7% | 66.7% | 80.0% | 66.7% | 33.3% | no |
| >0.40 | 5 | 11.1% | 80.0% | 75.0% | 60.0% | 40.0% | no |
| >0.50 | 8 | 17.8% | 75.0% | 83.3% | 75.0% | 37.5% | no |
| >0.60 | 11 | 24.4% | 72.7% | 88.9% | 81.8% | 36.4% | no |
| >0.70 | 11 | 24.4% | 72.7% | 88.9% | 81.8% | 36.4% | no |
| >0.80 | 11 | 24.4% | 72.7% | 88.9% | 81.8% | 36.4% | no |

The e47 unlisted score is 0.59: raising the review cutoff from >0.50 to >0.60 stops that particular trigger, but its `corporate_transaction_restructuring` event score remains in the gray band, so this one-gate counterfactual still sends it to review. Only the `choice_only` counterfactual bypasses that other trigger and accepts e47; this illustrates why changing one review threshold cannot substitute for a distinct `positive / abstain / negative` decision policy.

### Event Noul positive threshold

The legacy sweep holds the negative cutoff at 0.2 and evaluates every saved event score against draft labels. Mid-band scores are treated as not positive for this binary metric. “Ambiguous cells” is not the same as the percentage of reviewed news.

| Positive cutoff | TP | FP | FN | Precision | Recall | Micro-F1 | Exact event-set rate | Ambiguous score cells / 675 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.30 | 39 | 29 | 2 | 57.4% | 95.1% | 71.6% | 53.3% | 15 |
| 0.40 | 39 | 20 | 2 | 66.1% | 95.1% | 78.0% | 60.0% | 24 |
| 0.50 | 39 | 17 | 2 | 69.6% | 95.1% | 80.4% | 66.7% | 27 |
| 0.60 | 38 | 15 | 3 | 71.7% | 92.7% | 80.9% | 68.9% | 30 |
| 0.70 | 36 | 11 | 5 | 76.6% | 87.8% | 81.8% | 71.1% | 36 |
| 0.80 | 34 | 6 | 7 | 85.0% | 82.9% | 84.0% | 75.6% | 43 |
| 0.90 | 31 | 2 | 10 | 93.9% | 75.6% | 83.8% | 75.6% | 50 |

This curve shows the expected trade-off on the same draft labels: stricter cutoffs reduce FPs and increase FNs. It does not pick a production threshold. Noul score calibration, per-category performance and dangerous-error costs remain unmeasured.

## Threshold options

1. **Keep the current strict gate for offline comparison only.** Do not treat it as a quality score. It errs toward review but the current `>0.2` rule marks abstain-zone scores as triggers.
2. **Separate states, do not simply lower cutoffs.** Keep Noul `negative / abstain / positive` distinct for each event, unlisted event, and insufficient evidence. A topic can be clear while event evidence is weak. An out-of-list event can be clear without being “uncertain”.
3. **Selective classification with independent validation.** Define before evaluation: what output is permitted for each state; what classes require human review; how missing or failed calls are routed; and an upper confidence bound for consequential FP. Evaluate that frozen policy on a new blind human-adjudicated test set.

No candidate policy here is production-ready. The current policy module `quality_policy.py` adds a pure offline tri-state interpretation while preserving the historical v0.3 gate for audit; it does not change `jev_spike.py`, runtime or saved Jev results.
