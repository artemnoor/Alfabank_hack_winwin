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
