"""Recompute compact, reproducible analysis from the frozen Jev pilot files."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
NEWS_PATH = HERE / "news.json"
LABELS_PATH = HERE / "annotations.json"
RESULTS_PATH = HERE / "live-results.json"
TAXONOMY_PATH = HERE.parents[1] / "taxonomy.json"
ANALYSIS_PATH = HERE / "analysis.json"
REPORT_PATH = HERE / "PILOT_REPORT_RU.md"
POSITIVE_THRESHOLD = 0.8
NEGATIVE_THRESHOLD = 0.2


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else 0.0
        if tp + fp + fn
        else None
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _metrics(
    cases: list[dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    event_codes: list[str],
    cutoff: float,
) -> dict[str, Any]:
    tp = fp = fn = exact = emitted_stories = topic_correct = 0
    predicted_by_case: dict[str, set[str]] = {}
    for case in cases:
        case_id = case["id"]
        result = results[case_id]
        predicted = {
            code for code in event_codes if result["event_scores"][code] >= cutoff
        }
        expected = set(labels[case_id]["events"])
        predicted_by_case[case_id] = predicted
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        exact += predicted == expected
        emitted_stories += bool(predicted)
        topic_correct += result["topic"] == labels[case_id]["topic"]
    return {
        **_prf(tp, fp, fn),
        "exact_event_set_count": exact,
        "exact_event_set_accuracy": _ratio(exact, len(cases)),
        "stories_with_candidates": emitted_stories,
        "candidate_coverage": _ratio(emitted_stories, len(cases)),
        "topic_accuracy": _ratio(topic_correct, len(cases)),
        "case_count": len(cases),
        "threshold": cutoff,
        "false_positives": [
            {
                "case_id": case_id,
                "event": code,
                "score": results[case_id]["event_scores"][code],
            }
            for case_id, predicted in predicted_by_case.items()
            for code in sorted(predicted - set(labels[case_id]["events"]))
        ],
        "false_negatives": [
            {
                "case_id": case_id,
                "event": code,
                "score": results[case_id]["event_scores"][code],
            }
            for case_id, predicted in predicted_by_case.items()
            for code in sorted(set(labels[case_id]["events"]) - predicted)
        ],
    }


def analyze() -> dict[str, Any]:
    news = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
    annotations = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    report = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    cases = news["cases"]
    labels = {row["case_id"]: row for row in annotations["cases"]}
    results = {row["case_id"]: row for row in report["results"]}
    event_codes = [row["code"] for row in taxonomy["events"]]
    if (
        report.get("complete") is not True
        or report.get("successful_count") != 50
        or report.get("attempt_count") != 50
        or len(cases) != 50
        or set(labels) != {case["id"] for case in cases}
        or set(results) != set(labels)
        or report.get("resolved_model_versions") != ["jev-1.13.0"]
    ):
        raise ValueError("pilot_not_complete_or_inputs_do_not_align")

    predictions = {
        case_id: {
            code
            for code, score in row["event_scores"].items()
            if score >= POSITIVE_THRESHOLD
        }
        for case_id, row in results.items()
    }
    tp = sum(
        len(predictions[cid] & set(label["events"])) for cid, label in labels.items()
    )
    fp = sum(
        len(predictions[cid] - set(label["events"])) for cid, label in labels.items()
    )
    fn = sum(
        len(set(label["events"]) - predictions[cid]) for cid, label in labels.items()
    )
    exact = sum(
        predictions[cid] == set(label["events"]) for cid, label in labels.items()
    )
    topic_correct = sum(
        results[cid]["topic"] == label["topic"] for cid, label in labels.items()
    )
    per_event: dict[str, Any] = {}
    for code in event_codes:
        class_tp = sum(
            code in predictions[cid] and code in labels[cid]["events"] for cid in labels
        )
        class_fp = sum(
            code in predictions[cid] and code not in labels[cid]["events"]
            for cid in labels
        )
        class_fn = sum(
            code not in predictions[cid] and code in labels[cid]["events"]
            for cid in labels
        )
        support = sum(code in label["events"] for label in labels.values())
        per_event[code] = {**_prf(class_tp, class_fp, class_fn), "support": support}

    legacy_status_counts: dict[str, int] = {}
    for row in results.values():
        legacy_status_counts[row["classification_status"]] = (
            legacy_status_counts.get(row["classification_status"], 0) + 1
        )
    decisions = report["policy_v2_1_comparison"]["policy_v2"]["cases"]
    evidence_expected = [
        cid for cid, label in labels.items() if label["insufficient_evidence"]
    ]
    unlisted_expected = [
        cid for cid, label in labels.items() if label["unlisted_event"]
    ]
    evidence_threshold = float(taxonomy["thresholds"]["noul_positive_at_or_above"])
    unlisted_threshold = float(taxonomy["thresholds"]["noul_positive_at_or_above"])
    evidence_detected = [
        cid
        for cid, row in results.items()
        if row["uncertainty_score"] >= evidence_threshold
    ]
    unlisted_detected = [
        cid
        for cid, row in results.items()
        if row["unlisted_event_score"] >= unlisted_threshold
    ]
    evidence_tp = len(set(evidence_expected) & set(evidence_detected))
    evidence_fp = len(set(evidence_detected) - set(evidence_expected))
    unlisted_tp = len(set(unlisted_expected) & set(unlisted_detected))
    unlisted_fp = len(set(unlisted_detected) - set(unlisted_expected))
    positive_cells = sum(
        score >= POSITIVE_THRESHOLD
        for row in results.values()
        for score in row["event_scores"].values()
    )
    negative_cells = sum(
        score <= NEGATIVE_THRESHOLD
        for row in results.values()
        for score in row["event_scores"].values()
    )
    abstain_cells = len(cases) * len(event_codes) - positive_cells - negative_cells

    case_by_id = {case["id"]: case for case in cases}
    false_positive_details = []
    false_negative_details = []
    topic_error_details = []
    for cid in sorted(labels):
        case, label, result = case_by_id[cid], labels[cid], results[cid]
        for code in sorted(predictions[cid] - set(label["events"])):
            false_positive_details.append(
                {
                    "case_id": cid,
                    "title": case["title"],
                    "event": code,
                    "score": result["event_scores"][code],
                    "likely_issue": "taxonomy boundary or draft-label disagreement; requires human adjudication",
                }
            )
        for code in sorted(set(label["events"]) - predictions[cid]):
            false_negative_details.append(
                {
                    "case_id": cid,
                    "title": case["title"],
                    "event": code,
                    "score": result["event_scores"][code],
                    "state": "abstain"
                    if NEGATIVE_THRESHOLD
                    < result["event_scores"][code]
                    < POSITIVE_THRESHOLD
                    else "negative",
                    "likely_issue": "threshold miss, model miss, or draft-label ambiguity; inspect evidence before changing policy",
                }
            )
        if result["topic"] != label["topic"]:
            topic_error_details.append(
                {
                    "case_id": cid,
                    "title": case["title"],
                    "expected_preliminary": label["topic"],
                    "jev": result["topic"],
                    "choice_confidence": result["topic_confidence"],
                }
            )

    latencies = [row["elapsed_ms"] for row in results.values()]
    costs = [row["usage"]["cost_rub"] for row in results.values()]
    threshold_sweep = [
        _metrics(cases, labels, results, event_codes, value)
        for value in (0.6, 0.7, 0.8, 0.9)
    ]
    result = {
        "schema_version": "t08-jev-expanded-pilot-analysis-v1",
        "study_id": report["study_id"],
        "data_status": "synthetic_only_preliminary_single_curator_not_blind",
        "source_sha256": {
            "news": _sha(NEWS_PATH),
            "annotations": _sha(LABELS_PATH),
            "taxonomy": _sha(TAXONOMY_PATH),
            "live_results": _sha(RESULTS_PATH),
        },
        "model_versions": report["resolved_model_versions"],
        "sample": {
            "cases": len(cases),
            "successful_responses": len(results),
            "failed_attempts": 0,
        },
        "core_metrics_at_event_threshold_0_8": {
            "topic_accuracy": _ratio(topic_correct, len(cases)),
            "topic_correct": topic_correct,
            "topic_total": len(cases),
            **_prf(tp, fp, fn),
            "event_exact_set_accuracy": _ratio(exact, len(cases)),
            "event_exact_set_count": exact,
            "event_false_positives": false_positive_details,
            "event_false_negatives": false_negative_details,
            "topic_misclassifications": topic_error_details,
            "per_event": per_event,
        },
        "policy_comparison": {
            "legacy": report["policy_v2_1_comparison"]["legacy"],
            "policy_v2_1": report["policy_v2_1_comparison"]["policy_v2"],
            "historical_classification_status_counts": legacy_status_counts,
            "legacy_full_story_manual_review_or_other": sum(
                row["classification_status"] != "classified" for row in results.values()
            ),
            "policy_v2_1_cases_with_any_review_task": sum(
                bool(decision["needs_any_review"]) for decision in decisions.values()
            ),
            "policy_v2_1_candidate_stories": sum(
                bool(decision["candidate_codes"]) for decision in decisions.values()
            ),
            "policy_v2_1_candidate_events": sum(
                len(decision["candidate_codes"]) for decision in decisions.values()
            ),
            "uncertainty_gold_count": len(evidence_expected),
            "uncertainty_signal_at_0_8": {
                **_prf(evidence_tp, evidence_fp, len(evidence_expected) - evidence_tp),
                "detected_case_ids": evidence_detected,
            },
            "unlisted_gold_count": len(unlisted_expected),
            "unlisted_signal_at_0_8": {
                **_prf(unlisted_tp, unlisted_fp, len(unlisted_expected) - unlisted_tp),
                "detected_case_ids": unlisted_detected,
            },
            "event_score_cells_at_0_2_and_0_8": {
                "positive": positive_cells,
                "negative": negative_cells,
                "abstain": abstain_cells,
                "abstain_stories": sum(
                    any(
                        NEGATIVE_THRESHOLD < score < POSITIVE_THRESHOLD
                        for score in results[cid]["event_scores"].values()
                    )
                    for cid in results
                ),
            },
            "interpretation": "Policy v2.1 produces event candidates, not confirmed facts. Zero routed review tasks on this small set does not establish safety: high-threshold uncertainty and unlisted signals miss preliminary positives.",
        },
        "descriptive_event_threshold_sweep": threshold_sweep,
        "operations": {
            "latency_ms": {
                "n": len(latencies),
                "mean": round(statistics.fmean(latencies), 2),
                "median": statistics.median(latencies),
                "p95_nearest_rank": sorted(latencies)[
                    math.ceil(0.95 * len(latencies)) - 1
                ],
                "caveat": "descriptive; small synthetic sample, not a service-level guarantee",
            },
            "usage": {
                "input_tokens": sum(
                    row["usage"]["input_tokens"] for row in results.values()
                ),
                "output_tokens": sum(
                    row["usage"]["output_tokens"] for row in results.values()
                ),
                "reported_cost_rub": round(sum(costs), 8),
                "mean_cost_per_call_rub": round(statistics.fmean(costs), 8),
            },
        },
        "methodology": {
            "live_calls": 50,
            "retries": 0,
            "fallback_calls": 0,
            "labels_sent_to_jev": False,
            "thresholds_tuned_on_this_set": False,
            "other_model_used_as_classifier": False,
            "limitations": [
                "40 cases came from a previously visible, unclassified synthetic pool; this is not blind.",
                "All labels were drafted by one curator and have not been human-adjudicated.",
                "Per-category supports are only 2 to 4 for most event types.",
                "Choice/Noul scores are treated as scores at the configured cutoffs, not proof of calibrated real-world probabilities.",
                "Threshold sweep is descriptive and must not be used as production calibration.",
            ],
        },
        "independent_review": {
            "agent_role": "AI Factory read-only metrics/security reviewer",
            "result": "PASS: independently recomputed counts and metrics match saved report",
            "request_integrity": "50 ordered case IDs; each stored request hash matches frozen manifest",
            "privacy_scan": "no article text, prompt/question-answer map, credential, bearer string, or raw provider body found in saved live result",
            "labels_caveat": "reviewer used one-curator preliminary annotations; this is not human gold",
        },
        "error_patterns_and_next_steps": {
            "likely_taxonomy_or_annotation_boundaries": [
                {
                    "cases": ["nb-005", "xp-041-export-quota"],
                    "observation": "Jev returned both trade_restriction and regulation_tax_change as positive for trade quotas/limits.",
                    "minimal_proposal": "Clarify that regulation_tax_change requires fiscal/tax rules; explicitly exclude import/export quotas and embargoes, which belong to trade_restriction.",
                    "human_review_required": True,
                },
                {
                    "cases": ["nb-035"],
                    "observation": "price_cost_change scored 0.81 although the planned tariff change was cancelled and the old price remained.",
                    "minimal_proposal": "Make completion/effectiveness a necessary criterion and add a negative example for cancelled or merely proposed price changes.",
                    "human_review_required": False,
                },
                {
                    "cases": ["nb-039", "xp-048-shortage-supply"],
                    "observation": "shortage_capacity_constraint recall was 0/2 at 0.8; Jev scored 0.34 and 0.58. One label concerns specialist shortage and one concerns low stock alongside a delivery/production disruption.",
                    "minimal_proposal": "Add contrastive examples that separate insufficient stock/capacity, delayed inbound supply, and realized production cuts; adjudicate whether specialist shortage belongs in this event or labor_workforce_event.",
                    "human_review_required": True,
                },
                {
                    "cases": ["nb-008", "nb-025"],
                    "observation": "both preliminary legal_enforcement positives were missed (scores 0.10 and 0.16).",
                    "minimal_proposal": "Review the intended scope: regulator information requests and a court rejecting a claim may not match an enforcement-only reading. Add paired include/exclude cases only after human adjudication.",
                    "human_review_required": True,
                },
            ],
            "threshold_readout": "On this dataset only, lowering event cutoff from 0.8 to 0.7 changes FP from 3 to 10 and micro-F1 from 0.861 to 0.800; do not lower on this same set. At unlisted cutoff 0.5 the existing sweep finds 2/2 draft positives but also 18 FP, so a lower cutoff is not a safe fix.",
            "recommended_next_steps": [
                "Human-adjudicate the disputed labels and event boundaries before treating any metric as model error.",
                "Keep taxonomy 0.3 and the current pilot outputs immutable; submit a separate taxonomy proposal for review, then use a new authorized matched live pilot.",
                "Preserve Noul scores and abstain state downstream; treat emitted items only as candidates and do not interpret zero review tasks as zero uncertainty.",
                "Create a genuinely blind benchmark after freezing taxonomy, questions and thresholds; use independent human annotators and a separate adjudicator.",
                "Measure same-input repeat consistency before making claims about stability.",
                "Do not invoke DeepSeek V4 Flash fallback until Polza confirms the underlying model revision and the user approves a separate call budget.",
            ],
        },
    }
    ANALYSIS_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_markdown(result)
    return result


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _write_markdown(data: dict[str, Any]) -> None:
    core = data["core_metrics_at_event_threshold_0_8"]
    comparison = data["policy_comparison"]
    legacy = comparison["legacy"]
    policy = comparison["policy_v2_1"]
    operations = data["operations"]
    rows = [
        "# Итоги live-пилота Jev на расширенном корпусе",
        "",
        f"Исследование: `{data['study_id']}`. Все **{data['sample']['cases']}** новостей синтетические; получено **{data['sample']['successful_responses']}** валидных ответов Jev версии `{data['model_versions'][0]}`. Новых повторов, fallback и запросов к другим моделям не было.",
        "",
        "> Метки предварительные, составлены одним человеком; они не утверждены и не являются human gold. 40 примеров взяты из ранее видимого пула, поэтому выборка не слепая. Результаты описывают только этот небольшой синтетический набор.",
        "",
        "## Качество на предварительных метках",
        "",
        "| Показатель | Результат |",
        "|---|---:|",
        f"| Точность основной темы | {_percent(core['topic_accuracy'])} ({core['topic_correct']}/{core['topic_total']}) |",
        f"| Event micro precision | {_percent(core['precision'])} |",
        f"| Event micro recall | {_percent(core['recall'])} |",
        f"| Event micro F1 | {_percent(core['f1'])} |",
        f"| Точное совпадение полного набора событий | {_percent(core['event_exact_set_accuracy'])} ({core['event_exact_set_count']}/50) |",
        f"| Ложные события / пропуски | {core['fp']} / {core['fn']} |",
        "",
        "### Legacy против Policy v2.1",
        "",
        "| Показатель | Legacy | Policy v2.1 |",
        "|---|---:|---:|",
        f"| Новостей, требующих полной ручной проверки по статусу | {comparison['legacy_full_story_manual_review_or_other']}/50 | — |",
        f"| Отдельные review-задачи | — | {comparison['policy_v2_1_cases_with_any_review_task']}/50 |",
        f"| Новости с событиями-кандидатами | {legacy['stories_with_emitted_events']}/50 | {comparison['policy_v2_1_candidate_stories']}/50 |",
        f"| Переданные события-кандидаты | {legacy['emitted_event_count']} | {comparison['policy_v2_1_candidate_events']} |",
        f"| Event precision / recall / F1 | {_percent(legacy['event_output_metrics']['precision'])} / {_percent(legacy['event_output_metrics']['recall'])} / {_percent(legacy['event_output_metrics']['f1'])} | {_percent(policy['event_output_metrics']['precision'])} / {_percent(policy['event_output_metrics']['recall'])} / {_percent(policy['event_output_metrics']['f1'])} |",
        f"| Ложные события / пропуски | {legacy['event_output_metrics']['fp']} / {legacy['event_output_metrics']['fn']} | {policy['event_output_metrics']['fp']} / {policy['event_output_metrics']['fn']} |",
        "",
        "**Вывод по ручной проверке:** на этих данных Policy v2.1 не ставит всю статью в очередь из-за одного спорного сигнала и передаёт найденные события как кандидаты. Но ноль review-задач сам по себе не означает безопасность: при пороге 0,8 сигнал недостаточности данных обнаружил только часть предварительно размеченных неопределённых примеров, а unlisted-сигнал не обнаружил ни одного предварительно размеченного случая вне списка. Нельзя считать review сокращённым безопасно до человеческой валидации и слепого теста.",
        "",
        "### Результаты по типам событий",
        "",
        "| Категория | TP | FP | FN | Precision | Recall | F1 | Поддержка |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for code, metric in core["per_event"].items():
        rows.append(
            f"| `{code}` | {metric['tp']} | {metric['fp']} | {metric['fn']} | {_percent(metric['precision'])} | {_percent(metric['recall'])} | {_percent(metric['f1'])} | {metric['support']} |"
        )
    rows += ["", "### Ложные срабатывания", ""]
    for item in core["event_false_positives"]:
        rows.append(
            f"- `{item['case_id']}` — `{item['event']}` (score {item['score']:.2f}), «{item['title']}». Вероятна близкая граница taxonomy или спорность черновой метки; исправлять нужно только после человеческого решения."
        )
    rows += ["", "### Пропущенные события", ""]
    for item in core["event_false_negatives"]:
        rows.append(
            f"- `{item['case_id']}` — `{item['event']}` (score {item['score']:.2f}, `{item['state']}`), «{item['title']}». Это может быть промах Jev, следствие порога или спорной метки."
        )
    rows += [
        "",
        "### Ошибки основной темы",
        "",
        f"Jev выбрал другую тему в **{len(core['topic_misclassifications'])}/50** случаев. Это сырые расхождения с предварительной разметкой; часть требует проверки самого эталона.",
        "",
    ]
    for item in core["topic_misclassifications"]:
        rows.append(
            f"- `{item['case_id']}` — ожидается `{item['expected_preliminary']}`, Jev выбрал `{item['jev']}` (Choice confidence {item['choice_confidence']:.2f}): «{item['title']}»."
        )
    rows += [
        "",
        "## Review-сигналы Policy v2.1",
        "",
        f"- Недостаточность доказательств: предварительно размечено {comparison['uncertainty_gold_count']}; при cutoff 0,8 найдено {comparison['uncertainty_signal_at_0_8']['tp']} из них (recall {_percent(comparison['uncertainty_signal_at_0_8']['recall'])}).",
        f"- Событие вне списка: предварительно размечено {comparison['unlisted_gold_count']}; при cutoff 0,8 найдено {comparison['unlisted_signal_at_0_8']['tp']} из них (recall {_percent(comparison['unlisted_signal_at_0_8']['recall'])}).",
        "- Состояние `abstain` у отдельного события сохраняется, но само по себе не создаёт ручную задачу. Это и уменьшает очередь; оно также может скрыть ошибку, если приложение дальше игнорирует спорные оценки.",
        f"- По всем 750 ячейкам Noul: positive ≥0,8 — {comparison['event_score_cells_at_0_2_and_0_8']['positive']}; negative ≤0,2 — {comparison['event_score_cells_at_0_2_and_0_8']['negative']}; abstain — {comparison['event_score_cells_at_0_2_and_0_8']['abstain']} (в {comparison['event_score_cells_at_0_2_and_0_8']['abstain_stories']} статьях).",
        "",
        "## Пороговый анализ",
        "",
        "| Порог кандидата | Покрытие новостей | Precision | Recall | F1 | FP | FN |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in data["descriptive_event_threshold_sweep"]:
        rows.append(
            f"| {item['threshold']:.1f} | {_percent(item['candidate_coverage'])} | {_percent(item['precision'])} | {_percent(item['recall'])} | {_percent(item['f1'])} | {item['fp']} | {item['fn']} |"
        )
    rows += [
        "",
        "Таблица — только описательный sweep на тех же 50 примерах. Порог не подбирался и не считается откалиброванным. Снижение cutoff нельзя объявлять улучшением без независимого набора и проверки цены ложных срабатываний.",
        "",
        "## Задержка и стоимость",
        "",
        f"Средняя задержка {operations['latency_ms']['mean']} мс; median {operations['latency_ms']['median']} мс; p95 nearest-rank {operations['latency_ms']['p95_nearest_rank']} мс (описательно, n=50). Provider usage сообщил {operations['usage']['input_tokens']:,} входных и {operations['usage']['output_tokens']:,} выходных токенов и стоимость **{operations['usage']['reported_cost_rub']:.4f} ₽** суммарно (около {operations['usage']['mean_cost_per_call_rub']:.4f} ₽ на запрос).",
        "",
        "## Рекомендация",
        "",
        "Jev пригоден для выдачи предварительных кандидатов в исследовательском режиме, но этот прогон не доказывает, что ему можно доверить финальную классификацию. Наиболее опасный сигнал — очень низкий recall категории `shortage_capacity_constraint` при строгом пороге; дополнительно требуют разбора границы `regulation_tax_change` с торговыми ограничениями и определения `legal_enforcement`. Policy v2.1 уменьшает общую ручную очередь ценой явного отказа от автоматической проверки многих сомнительных оценок; перед передачей в следующие этапы downstream должен сохранять исходные оценки и не трактовать кандидата как факт.",
        "",
        "DeepSeek fallback не запускался: текущая идентичность Polza SKU `deepseek-v4-flash-0731` не доказывает, что это именно старые веса V4 Flash, а не V4.1. Нужны подтверждение поставщика и отдельное решение о бюджете/экспериментальном протоколе.",
        "",
        "Повторяемость одинакового запроса не измерялась: каждую из 50 историй Jev обработал один раз. Стабильность повторного ответа остаётся неизвестной.",
        "",
        "Независимый read-only reviewer сверил 50 упорядоченных ответов, request hashes, policy routing, метрики и usage; числа совпали. Отдельный AI reviewer до live-прогона проверял предварительные метки, не видя ответов Jev. Это AI advisory, а не независимая человеческая разметка.",
        "",
        "## Что стоит улучшить до следующего live-эксперимента",
        "",
        "- `nb-005` и `xp-041`: Jev одновременно ставит `trade_restriction` и `regulation_tax_change` на квоты. В следующем предложении таксономии стоит явно отделить торговые лимиты от налоговых/фискальных правил.",
        "- `nb-035`: score `price_cost_change=0.81` на отменённое повышение. Минимальное уточнение — событие цены считается положительным только после фактического изменения; отменённый план добавить как отрицательный пример.",
        "- `shortage_capacity_constraint`: 0/2 на cutoff 0,8. Примеры объединяют дефицит специалистов и низкий запас сырья; нужно развести нехватку запаса/мощности, задержку поставки и фактическое сокращение выпуска. Метки `nb-039` и `xp-048` сначала проверить человеку.",
        "- `legal_enforcement`: Jev пропустил оба черновых положительных случая (`nb-008` 0,10; `nb-025` 0,16). Нужно решить, входят ли запрос документов регулятором и отказ суда по иску в эту категорию; до этого нельзя считать обе строки бесспорными ошибками модели.",
        "- Не снижать event cutoff по этим же данным: на 0,7 FP растёт с 3 до 10, а F1 падает с 86,1% до 80,0%. Для unlisted cutoff 0,5 находит 2/2 черновых метки, но даёт 18 FP — это не безопасный выход.",
        "- Следующий шаг: человеческая adjudication спорных меток, отдельное версионированное предложение уточнений, затем новый слепой набор от независимого составителя. Текущие оценки и taxonomy v0.3 остаются замороженными.",
        "",
        "Машиночитаемые данные, включая точные ошибки, threshold sweep и SHA-256 источников, находятся в `analysis.json`; первичные безопасно сохранённые ответы — `live-results.json`.",
    ]
    REPORT_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    analysis = analyze()
    print(
        json.dumps(
            {
                "cases": analysis["sample"]["cases"],
                "topic_accuracy": analysis["core_metrics_at_event_threshold_0_8"][
                    "topic_accuracy"
                ],
                "event_micro_f1": analysis["core_metrics_at_event_threshold_0_8"]["f1"],
                "exact_set_accuracy": analysis["core_metrics_at_event_threshold_0_8"][
                    "event_exact_set_accuracy"
                ],
                "legacy_review": analysis["policy_comparison"][
                    "legacy_full_story_manual_review_or_other"
                ],
                "policy_v2_1_review_tasks": analysis["policy_comparison"][
                    "policy_v2_1_cases_with_any_review_task"
                ],
                "analysis_sha256": _sha(ANALYSIS_PATH),
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
        )
    )
