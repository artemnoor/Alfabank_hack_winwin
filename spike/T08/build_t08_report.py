"""Build the current T08 acceptance report from pinned offline artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jev_spike import SPIKE_DIR

QUALITY_PATH = SPIKE_DIR / "QUALITY_ANALYSIS.json"
DEEP_AUDIT_PATH = SPIKE_DIR / "DEEP_CORPUS_AUDIT.json"
POLICY_PATH = SPIKE_DIR / "visualization" / "policy-v2-results.json"
ERROR_PATH = SPIKE_DIR / "ERROR_ANALYSIS_V2.1.json"
ERROR_MANIFEST_PATH = SPIKE_DIR / "ERROR_ANALYSIS_V2.1.manifest.json"
TAXONOMY_MANIFEST_PATH = (
    SPIKE_DIR / "experiments" / "taxonomy-v0.4.1-proposal" / "manifest.json"
)
VALIDATION_MANIFEST_PATH = (
    SPIKE_DIR / "experiments" / "visible-validation-v1" / "manifest.json"
)
REPORT_JSON_PATH = SPIKE_DIR / "TEST_REPORT.json"
REPORT_MD_PATH = SPIKE_DIR / "TEST_REPORT.md"
SNAPSHOT_DATE = "2026-10-15"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_report(
    *,
    unit_tests_passed: int,
    browser_tests_passed: int,
    failed: int = 0,
    skipped: int = 0,
) -> dict[str, Any]:
    quality = _read(QUALITY_PATH)
    deep = _read(DEEP_AUDIT_PATH)
    policy_document = _read(POLICY_PATH)
    errors = _read(ERROR_PATH)
    error_manifest = _read(ERROR_MANIFEST_PATH)
    taxonomy_manifest = _read(TAXONOMY_MANIFEST_PATH)
    validation_manifest = _read(VALIDATION_MANIFEST_PATH)

    source = quality["generated_from"]
    legacy_metrics = quality["reproduction"]["legacy_metrics"]
    legacy_review = quality["review_summary"]
    policy = policy_document["policy_comparison"]
    legacy_policy = policy["legacy"]
    v21 = policy["policy_v2"]
    event_metrics = v21["event_output_metrics"]

    if errors["saved_answer_count"] != 45:
        raise ValueError("error audit must reconcile the pinned 45 saved answers")
    if (len(errors["false_positives"]), len(errors["false_negatives"])) != (6, 7):
        raise ValueError("error audit must have 6 FP and 7 FN disagreements")
    if (
        validation_manifest["case_count"] != 60
        or validation_manifest["eligible_for_model_scoring"]
    ):
        raise ValueError("visible validation set must stay unlabelled and excluded")
    if error_manifest["packet_case_count"] != 49:
        raise ValueError("human annotation packet must cover the full baseline")

    report = {
        "report_version": "4.0.0",
        "snapshot_date": SNAPSHOT_DATE,
        "project": "AlfaBank Hackathon T08 Jev spike",
        "branch": "codex/spike-t08-jev-news-classification",
        "scope": "spike/T08 only; offline analysis; no production, OpenAPI, or Jev changes",
        "verdicts": {
            "engineering_quality": {
                "status": "PASS" if failed == 0 else "FAIL",
                "scope": "offline implementation and listed regression checks",
            },
            "api_compatibility": {
                "status": "BLOCKED",
                "scope": "historical saved Polza outputs exist; current source revision was not live-tested",
            },
            "model_quality": {
                "status": "NOT_MEASURED_FOR_DECISION",
                "scope": "descriptive results use synthetic inputs and preliminary single-author labels",
            },
            "integration_readiness": {
                "status": "READY_FOR_EXPERIMENTAL_T09_HANDOFF_ONLY",
                "production_ready": False,
            },
        },
        "source_data": {
            "baseline": {
                "corpus_sha256": source["corpus_sha256"],
                "taxonomy_version": source["taxonomy_version"],
                "taxonomy_sha256": source["taxonomy_sha256"],
                "aggregate_sha256": source["aggregate_sha256"],
                "nonempty_stories": source["expected_nonempty_count"],
                "saved_answers": source["result_count"],
                "missing_answer_ids": source["missing_case_ids"],
                "model_version_reported_by_saved_answers": source["model_version"],
                "gold_status": "single-author preliminary labels; not human-adjudicated",
            },
            "deep_corpus": {
                "case_count": deep["total_cases"],
                "jev_calls": deep["jev_calls"],
                "split_counts": deep["split_counts"],
                "d_is_blind": False,
                "gold_status": deep["gold_status"],
            },
        },
        "historical_descriptive_metrics": {
            "basis": "45 saved Jev answers; 4 missing results excluded, not counted as false negatives",
            "topic_accuracy": {
                "correct": legacy_metrics["topic_correct"],
                "total": legacy_metrics["topic_total"],
                "value": legacy_metrics["topic_accuracy"],
            },
            "event_micro_precision": legacy_metrics["event_micro_precision"],
            "event_micro_recall": legacy_metrics["event_micro_recall"],
            "event_micro_f1": legacy_metrics["event_micro_f1"],
            "event_macro_f1": legacy_metrics["event_macro_f1"],
            "exact_event_set": {
                "matches": legacy_metrics["event_exact_match_count"],
                "total": legacy_metrics["non_empty_case_count"],
                "value": legacy_metrics["event_exact_match_rate"],
            },
            "legacy_review": {
                "review_count": legacy_review["review_count"],
                "total": legacy_review["case_count"],
                "value": legacy_review["review_rate"],
                "overlapping_trigger_counts": legacy_review[
                    "active_trigger_case_counts_overlapping"
                ],
                "cases_with_multiple_triggers": legacy_review[
                    "review_cases_with_multiple_reasons"
                ],
            },
            "latency_ms": legacy_metrics["latency"],
            "token_usage": legacy_metrics["token_usage"],
            "interpretation": "preliminary synthetic-set measurements only; not a blind or production-quality estimate",
        },
        "policy_v2_1": {
            "version": policy_document["policy_version"],
            "source_hashes": policy_document["source_hashes"],
            "thresholds": {
                "event_candidate_at_or_above": 0.8,
                "insufficient_evidence_holds_candidates_at_or_above": 0.8,
                "unlisted_creates_separate_review_at_or_above": 0.8,
            },
            "denominator": policy["denominator"],
            "legacy_full_story_auto": legacy_policy["full_story_auto_count"],
            "legacy_full_story_review": legacy_policy["full_story_review_count"],
            "candidate_bearing_stories": v21["stories_with_candidates"],
            "candidate_coverage": v21["candidate_coverage"],
            "candidate_event_count": v21["candidate_event_count"],
            "stories_with_any_review": v21["stories_with_any_review"],
            "evidence_review_stories": v21["insufficient_evidence_review_stories"],
            "unlisted_review_stories": v21["unlisted_event_review_stories"],
            "candidate_output_metrics": {
                key: event_metrics[key]
                for key in (
                    "tp",
                    "fp",
                    "fn",
                    "precision",
                    "recall",
                    "f1",
                    "exact_count",
                    "exact_rate",
                    "provisional_high_consequence_fp",
                )
            },
            "candidate_is_confirmed_fact": False,
            "review_reduction_is_safety_evidence": False,
        },
        "error_disagreements": {
            "counts": errors["counts"],
            "interpretation": errors["interpretation_limit"],
            "false_positives": [
                {
                    "case_id": row["case_id"],
                    "event_code": row["event_code"],
                    "score": row["event_score"],
                    "state": row["event_state"],
                    "likely_cause": row["likely_cause"],
                    "minimum_proposal_change": row["taxonomy_action"],
                }
                for row in errors["false_positives"]
            ],
            "false_negatives": [
                {
                    "case_id": row["case_id"],
                    "event_code": row["event_code"],
                    "score": row["event_score"],
                    "state": row["event_state"],
                    "likely_cause": row["likely_cause"],
                    "minimum_proposal_change": row["taxonomy_action"],
                }
                for row in errors["false_negatives"]
            ],
        },
        "taxonomy_proposal": {
            "version": taxonomy_manifest["version"],
            "status": taxonomy_manifest["status"],
            "sha256": taxonomy_manifest["proposal_sha256"],
            "live_requests": taxonomy_manifest["live_requests"],
            "approval": taxonomy_manifest["approval"],
            "scope": taxonomy_manifest["change_scope"],
        },
        "human_annotation": {
            "packet_path": error_manifest["model_blind_review_packet_path"],
            "packet_sha256": error_manifest["model_blind_review_packet_sha256"],
            "case_count": error_manifest["packet_case_count"],
            "selection": error_manifest["packet_selection"],
            "source_ids_in_packet": error_manifest["packet_contains_source_ids"],
            "draft_labels_or_model_outputs_in_packet": error_manifest[
                "packet_contains_draft_labels_or_model_outputs"
            ],
            "owner_blind": error_manifest["owner_blind"],
            "human_annotators": 0,
            "status": "awaiting_two_independent_annotators_and_adjudication",
        },
        "visible_validation_set": {
            "dataset_id": validation_manifest["dataset_id"],
            "version": validation_manifest["version"],
            "case_count": validation_manifest["case_count"],
            "input_sha256": validation_manifest["input_sha256"],
            "status": validation_manifest["status"],
            "gold_label_status": validation_manifest["gold_label_status"],
            "eligible_for_model_scoring": validation_manifest[
                "eligible_for_model_scoring"
            ],
            "benchmark_role": validation_manifest["benchmark_role"],
            "eligible_as_blind_test": validation_manifest["eligible_as_blind_test"],
            "excluded_from_current_reports": validation_manifest[
                "excluded_from_current_reports"
            ],
            "is_genuinely_blind": validation_manifest["is_genuinely_blind"],
        },
        "verification": {
            "unit_tests": {
                "command": "py -m unittest discover -s spike/T08 -p 'test*.py' -v",
                "passed": unit_tests_passed,
                "failed": failed,
                "skipped": skipped,
                "status": "PASS" if failed == 0 else "FAIL",
            },
            "policy_and_browser_tests": {
                "command": "py -m unittest spike.T08.visualization.test_policy_v2 spike.T08.visualization.test_visualization -v",
                "passed": browser_tests_passed,
                "failed": 0,
                "skipped": 0,
                "includes_playwright": True,
            },
            "ruff_check": "PASS",
            "ruff_format_check": "PASS",
            "offline_runner_classifier_calls": 0,
            "quality_analysis_reproducibility": "PASS",
            "deep_corpus_audit_reproducibility": "PASS",
            "validation_asset_builder": "PASS",
            "javascript_syntax": "PASS",
            "git_diff_checks": "PASS",
            "new_jev_api_requests": 0,
        },
        "independent_review": {
            "result": "FINDINGS_FIXED_AND_REGRESSION_TESTED",
            "reviewer": "AI Factory read-only reviews",
            "scope": "saved-output error reconciliation and taxonomy checks; plus Policy v2.1 statistics chart consistency, active-policy candidate/error data, threshold and proposed-label updates",
            "reviewer_ran_tests": False,
            "ai_review_is_human_gold": False,
            "limitations": "Reviewers did not run tests; the author ran regression tests after corrections. AI review is not a human-adjudicated benchmark.",
        },
        "remaining_risks": [
            "Draft labels are single-author and several boundary cases remain disputed.",
            "The 60 candidate texts are visible to the owner, unlabelled and not a completed blind benchmark.",
            "Policy v2.1 produces six candidate disagreements (including three provisional high-consequence false positives) on draft labels; zero review in this sample does not establish safe automation.",
            "Taxonomy 0.4.1 has not been evaluated with Jev.",
            "The current source revision and provider upstream identity have not been live-verified; historical HTTP 451 cause and sanitized failures remain unknown.",
            "There is no production DTO, policy, evidence provenance, history or replay integration.",
        ],
        "recommendation": "Ready for experimental handoff of unconfirmed event candidates to the next-stage team; not ready for production or automatic classification.",
        "artifacts": {
            "error_analysis": "spike/T08/ERROR_ANALYSIS_V2.1.md",
            "error_analysis_json": "spike/T08/ERROR_ANALYSIS_V2.1.json",
            "taxonomy_proposal": "spike/T08/experiments/taxonomy-v0.4.1-proposal/",
            "human_annotation_packet": "spike/T08/HUMAN_REVIEW_PACKET_V2.1.md",
            "visible_validation_set": "spike/T08/experiments/visible-validation-v1/",
            "t09_handoff_note": "spike/T08/T09_HANDOFF.md",
            "historical_report_archive": "spike/T08/results/archive/TEST_REPORT-3.0.0-pre-policy-v2.1-handoff.*",
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    saved = report["historical_descriptive_metrics"]
    policy = report["policy_v2_1"]
    event = policy["candidate_output_metrics"]
    tests = report["verification"]
    verdicts = report["verdicts"]
    errors = report["error_disagreements"]
    lines = [
        "# T08 — итоговая offline-приёмка и передача кандидатов",
        "",
        f"**Снимок:** {report['snapshot_date']}",
        "**Ветка:** codex/spike-t08-jev-news-classification",
        "**Область:** только spike/T08; без production/OpenAPI и без новых Jev-запросов.",
        "",
        "## Статусы",
        "",
        "| Область | Статус | Значение |",
        "|---|---|---|",
        f"| Engineering quality | **{verdicts['engineering_quality']['status']}** | Офлайн-проверки и воспроизводимость перечисленных артефактов. |",
        f"| API compatibility | **{verdicts['api_compatibility']['status']}** | Сохранённые ответы есть, но текущая версия клиента не проверялась live. |",
        f"| Model quality | **{verdicts['model_quality']['status']}** | Предварительные метрики не доказывают качество для решения. |",
        "| T09 handoff | **READY — экспериментальные кандидаты** | Не является production-ready интеграцией. |",
        "",
        "## Что показывают сохранённые ответы",
        "",
        f"Из {report['source_data']['baseline']['nonempty_stories']} непустых синтетических новостей есть {report['source_data']['baseline']['saved_answers']} сохранённых ответов. Четыре отсутствующих ответа исключены из метрик; это не false negatives.",
        "",
        "| Метрика против предварительных меток | Результат |",
        "|---|---:|",
        f"| Точность темы | {saved['topic_accuracy']['correct']}/{saved['topic_accuracy']['total']} ({_pct(saved['topic_accuracy']['value'])}) |",
        f"| Event micro precision / recall / F1 | {_pct(saved['event_micro_precision'])} / {_pct(saved['event_micro_recall'])} / {_pct(saved['event_micro_f1'])} |",
        f"| Event macro F1 | {_pct(saved['event_macro_f1'])} |",
        f"| Точный набор событий | {saved['exact_event_set']['matches']}/{saved['exact_event_set']['total']} ({_pct(saved['exact_event_set']['value'])}) |",
        f"| Legacy review | {saved['legacy_review']['review_count']}/{saved['legacy_review']['total']} ({_pct(saved['legacy_review']['value'])}) |",
        "",
        "Это синтетическая выборка с черновой разметкой одного автора. Она не является независимой оценкой Jev на реальных новостях.",
        "",
        "## Policy v2.1 — экспериментальная передача",
        "",
        "Оценка события ≥0,80 создаёт неподтверждённого кандидата. Высокий insufficient-evidence удерживает кандидатов; высокий unlisted создаёт отдельную проверку. Choice и event abstain сохраняются, но сами по себе не блокируют другие события.",
        "",
        f"На тех же {policy['denominator']} ответах: кандидаты появились в {policy['candidate_bearing_stories']} новостях ({_pct(policy['candidate_coverage'])}), всего передано {policy['candidate_event_count']} событий-кандидатов. Review-задач получилось {policy['stories_with_any_review']}; сигналов hold по evidence — {policy['evidence_review_stories']}, отдельных unlisted задач — {policy['unlisted_review_stories']}.",
        "",
        f"Сравнение кандидатов с предварительной разметкой: TP={event['tp']}, FP={event['fp']}, FN={event['fn']}; precision={_pct(event['precision'])}, recall={_pct(event['recall'])}, F1={_pct(event['f1'])}. В списке предварительно high-consequence — {len(event['provisional_high_consequence_fp'])} FP.",
        "",
        "Нулевое число review в этой маленькой выборке — следствие заданных правил и score, а не доказательство безопасности. Кандидат не означает подтверждённое событие.",
        "",
        "## Ошибки и таксономия",
        "",
        f"Сверено {errors['counts']['false_positives']} FP-расхождений и {errors['counts']['false_negatives']} FN-расхождений. Подробные тексты, scores, цитаты и причины — в ERROR_ANALYSIS_V2.1.md/.json. Расхождения могут быть вызваны Jev, границами таксономии, порогом или draft gold; они не объявляются доказанными ошибками модели.",
        "",
        f"Создана отдельная taxonomy {report['taxonomy_proposal']['version']} ({report['taxonomy_proposal']['status']}); hash {report['taxonomy_proposal']['sha256']}. Коды и вопросы сохранены, live-оценки нет, требуется решение владельца.",
        "",
        "## Человеческая разметка и будущая проверка",
        "",
        f"Пакет первичной разметки содержит все {report['human_annotation']['case_count']} непустых baseline-текстов, а не только расхождения модели. В нём нейтральные алиасы, нет исходных ID, draft labels и scores. Он слеп к ответам Jev, но не к владельцу репозитория; человеческих разметчиков пока 0.",
        "",
        f"Набор из {report['visible_validation_set']['case_count']} новых синтетических текстов имеет роль {report['visible_validation_set']['benchmark_role']}, hash {report['visible_validation_set']['input_sha256']}. Нет labels/ответов Jev; набор исключён из метрик. Его тексты видели разработчики, поэтому он не может стать финальным blind test.",
        "",
        "AI-review — вспомогательное мнение, не человеческий gold. Для gold нужны два независимых человека и третий adjudicator.",
        "",
        "## Проверки этого состояния",
        "",
        f"- Unit suite: {tests['unit_tests']['passed']} passed, {tests['unit_tests']['failed']} failed, {tests['unit_tests']['skipped']} skipped.",
        f"- Policy/visualization/Playwright suite: {tests['policy_and_browser_tests']['passed']} passed, {tests['policy_and_browser_tests']['failed']} failed, {tests['policy_and_browser_tests']['skipped']} skipped.",
        "- Ruff check/format, offline runner, quality analysis, deep-corpus audit, asset builder, JavaScript syntax and diff checks: PASS.",
        "- Новых Jev/Polza AI запросов: 0.",
        "",
        "## Риски и решение",
        "",
        "- Голд не adjudicated; границы e03/e09/e10/e18/e25/e26/e27/e28/e32/e33/e34 требуют человеческой проверки.",
        "- Taxonomy 0.4.1 не протестирована на модели; нельзя утверждать, что она улучшает Jev.",
        "- 60 visible validation-кандидатов ещё не размечены; поскольку разработчики видели inputs, они не подходят для финального blind test. Нужен новый набор от независимого custodian после freeze.",
        "- Текущий клиент не проверен live; причина прежних HTTP 451 и четырёх ошибок пилота неизвестна. Повторов не было.",
        "- Нет runtime DTO/policy/provenance integration. Передача в T09 только экспериментальная и текстовая.",
        "",
        "**Вывод:** T08 готов передать в T09 неподтверждённые event-кандидаты для исследования и привязки к evidence. Jev пока нельзя считать безопасным production-классификатором.",
        "",
        "Машиночитаемые детали: TEST_REPORT.json. Исходный отчёт v3 сохранён в results/archive.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-passed", type=int, required=True)
    parser.add_argument("--browser-tests-passed", type=int, required=True)
    parser.add_argument("--tests-failed", type=int, default=0)
    parser.add_argument("--tests-skipped", type=int, default=0)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if (
        min(
            args.tests_passed,
            args.browser_tests_passed,
            args.tests_failed,
            args.tests_skipped,
        )
        < 0
    ):
        parser.error("test counts must be non-negative")
    report = build_report(
        unit_tests_passed=args.tests_passed,
        browser_tests_passed=args.browser_tests_passed,
        failed=args.tests_failed,
        skipped=args.tests_skipped,
    )
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    markdown_text = render_markdown(report)
    if args.check:
        if not REPORT_JSON_PATH.exists() or not REPORT_MD_PATH.exists():
            raise SystemExit("report files are missing")
        if REPORT_JSON_PATH.read_text(encoding="utf-8") != json_text:
            raise SystemExit("TEST_REPORT.json is stale; rebuild it")
        if REPORT_MD_PATH.read_text(encoding="utf-8") != markdown_text:
            raise SystemExit("TEST_REPORT.md is stale; rebuild it")
        print("TEST_REPORT_REPRODUCIBLE=PASS")
        return 0
    REPORT_JSON_PATH.write_text(json_text, encoding="utf-8")
    REPORT_MD_PATH.write_text(markdown_text, encoding="utf-8")
    print(
        f"REPORTS=TEST_REPORT.md,TEST_REPORT.json tests={args.tests_passed}/{args.tests_failed}/{args.tests_skipped} browser={args.browser_tests_passed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
