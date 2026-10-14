# AI Factory and independent-review log

Date: 2026-10-14. Scope was offline review of `spike/T08` only. No API client was invoked, no internet/provider request was made, and reviewers were instructed not to edit shared files.

## Workflow context

- Read the AIF skill instructions and project `.ai-factory/RULES.md`; the task was scoped to an offline spike. AIF grounding was used to keep claims tied to pinned result files and test output.
- Baseline, taxonomy and v4 aggregate were treated as immutable inputs. New policy logic and proposal artifacts are separately versioned.
- Review tasks were separated so error triggers, blind label review and threshold calculations were independent. No agent committed changes.

## Subagents used

| Agent | Assignment | Method | Result/use |
|---|---|---|---|
| `/root/review_triggers` | Reconstruct why each saved response enters review and inventory topic/event errors. | Read-only calculation from pinned 45 response rows and v0.3 rules. | Confirmed active Choice=5, event-band=24, insufficient-evidence=17, unlisted=32; 42 review, 3 accepted. Its counts were independently reimplemented in `quality_analysis.py` and regression tests. |
| `/root/blind_gold_taxonomy` | Check disputed labels and taxonomy boundaries, prioritizing e33/e34/e35. | For e33/e34/e35, first-pass label judgment was recorded from text before seeing Jev outputs or current expected labels; taxonomy/current gold were then consulted. | AI opinion only, not a human annotation. Findings and disagreements were copied into `HUMAN_REVIEW_PACKET.md`; source labels were not changed. |
| `/root/threshold_stats` | Independently recalculate threshold and selective-coverage behavior from stored scores. | Read-only recomputation, no calls or data changes. | Compared with `quality_analysis.py`; counterfactual policy results are explicitly non-production and regression-tested. |

## Independent final implementation review

`/root/final_review_t08_quality` performed a read-only review after the calculations and artifacts were generated. It independently recomputed all 7 insufficient-evidence and 7 unlisted gate rows, including coverage, topic accuracy, event TP/FP/FN/F1/exact match, case error and provisional high-impact false positives. It confirmed the 45 saved statuses, source hashes, reproducibility of `QUALITY_ANALYSIS.json`, generated error/uncertainty reports, and the e35 source quote. No calculation discrepancy was found.

The review caught two stale-document issues and one explanation issue: README omitted the new uncertainty/unlisted sweeps; the report and log still marked the prior test count/final review as current/pending; and e47 could be misread as automatically accepted when only the unlisted gate was relaxed. These were corrected. A regression test now compares both review-gate tables against the machine-readable sweep rows, and e47 is documented as still blocked by its event gray-band trigger. The final fresh suite passed: 110 tests, 0 failures, 0 skips; see TEST_REPORT.md/JSON. A final read-only follow-up then reran the 4 artifact regression tests (4/4 passed), reran both reproducibility checks, and confirmed the report builder output exactly matches the checked-in TEST_REPORT.json and TEST_REPORT.md. It reran only those 4 tests, not the full suite.

## Limits

AI agents do not replace an independent human annotator, adjudicator, security audit or provider evidence. The AI label review is explicitly not gold. The reviewer tasks all used the same repository contents and are not independent real-world validation samples.

## Finalization review — 2026-10-15

`/root/t08_final_audit` performed a new read-only review of the final error report, report builder, validation-set rename and full-baseline annotation packet. It confirmed the 60-story set is consistently marked as visible validation (not blind), the `validation-v1-*` IDs and manifest hashes agree, the 49-story packet omits source IDs/draft labels/model outputs, and the original corpus, v0.3 taxonomy and Jev aggregate hashes remain pinned. The reviewer found two documentation drifts (stale test count and generic holdout wording); these were corrected, then the reviewer confirmed there were no remaining findings. The reviewer did not run tests.

The primary run on this revision executed 118 unit tests and 19 Policy/visualization/Playwright tests (all passed), Ruff check/format, offline runner, quality-analysis and deep-corpus report reproducibility, final report reproducibility and `git diff --check`. The exhausted live-budget guard refused classification before network access. No new Jev API request was made. These engineering checks do not make AI review a human gold label or establish model quality.

## Choice validation hardening follow-up — 2026-10-15

An offline code-path review found that `visualization.policy_v2.evaluate_result` trusted Choice scores when called directly: it validated each value and the selected code but did not itself verify the probability sum, maximum-choice consistency, or the stored confidence formula. The saved-data loader did validate these fields, but the policy boundary now independently fails closed as well. A regression test covers wrong confidence, wrong winner, and malformed sum; the low-confidence test uses a valid distribution and confirms that confidence remains non-blocking for event candidates.

`/root/policy_v2_review` independently reviewed the changed boundary and one-way dependency on `jev_spike.choice_confidence_matches`. It confirmed the validation and tolerances match the shared live-result validator, with no import cycle and no change to candidate routing. The reviewer did not run tests. The verification run for this follow-up executed 118 offline suite tests and 20 Policy/visualization/Playwright tests, plus the report/artifact, Ruff, offline runner, network-guard and diff checks. User-modified screenshot files were backed up and restored byte-for-byte after Playwright. No Jev/Polza API request was made.

The visualization had a small version-label drift: the calculation/report were Policy v2.1 while several visible labels said only “Policy v2”. Updated the mode control, detail labels, and comparison/statistics headings to say “Policy v2.1”; the Playwright assertions now check the visible version. This copy-only correction changes neither routing nor saved metrics and has no separate AI-review claim.

## Statistics chart consistency review — 2026-10-15

`/root/policy_chart_review` performed a read-only review of the Policy v2.1 statistics screen. It found that the event-distribution and FP/FN charts still used Legacy predictions while the metric cards used v2 candidates, and that the footnote incorrectly described every chart as Legacy-only. The implementation now routes both charts through the active policy, labels them by mode, and explains that only Coverage vs Error Rate and presets A–E remain Legacy diagnostics. A new Playwright regression independently compares chart rows with Python evaluation over the saved 45 responses, verifies that a proposed gold edit changes the v2 FP/FN graph, and verifies a local positive-threshold change against `policy_v2.evaluate_case` at 0.95. The test also asserts no HTTP(S) requests and no JavaScript errors. The reviewer did not run tests; the author ran the 118-test T08 suite and 21 Policy/visualization/Playwright checks after the change. No Jev/Polza request was made, and user-modified screenshots were restored byte-for-byte.

## Plain-language metric review — 2026-10-15

`/root/t08_final_consistency_review` performed a read-only review of the localized statistics screen. It found that “not found” incorrectly merged an event below the Noul threshold with a positive event held by Policy v2.1, and that Legacy cards described raw Noul threshold labels as if they had been sent downstream despite whole-news review. The UI now says “not passed further” for v2.1 and explicitly includes held candidates; Legacy cards say “above/below Noul threshold,” with a footnote separating raw threshold scores from the actual-transfer comparison table. Browser regression assertions cover both distinctions and pin raw Legacy Noul F1 (`84.0%`) separately from Current Strict delivered-output F1 (`9.1%`). A read-only follow-up confirmed the corrected semantics and no formula changes. Final checks on the current UI version: 21 Policy/visualization/Playwright tests passed; the base T08 suite passed 118 tests on the same revision line, plus Ruff, generated HTML/report checks, and offline runner. No network or Jev/Polza requests were made. Six user-modified PNGs were restored and SHA-256 verified after Playwright.

## Mobile reading-order and touch review — 2026-10-15

`/root/t08_final_consistency_review` independently reviewed the mobile layout changes. It confirmed the compact-screen DOM/visual order (“news list → label comparison → detailed analysis”), the 16px filter input, touch control sizing, and that the CSS changes are limited to narrow breakpoints; no desktop regression was identified. The reviewer did not run tests or access the network. Author verification: 118 T08 tests and 21 Policy/visualization/Playwright tests passed; no external browser requests or Jev/Polza calls occurred. The six user-modified PNGs were restored and hash-verified.
