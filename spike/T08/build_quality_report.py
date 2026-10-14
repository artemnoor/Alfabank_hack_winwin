"""Build the final offline T08 report from pinned machine artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jev_spike import SPIKE_DIR

QUALITY_PATH = SPIKE_DIR / "QUALITY_ANALYSIS.json"
DEEP_AUDIT_PATH = SPIKE_DIR / "DEEP_CORPUS_AUDIT.json"
REPORT_JSON_PATH = SPIKE_DIR / "TEST_REPORT.json"
REPORT_MD_PATH = SPIKE_DIR / "TEST_REPORT.md"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_report(test_count: int) -> dict[str, Any]:
    quality = _read(QUALITY_PATH)
    deep = _read(DEEP_AUDIT_PATH)
    report = _read(REPORT_JSON_PATH)
    source = quality["generated_from"]
    summary = quality["review_summary"]
    legacy = quality["reproduction"]["legacy_metrics"]
    report.update(
        {
            "report_version": "3.0.0",
            "generated_at_utc": "2026-10-14T00:00:00Z",
            "scope": "offline-only quality analysis; spike/T08 only; no Jev requests, runtime, OpenAPI or production integration changes",
            "verdicts": {
                "engineering_quality": {
                    "status": "PASS",
                    "scope": "offline implementation, reproducible analysis, regression suite, and report artifacts",
                },
                "api_compatibility": {
                    "status": "PASS_WITH_LIMITS",
                    "scope": "historical Polza Jev request/response evidence only; current revision was not live-tested",
                },
                "model_quality": {
                    "status": "NOT_MEASURED_FOR_DECISION",
                    "meaning": "partial descriptive metrics use a small synthetic set and single-author draft labels; no independent human gold or blind set",
                },
                "integration_readiness": {"status": "NOT_READY"},
            },
            "tests": {
                "unittest": {
                    "command": 'python -m unittest discover -s spike/T08 -p "test_*.py" -v',
                    "passed": test_count,
                    "failed": 0,
                    "skipped": 0,
                    "status": "PASS",
                },
                "ruff_check": {"command": "ruff check spike/T08", "status": "PASS"},
                "ruff_format": {
                    "command": "ruff format --check spike/T08",
                    "status": "PASS",
                    "python_files": len(list(SPIKE_DIR.rglob("*.py"))),
                },
                "offline_runner": {
                    "command": "python spike/T08/run_spike.py",
                    "status": "PASS",
                    "classifier_calls": 0,
                    "nonempty_news": 49,
                    "empty_local_validation": 1,
                },
                "quality_analysis": {
                    "command": "python spike/T08/quality_analysis.py --check",
                    "status": "PASS",
                },
                "deep_corpus_audit": {
                    "command": "python spike/T08/deep_corpus_audit.py --check",
                    "status": "PASS",
                },
                "aggregate_rebuild": {
                    "command": "python spike/T08/aggregate_pilot.py <pinned smoke and 8 staged reports> --output <temporary file>",
                    "status": "PASS",
                    "successful_results": 45,
                    "matches_saved_v4_except_timestamp": True,
                    "temporary_output_removed": True,
                },
                "new_live_api_calls": 0,
            },
            "quality_pass": {
                "analysis_version": quality["analysis_version"],
                "policy_version": quality["policy_version"],
                "source_hashes": {
                    "corpus_sha256": source["corpus_sha256"],
                    "taxonomy_sha256": source["taxonomy_sha256"],
                    "aggregate_sha256": source["aggregate_sha256"],
                },
                "saved_response_coverage": {
                    "results": source["result_count"],
                    "expected_nonempty_cases": source["expected_nonempty_count"],
                    "missing_case_ids": source["missing_case_ids"],
                    "missing_rows_counted_as_false_negatives": False,
                    "model_version_reported_by_saved_answers": source["model_version"],
                },
                "reproduced_metrics": legacy,
                "review_summary": summary,
                "signal_quality": quality["signal_quality"],
                "selective_policies": quality["policies"],
                "threshold_sweeps": quality["threshold_sweeps"],
                "review_gate_sweeps": quality["review_gate_sweeps"],
                "error_case_review": quality["error_cases"],
                "latency_and_cost": {
                    "latency": legacy["latency"],
                    "usage": legacy["token_usage"],
                    "failed_request_cost": "UNKNOWN; failed attempts may have been billed",
                },
                "top_findings": [
                    {
                        "severity": "HIGH",
                        "finding": "No independent human gold labels or blind holdout; decision-grade model quality is not measured.",
                        "file": "spike/T08/DEEP_CORPUS_AUDIT.json",
                        "reproduction": "python spike/T08/deep_corpus_audit.py --check; inspect gold_status and not_a_blind_holdout",
                        "expected": "Independent human annotations, adjudication and frozen blind data before model quality claims.",
                        "actual": "Single-author draft labels; D is visible; no Jev calls on the deep corpus.",
                        "recommendation": "Complete human review and a separately controlled blind benchmark before any automation decision.",
                    },
                    {
                        "severity": "HIGH",
                        "finding": "4 of 49 outputs are missing after sanitized failures; failure cause is unknown and success-only metrics may be biased.",
                        "file": "spike/T08/results/jev-live-aggregate-20261014-v4.json:24-53",
                        "reproduction": "python spike/T08/quality_analysis.py --check; inspect missing_result_case_ids",
                        "expected": "Missing requests remain unavailable and are excluded from FP/FN denominators.",
                        "actual": "e23/e35/e41/e43 have no Jev result; raw causes are unavailable.",
                        "recommendation": "Do not infer model errors or retry without a new approved budget.",
                    },
                    {
                        "severity": "HIGH",
                        "finding": "42/45 review is driven by overlapping abstention/review rules; relaxing them creates draft-label errors and is not a safe coverage guarantee.",
                        "file": "spike/T08/quality_analysis.py:484-537; spike/T08/quality_policy.py:45-150",
                        "reproduction": "python spike/T08/quality_analysis.py; inspect review_summary and review_gate_sweeps",
                        "expected": "Topic uncertainty, event abstention, out-of-list and evidence sufficiency remain distinct signals.",
                        "actual": "Overlapping legacy gates yield 93.3% review; weaker gates are not independently validated.",
                        "recommendation": "Evaluate a preregistered policy only on human-adjudicated blind data.",
                    },
                    {
                        "severity": "HIGH",
                        "finding": "Historical API budget accounting is 50 pilot attempts plus 3 separate TypeSafe 451 checks if one global cap applies; no further requests without new approval.",
                        "file": "spike/T08/results/route-check.json:1-14; spike/T08/TEST_REPORT.json:live_api",
                        "reproduction": "Count 50 pinned pilot attempts and 3 separate route checks.",
                        "expected": "No request beyond the approved global budget.",
                        "actual": "Known history is 53 if route checks share that cap; no requests were made in this pass.",
                        "recommendation": "Keep live calls disabled until a new explicit budget and accounting boundary are approved.",
                    },
                    {
                        "severity": "MEDIUM",
                        "finding": "Current source revision and provider upstream/fallback identity were not live-verified or cryptographically attested.",
                        "file": "spike/T08/jev_spike.py; spike/T08/results/jev-live-aggregate-20261014-v4.json",
                        "reproduction": "Compare the saved client SHA with current source and inspect provider_response_authenticity.",
                        "expected": "Current client behavior and provider path verified for the revision under review.",
                        "actual": "Stored answers were checked offline; current revision made no request; origin is unattested.",
                        "recommendation": "Do not claim current-live compatibility or upstream attestation without a separately approved check.",
                    },
                ],
                "quality_analysis_artifact": {
                    "path": "spike/T08/QUALITY_ANALYSIS.json",
                    "sha256": _sha256(QUALITY_PATH),
                },
            },
            "taxonomy_proposal": {
                "path": "spike/T08/experiments/taxonomy-v0.4-proposal/taxonomy.json",
                "version": "0.4.0-spike",
                "sha256": "444b570655e87938276d7fdeec5fa61642498497377c179c557c58549a8f972c",
                "status": "unvalidated proposal; no new Jev run; not approved",
            },
            "deep_corpus_audit": {
                "path": "spike/T08/DEEP_CORPUS_AUDIT.json",
                "sha256": _sha256(DEEP_AUDIT_PATH),
                "total_cases": deep["total_cases"],
                "nonempty_cases": deep["nonempty_cases"],
                "split_counts": deep["split_counts"],
                "uncovered_topic_codes": deep["uncovered_topic_codes"],
                "uncovered_event_codes": deep["uncovered_event_codes"],
                "jev_calls": deep["jev_calls"],
                "d_is_blind": False,
                "gold_status": deep["gold_status"],
                "duplicate_groups": deep["exact_duplicate_text_groups"],
                "near_duplicate_pairs": deep[
                    "near_duplicate_pairs_at_or_above_threshold"
                ],
            },
            "gold_review": {
                "status": "AWAITING_HUMAN_REVIEW",
                "human_annotators": 0,
                "ai_reviewers_are_not_gold": True,
                "priority_cases": [
                    "e33-multi-price-shortage",
                    "e34-multi-insolvency-legal",
                    "e35-multi-labor-investment",
                ],
                "packet": "spike/T08/HUMAN_REVIEW_PACKET.md",
            },
            "independent_review": {
                "workflow": "AI Factory; read-only subagent reviews; no shared-file editing by reviewers",
                "subagents_used": [
                    {
                        "agent": "/root/review_triggers",
                        "focus": "review triggers and error inventory",
                    },
                    {
                        "agent": "/root/blind_gold_taxonomy",
                        "focus": "model-blind AI opinion on disputed labels; not human gold",
                    },
                    {
                        "agent": "/root/threshold_stats",
                        "focus": "independent threshold and coverage calculations",
                    },
                    {
                        "agent": "/root/final_review_t08_quality",
                        "focus": "final read-only recalculation, source hashes and artifact consistency",
                    },
                ],
                "final_review": "confirmed both gate sweeps, 45 statuses, source hashes and generated artifacts; final follow-up reran 4 artifact tests (4/4) and confirmed TEST_REPORT JSON/Markdown exactly match the report builder; caught documentation sync issues and e47 interpretation, all corrected and regression-tested",
                "log": "spike/T08/AI_REVIEW_LOG.md",
            },
            "http_451": {
                "observations": [
                    "historical TypeSafe GET /v1/models returned 451",
                    "two historical TypeSafe System One POST attempts returned 451",
                ],
                "confirmed_root_cause": None,
                "status": "UNKNOWN; not retried and no workaround attempted",
            },
            "not_run_or_not_measured": [
                "No Jev call in this pass; new paid/API requests forbidden by task budget",
                "No decision-grade model quality or probability calibration",
                "No independent human gold adjudication",
                "No blinded holdout; deep-v1 D is visible and excluded from scoring/tuning",
                "No live metamorphic/repeated stability run",
                "No live check of the current client revision",
                "No verified cause for historical HTTP 451 or sanitized request failures",
                "No provider-side/upstream identity or fallback attestation",
                "No production DTO/policy/provenance/history/replay integration",
            ],
            "artifacts": {
                **report.get("artifacts", {}),
                "quality_analysis": "spike/T08/QUALITY_ANALYSIS.json",
                "deep_corpus_audit": "spike/T08/DEEP_CORPUS_AUDIT.json",
                "error_analysis": "spike/T08/ERROR_ANALYSIS.md",
                "uncertainty_analysis": "spike/T08/UNCERTAINTY_ANALYSIS.md",
                "threshold_comparison": "spike/T08/THRESHOLD_COMPARISON.md",
                "human_review_packet": "spike/T08/HUMAN_REVIEW_PACKET.md",
                "benchmark_plan": "spike/T08/BENCHMARK_PLAN.md",
                "taxonomy_proposal": "spike/T08/TAXONOMY_PROPOSAL.md",
                "next_steps": "spike/T08/NEXT_STEPS.md",
                "ai_review_log": "spike/T08/AI_REVIEW_LOG.md",
                "previous_report_archive": "spike/T08/results/archive/TEST_REPORT-2.1.0-pre-quality.md and .json",
            },
            "recommendation": "Do not trust Jev for automatic classification of Russian business news yet. Retain it as an isolated research spike and require human review. First obtain human-adjudicated labels and a truly blind benchmark; only then request a separate small paired Jev experiment.",
        }
    )
    report["live_api"]["rechecked_in_this_pass"] = False
    report["live_api"]["new_requests_in_this_pass"] = 0
    report["live_api"]["historical_status_note"] = (
        "Saved outputs provide historical compatibility evidence only; do not treat this pass as a live API check."
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    quality = report["quality_pass"]
    summary = quality["review_summary"]
    metrics = quality["reproduced_metrics"]
    policies = {row["policy_id"]: row for row in quality["selective_policies"]}
    current = policies["current_strict"]
    ignore_u = policies["ignore_uncertainty_gate"]
    ignore_both = policies["ignore_both_signal_gates"]
    choice_only = policies["choice_only"]
    tests = report["tests"]["unittest"]
    reasons = summary["active_trigger_case_counts_overlapping"]
    combinations = summary["trigger_combination_counts"]
    event_fp = ", ".join(
        f"{item['case_id']}:{item['code']}" for item in metrics["event_false_positives"]
    )
    event_fn = ", ".join(
        f"{item['case_id']}:{item['code']}" for item in metrics["event_false_negatives"]
    )
    error_topics = ", ".join(
        f"{item['case_id']} ({item['expected']} → {item['predicted']})"
        for item in metrics["topic_misclassifications"]
    )
    return f"""# T08 — Jev: offline quality improvement report

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
| `python -m unittest discover -s spike/T08 -p "test_*.py" -v` | **{tests["passed"]} passed, {tests["failed"]} failed, {tests["skipped"]} skipped** |
| `ruff check spike/T08` | **PASS** |
| `ruff format --check spike/T08` | **PASS**, {report["tests"]["ruff_format"]["python_files"]} Python files checked |
| `python spike/T08/run_spike.py` | **PASS**, 0 classifier calls; 49 non-empty plus 1 locally rejected empty case |
| `python spike/T08/quality_analysis.py --check` | **PASS**, machine analysis reproduces byte-for-byte |
| `python spike/T08/deep_corpus_audit.py --check` | **PASS**, deep corpus audit reproduces |
| Historical aggregate rebuild from pinned smoke + 8 staged files | **PASS**, 45 outputs and every field matches v4 except generation timestamp; temporary output removed |
| New Jev API requests | **0**, as required |

The offline tests prohibit standard Python network entrypoints and test that an exhausted live ledger refuses before calling the classifier. This is an application-level guard, not an operating-system egress firewall.

## What the saved Jev answers show

The original baseline and its results were kept unchanged. Hashes:

- Baseline corpus: `{quality["source_hashes"]["corpus_sha256"]}`
- Taxonomy `0.3.0-spike`: `{quality["source_hashes"]["taxonomy_sha256"]}`
- Saved aggregate v4: `{quality["source_hashes"]["aggregate_sha256"]}`

There are 45 saved successful answers for 49 non-empty baseline stories. Missing: `{", ".join(quality["saved_response_coverage"]["missing_case_ids"])}`. Missing calls are not counted as model false negatives.

| Metric against draft labels | Result |
|---|---:|
| Topic accuracy | {metrics["topic_correct"]}/{metrics["topic_total"]} = {_percent(metrics["topic_accuracy"])} |
| Event micro precision / recall / F1 | {_percent(metrics["event_micro_precision"])} / {_percent(metrics["event_micro_recall"])} / {_percent(metrics["event_micro_f1"])} |
| Event macro F1 | {_percent(metrics["event_macro_f1"])} |
| Exact event-set match | {metrics["event_exact_match_count"]}/{metrics["non_empty_case_count"]} = {_percent(metrics["event_exact_match_rate"])} |
| Historical result status `uncertain/review` | {summary["review_count"]}/{summary["case_count"]} = {_percent(summary["review_rate"])} |
| Unlisted-event recall | 0/1; one draft positive only |
| `legal_enforcement` recall | 0; no positive answer for 3 draft positives |
| `shortage_capacity_constraint` recall | 1/3 |

The 45-answer descriptive metrics are not a valid independent estimate: labels are single-author drafts, categories have very small support, 4 outputs are missing, and the provider response origin is not signed.

### Errors against the current draft labels

- **14 topic mismatches.** Full text, intended labels, Jev choices and possible annotation disputes are listed in [ERROR_ANALYSIS.md](ERROR_ANALYSIS.md). IDs: {error_topics}.
- **6 event false positives:** {event_fp}.
- **7 event false negatives:** {event_fn}.
- `e33`, `e34`, and `e35` need human adjudication. The AI reviewer’s model-blind first opinion is not human gold. Jev had no saved response for e35.

## Why 93.3% were sent to review

The triggers overlap; do not add these counts as if they were distinct cases:

| Active reason | Cases |
|---|---:|
| Choice confidence below 0.5 | {reasons["choice"]} |
| Event score in the gray band (0.2–0.8) | {reasons["event_scores"]} |
| Insufficient-evidence score above 0.2 | {reasons["uncertainty"]} |
| Unlisted-event score above 0.2 | {reasons["unlisted"]} |

There are {summary["review_cases_with_multiple_reasons"]} cases with multiple triggers and {summary["review_cases_with_exactly_one_reason"]} with one. Single-trigger cases: {summary["exclusive_single_reason_counts"]}. Combination counts: `{json.dumps(combinations, ensure_ascii=False, sort_keys=True)}`.

Important: Noul’s middle band is **abstain**, not a calibrated probability. The saved unlisted signal had 33 abstains and 12 negatives, with no positive; the insufficient-evidence signal had 3 positive, 14 abstain and 28 negative. The active historical rule treats any score above 0.2 as review. For `other_uncertain`, legacy logic ignores the unlisted/event gates, which explains raw trigger counts of 5/25/17/33 versus active counts of 5/24/17/32.

### Counterfactual policy snapshots

All rows reuse the same 45 partially observed cases and single-author draft labels. These are diagnostic calculations, not recommendations or calibrated risk estimates.

| Policy | Auto accepted | Topic accuracy | Event F1 | Exact event set | Case error rate | Provisional consequential FP |
|---|---:|---:|---:|---:|---:|---:|
| Current strict gate | {current["accepted_case_count"]}/45 | {_percent(current["topic_accuracy"])} | {_percent(current["event_metrics"]["f1"])} | {_percent(current["event_metrics"]["exact_rate"])} | {_percent(current["case_error_rate"])} | {current["high_consequence_false_positive_count_provisional"]} |
| Ignore only insufficient-evidence gate | {ignore_u["accepted_case_count"]}/45 | {_percent(ignore_u["topic_accuracy"])} | {_percent(ignore_u["event_metrics"]["f1"])} | {_percent(ignore_u["event_metrics"]["exact_rate"])} | {_percent(ignore_u["case_error_rate"])} | {ignore_u["high_consequence_false_positive_count_provisional"]} |
| Ignore both evidence signal gates | {ignore_both["accepted_case_count"]}/45 | {_percent(ignore_both["topic_accuracy"])} | {_percent(ignore_both["event_metrics"]["f1"])} | {_percent(ignore_both["event_metrics"]["exact_rate"])} | {_percent(ignore_both["case_error_rate"])} | {ignore_both["high_consequence_false_positive_count_provisional"]} |
| Choice only | {choice_only["accepted_case_count"]}/45 | {_percent(choice_only["topic_accuracy"])} | {_percent(choice_only["event_metrics"]["f1"])} | {_percent(choice_only["event_metrics"]["exact_rate"])} | {_percent(choice_only["case_error_rate"])} | {choice_only["high_consequence_false_positive_count_provisional"]} |

The 93.3% review rate is partly a consequence of how we interpret abstention scores, but lowering the gates does not establish a safe automation rate. Choice-only accepts 40 cases and has 16 draft-label case errors plus 3 provisional high-consequence false positives. Changing only the unlisted gate does not auto-accept e47 because its corporate-transaction event score remains gray. Full per-threshold tables are in [THRESHOLD_COMPARISON.md](THRESHOLD_COMPARISON.md); machine calculations are in [QUALITY_ANALYSIS.json](QUALITY_ANALYSIS.json).

## Taxonomy, labels and benchmark

- Taxonomy v0.3 remains unchanged. A separate `0.4.0-spike` proposal refines boundary definitions but has the same codes/questions; it has not been tried with Jev and is not approved. See [TAXONOMY_PROPOSAL.md](TAXONOMY_PROPOSAL.md).
- The deep synthetic corpus contains {report["deep_corpus_audit"]["total_cases"]} cases (A=76, B=36, C=24, D=24), with all 11 topic and all 15 event codes represented. Jev was not run on it.
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
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-passed", type=int, required=True)
    parser.add_argument("--tests-failed", type=int, default=0)
    parser.add_argument("--tests-skipped", type=int, default=0)
    args = parser.parse_args()
    if min(args.tests_passed, args.tests_failed, args.tests_skipped) < 0:
        parser.error("test counts must be non-negative")
    report = build_report(args.tests_passed)
    report["tests"]["unittest"]["failed"] = args.tests_failed
    report["tests"]["unittest"]["skipped"] = args.tests_skipped
    report["tests"]["unittest"]["status"] = "PASS" if args.tests_failed == 0 else "FAIL"
    REPORT_JSON_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    REPORT_MD_PATH.write_text(render_markdown(report), encoding="utf-8")
    print(
        f"REPORTS={REPORT_MD_PATH.name},{REPORT_JSON_PATH.name} tests={args.tests_passed}/{args.tests_failed}/{args.tests_skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
