"""Render human-readable error and review tables from pinned offline analysis."""

from __future__ import annotations

import json
from typing import Any

from jev_spike import SPIKE_DIR

ANALYSIS_PATH = SPIKE_DIR / "QUALITY_ANALYSIS.json"

TOPIC_CAUSES = {
    "e06-production-fire": "Broad company topic may have beaten the more specific physical-industry subject; needs topic tie-break adjudication.",
    "e07-price-polymer": "Company-specific price change competes with the economy topic; main-focus rule is underspecified.",
    "e09-trade-export": "Government actor and trade measure can pull toward politics or industry; current examples do not give a reliable topic tie-break.",
    "e10-trade-import": "Import duty can be framed as a legal instrument or a trade-flow story; paired gold needs human confirmation.",
    "e12-sanctions-assets": "The sanctions instrument may dominate the story, while the gold topic treats it as international politics; likely topic-boundary ambiguity.",
    "e14-regulation-tax": "A tax rule has both a legal mechanism and an economic effect; the intended main-subject rule is not explicit.",
    "e18-labor-layoffs": "The main event is workforce reduction although the company is the actor; business_companies may be too broad. Gold topic needs adjudication.",
    "e24-recall-food": "A product recall combines health/safety consequences with legal or regulatory action; topic depends on the article's central focus.",
    "e28-disaster-drought": "Drought, water limits and operational impact span environment and resources; taxonomy scope is unclear.",
    "e29-investment-plant": "Industrial expansion can be labeled industry or company investment; explicit main-focus tie-break is missing.",
    "e33-multi-price-shortage": "Price plus input scarcity straddles economy and physical supply; blind review found the topic gold debatable.",
    "e42-uncertain-price-forecast": "An energy-market event can be read as macroeconomics or energy resources; topic boundary needs matched examples.",
    "e45-injection-rumor": "A device-industry story with a recall can be business or technology; the intended main subject is not decisive in v0.3.",
    "e47-unlisted-contract-award": "A public contract award can be government/politics or company/commercial activity; topic and out-of-list event labels need adjudication.",
}

EVENT_CAUSES = {
    (
        "e03-shortage-cells",
        "production_operational_disruption",
    ): "Possible over-inference from a shortage to actual production impact; verify whether the article states a current output interruption.",
    (
        "e27-disaster-flood",
        "production_operational_disruption",
    ): "Possible inference from a flood/operational threat to a confirmed production interruption; draft gold says no listed production event.",
    (
        "e25-legal-fine",
        "sanctions",
    ): "A fine or enforcement action may have been conflated with sanctions; categories need an explicit instrument distinction.",
    (
        "e09-trade-export",
        "regulation_tax_change",
    ): "A quota is a state measure, but it may not be a tax/regulatory change under the taxonomy's intended boundary; human gold review needed.",
    (
        "e10-trade-import",
        "regulation_tax_change",
    ): "A duty can qualify as a tax rule and/or trade restriction; the event definitions may permit both, so the draft gold may be too narrow.",
    (
        "e32-multi-fire-supply",
        "environment_disaster_impact",
    ): "A factory fire is not automatically environmental impact; event should require stated natural hazard or ecological/business impact.",
    (
        "e03-shortage-cells",
        "shortage_capacity_constraint",
    ): "Jev missed the explicit shortage label; could reflect weak positive criteria or competition with supply disruption/production impact.",
    (
        "e33-multi-price-shortage",
        "shortage_capacity_constraint",
    ): "The text may support a shortage alongside price change, but blind review and current corpus review disagree; gold is unresolved.",
    (
        "e18-labor-layoffs",
        "corporate_transaction_restructuring",
    ): "A workforce reduction may be mistaken for corporate restructuring; require explicit reorganization/transaction evidence.",
    (
        "e25-legal-fine",
        "legal_enforcement",
    ): "A formal fine/proceeding may be present but the model did not select the event; inspect prompt wording and score after human gold confirmation.",
    (
        "e26-legal-investigation",
        "legal_enforcement",
    ): "The label intentionally includes formal investigation without a final violation; Jev may be interpreting enforcement too narrowly.",
    (
        "e34-multi-insolvency-legal",
        "legal_enforcement",
    ): "The separate creditor filing is a plausible legal action; this is a boundary case that must remain distinct from insolvency alone.",
    (
        "e28-disaster-drought",
        "environment_disaster_impact",
    ): "Drought and water limits may be environmental impact, resource constraint, or regulation; wording and gold require human adjudication.",
}


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _load() -> dict[str, Any]:
    return json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))


def render_error_analysis(data: dict[str, Any]) -> str:
    rows = data["cases"]
    topic_errors = [row for row in rows if row["topic_mismatch"]]
    metrics = data["reproduction"]["legacy_metrics"]
    event_tp = sum(item["tp"] for item in metrics["per_event"].values())
    event_fp = sum(item["fp"] for item in metrics["per_event"].values())
    event_fn = sum(item["fn"] for item in metrics["per_event"].values())
    event_errors: list[tuple[dict[str, Any], str, str]] = []
    for row in rows:
        for code in row["event_false_positives"]:
            event_errors.append((row, "FP", code))
        for code in row["event_false_negatives"]:
            event_errors.append((row, "FN", code))
    output = [
        "# Error analysis — сохранённый Jev pilot v4",
        "",
        "Эта записка использует только 45 сохранённых валидных ответов. Четыре неуспешных кейса отсутствуют в сравнениях и не считаются FN. Текущие labels — предварительные метки одного автора; поэтому ниже разделены наблюдаемое расхождение и гипотеза о причине. Это не доказательство ошибки модели до adjudication gold.",
        "",
        f"Пилот: topic mismatch {len(topic_errors)}/45; event TP/FP/FN {event_tp}/{event_fp}/{event_fn}. Exact event set: {metrics['event_exact_match_count']}/45.",
        "",
        "## Ошибки основной темы",
        "",
        "| Case | Draft gold | Jev | Текст новости | Гипотеза и статус gold |",
        "|---|---|---|---|---|",
    ]
    for row in topic_errors:
        case_id = row["case_id"]
        output.append(
            f"| `{case_id}` | `{row['gold']['topic']}` | `{row['jev']['topic']}` | {_cell(row['text'])} | {_cell(TOPIC_CAUSES.get(case_id, 'Нужна проверка правила главной темы; mismatch не доказывает неверность gold.'))} |"
        )
    output += [
        "",
        "## Ошибки событий",
        "",
        "FP/FN ниже — сравнение пороговых меток с предварительной разметкой. Scores не являются калиброванными вероятностями. Если один кейс содержит несколько расхождений, он появляется в нескольких строках.",
        "",
        "| Case | Тип | Событие | Draft gold | Jev event labels | Текст новости | Гипотеза / вопрос к gold |",
        "|---|---|---|---|---|---|---|",
    ]
    for row, error_type, code in event_errors:
        detail = EVENT_CAUSES.get(
            (row["case_id"], code),
            "Проверить наличие прямого свидетельства и границу с соседними классами.",
        )
        output.append(
            f"| `{row['case_id']}` | {error_type} | `{code}` | `{', '.join(row['gold']['events']) or '∅'}` | `{', '.join(row['jev']['events']) or '∅'}` | {_cell(row['text'])} | {_cell(detail)} |"
        )
    output += [
        "",
        "## Отдельные наблюдения",
        "",
        "- `legal_enforcement`: recall 0/3; сохранённые оценки не дали ни одного positive prediction на пороге 0.8. Это может быть вопросом формулировки Noul/границы класса, но также требует проверки gold.",
        "- `shortage_capacity_constraint`: recall 1/3; e03 и e33 не распознаны. e33 особенно спорен: один reviewer независимо отметил прямое свидетельство нехватки, второй аудит оставил gold на adjudication.",
        "- Out-of-list signal: в исходных 45 ответах нет ни одного score ≥0.8; один gold out-of-list кейс e47 имеет score около 0.59 и находится лишь в серой зоне. Текущий review-gate ловит его ценой многих нерешённых сигналов.",
        "- Неопределённые кейсы: e40/e41/e43 и похожие сообщения должны разбираться отдельно от фактической ошибки метки. e41 и e43 не имеют успешного ответа Jev.",
        "- Multi-label exact accuracy сильно ниже micro-F1 на небольшом multi-event срезе: одно пропущенное или лишнее событие делает весь набор неверным.",
        "",
        "## Пропуски и ограничения",
        "",
        "Неуспешные запросы: `e23-recall-battery`, `e35-multi-labor-investment`, `e41-uncertain-sanctions-talk`, `e43-uncertain-vague-delivery`. Для них нет Jev score и нет основания ставить FN/FP. e35 — gold boundary по трудовой метке, но ответ отсутствует.",
        "",
        "AI reviewer и авторский аудит не являются независимыми человеческими аннотаторами. До human review нельзя исправлять source corpus или выдавать эти категории за окончательные ошибки Jev.",
        "",
        "Подробные per-case scores и trigger fields: `QUALITY_ANALYSIS.json`; hashes и контроль воспроизводимости — `quality_analysis.py`.",
        "",
    ]
    return "\n".join(output)


def render_uncertainty(data: dict[str, Any]) -> str:
    summary = data["review_summary"]
    output = [
        "# Uncertainty analysis — почему review составляет 93,3%",
        "",
        "## Короткий ответ",
        "",
        "42 из 45 сохранённых ответов получают `uncertain` по историческому rule gate. Это не равнозначно тому, что Jev не выбрал тему или не распознал события. Сигналы пересекаются, а один средний Noul score сейчас трактуется слишком широко как review-триггер.",
        "",
        "## Точный разбор текущего rule gate",
        "",
        "| Причина | Срабатываний на кейсах review | Доля от 45 | Что в действительности означает |",
        "|---|---:|---:|---|",
        f"| Choice confidence < 0.5 | {summary['active_trigger_case_counts_overlapping']['choice']} | {summary['active_trigger_case_counts_overlapping']['choice'] / 45:.1%} | Выбранная тема не достигла экспериментального порога |",
        f"| Хотя бы один event score в серой зоне (0.2, 0.8) | {summary['active_trigger_case_counts_overlapping']['event_scores']} | {summary['active_trigger_case_counts_overlapping']['event_scores'] / 45:.1%} | Неопределённость хотя бы одного event Noul; не вся классификация |",
        f"| Insufficient-evidence score > 0.2 | {summary['active_trigger_case_counts_overlapping']['uncertainty']} | {summary['active_trigger_case_counts_overlapping']['uncertainty'] / 45:.1%} | Склеивает серую зону и positive score в один review signal |",
        f"| Unlisted-event score > 0.2 | {summary['active_trigger_case_counts_overlapping']['unlisted']} | {summary['active_trigger_case_counts_overlapping']['unlisted'] / 45:.1%} | Очень широкий индикатор возможного события вне списка |",
        f"| Итого review | {summary['review_count']} | {summary['review_rate']:.1%} | Не складывать причины: они перекрываются |",
        "",
        f"Trigger combinations: {summary['review_cases_with_multiple_reasons']} из 42 review имеют несколько причин; {summary['review_cases_with_exactly_one_reason']} — ровно одну. В последних: unlisted=8, insufficient-evidence=5, event band=1, Choice-only=0. Всего активных триггеров 78, а не 42.",
        "",
        "Историческая ветка `other_uncertain` игнорирует event-band и unlisted triggers. Поэтому raw и effective trigger counts различаются: event band 25→24, unlisted 33→32; e50 и e46 показывают это исключение. Полный список всех 45 с Choice, event scores, uncertainty, unlisted и final status приведён ниже.",
        "",
        "## Noul состояния — не путать с review gate",
        "",
        "При утверждённых экспериментальных границах `<=0.2 negative`, `>=0.8 positive`, между ними `abstain`:",
        "",
        f"- Недостаточность доказательств: {summary['noul_state_counts']['insufficient_evidence']}. 17 review-триггеров — это 14 abstain + 3 positive; только три score достигают positive-зоны.",
        f"- Событие вне списка: {summary['noul_state_counts']['unlisted']}. Все 33 score выше 0.2 находятся в abstain, ни один не positive; 12 negative.",
        "- Следовательно, `score > 0.2 → review` — широкое защитное правило, но оно превращает `abstain` в эквивалент положительной причины для отказа в автоматической классификации.",
        "- С другой стороны, ослабление правила без независимой калибровки может автоматически принять действительно неполные или out-of-list сообщения. Таблица policy ниже показывает этот риск на тех же 45 кейсах.",
        "",
        "## Все успешные ответы",
        "",
        "Scores показаны для всех 15 событий и двух сигналов, без округления выше двух знаков. `Topic gold → Jev`. Четыре неуспешных вызова перечислены после таблицы; им не приписываются искусственные оценки.",
        "",
        "| Case | Topic gold → Jev | Choice | Event scores: code=score | Uncertainty | Unlisted | Active review triggers | Final status |",
        "|---|---|---:|---|---:|---:|---|---|",
    ]
    for row in data["cases"]:
        scores = "; ".join(
            f"{code}={score:.2f}" for code, score in row["jev"]["event_scores"].items()
        )
        active = row["review"]["active_code_triggers"]
        trigger_list = (
            ", ".join(name for name, value in active.items() if value) or "none"
        )
        output.append(
            f"| `{row['case_id']}` | `{row['gold']['topic']}` → `{row['jev']['topic']}` | {row['jev']['choice_confidence']:.3f} | {_cell(scores)} | {row['jev']['uncertainty_score']:.3f} | {row['jev']['unlisted_score']:.3f} | {trigger_list} | {row['jev']['status']} |"
        )
    output += [
        "",
        "Нет успешного ответа Jev: `e23-recall-battery`, `e35-multi-labor-investment`, `e41-uncertain-sanctions-talk`, `e43-uncertain-vague-delivery`. Причины sanitized failures неизвестны; повторного запроса не было.",
        "",
    ]
    return "\n".join(output)


def main() -> int:
    data = _load()
    (SPIKE_DIR / "ERROR_ANALYSIS.md").write_text(
        render_error_analysis(data), encoding="utf-8"
    )
    (SPIKE_DIR / "UNCERTAINTY_ANALYSIS.md").write_text(
        render_uncertainty(data), encoding="utf-8"
    )
    print("RENDERED=ERROR_ANALYSIS.md,UNCERTAINTY_ANALYSIS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
