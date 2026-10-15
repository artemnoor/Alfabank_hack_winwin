"""Build a frozen, synthetic-only Jev pilot set and draft annotations.

The 40 source stories are copied from the existing future-candidate pool. Ten
additional stories extend event and writing-style coverage. Labels are authored
before any Jev calls and stored separately from request text.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "experiments" / "future-blind-candidate-v1" / "news.json"
SOURCE_MANIFEST = SOURCE.parent / "manifest.json"
ANNOTATION_REVIEW = OUT / "ANNOTATION_REVIEW.md"
sys.path.insert(0, str(ROOT))
from jev_spike import DEFAULT_MODEL, make_request, request_hash, taxonomy_hash  # noqa: E402

ADDITIONAL = [
    {
        "id": "xp-041-export-quota",
        "title": "Экспортный лимит на полимер вступил в силу",
        "text": "Правительство опубликовало постановление о квартальной квоте на вывоз промышленного полимера. Таможня начала применять лимит 1 октября; несколько поставщиков подтвердили, что новые партии оформляются в пределах установленного объёма.",
    },
    {
        "id": "xp-042-ransomware",
        "title": "Атака зашифровала внутренние системы сети аптек",
        "text": "Сеть «Ромашка-Фарм» подтвердила кибератаку: часть внутренних серверов зашифрована, а корпоративные кабинеты временно отключены. Розничные точки продолжают отпускать лекарства; проверка возможной утечки данных ещё идёт.",
    },
    {
        "id": "xp-043-strike",
        "title": "Работники терминала начали объявленную забастовку",
        "text": "Профсоюз грузового терминала «Восточный причал» сообщил, что 64 сотрудника начали забастовку после отклонения коллективного соглашения. Руководство и представители работников встретятся завтра при посредничестве трудовой инспекции.",
    },
    {
        "id": "xp-044-insolvency-lawsuit",
        "title": "Компания пропустила купонный платёж, кредитор подал иск",
        "text": "АО «Меридиан-Строй» не перечислило держателям облигаций купон в установленную дату, что подтверждено сообщением биржи. Один из кредиторов отдельно подал в арбитраж иск о взыскании долга; заявление принято к производству.",
    },
    {
        "id": "xp-045-flood-factory",
        "title": "Паводок повредил цех и остановил выпуск на площадке",
        "text": "После разлива реки вода повредила электрощитовую завода «Берег-Маш». Компания подтвердила остановку сборочной линии и эвакуацию смены; оценка ущерба продолжается, повторный запуск пока не назначен.",
    },
    {
        "id": "xp-046-tax-law",
        "title": "Новый налоговый сбор для отрасли утверждён парламентом",
        "text": "Парламент принял закон о дополнительном сборе для производителей минеральных удобрений. Документ подписан и опубликован, новая ставка применяется с 1 января следующего года.",
    },
    {
        "id": "xp-047-sanctions-and-trade",
        "title": "Ограничительный список расширен, импорт части товара запрещён",
        "text": "Министерство включило компанию «Норд-Компонент» в санкционный перечень и заморозило её активы. Отдельное постановление таможенной службы запретило ввоз двух моделей контроллеров из страны регистрации компании.",
    },
    {
        "id": "xp-048-shortage-supply",
        "title": "Задержка сырья оставила фабрику без запаса на месяц",
        "text": "Поставщик не доставил согласованную партию промышленного волокна на фабрику «ЛёнТех» к сроку. Остатка сырья хватит на четыре дня, поэтому предприятие уже сократило выпуск двух изделий до восстановления поставок.",
    },
    {
        "id": "xp-049-capacity-investment",
        "title": "Производитель вложит средства в третью линию сборки",
        "text": "Совет директоров «Орбита-Прибор» утвердил капитальный проект стоимостью 2,4 млрд рублей. На заводе построят третью линию сборки, которая после ввода увеличит годовую мощность с 80 до 110 тысяч устройств.",
    },
    {
        "id": "xp-050-recall",
        "title": "Регулятор распорядился отозвать партию детских кресел",
        "text": "Проверка выявила дефект крепления в 3 200 автомобильных креслах компании «Парус-Деталь». Регулятор опубликовал обязательное предписание об отзыве партии, а производитель открыл бесплатную замену изделий.",
    },
]

# Topic/event labels and evidence were drafted from the text alone. These are
# preliminary reference annotations, not human-adjudicated gold labels.
LABELS: dict[str, dict[str, Any]] = {
    "nb-001": {
        "topic": "industry_trade_supply",
        "events": ["supply_chain_disruption"],
        "evidence": {
            "supply_chain_disruption": "выдача партии промышленных сканеров сдвигается на четыре дня"
        },
    },
    "nb-002": {
        "topic": "industry_trade_supply",
        "events": [],
        "unlisted": True,
        "evidence": {
            "unlisted_business_event": "В октябре торговая группа «Маяк» сократит число заказов"
        },
        "review_note": "Пограничное: официально объявлено будущее сокращение заказов; проверить, считать ли закупочное решение самостоятельным событием вне списка.",
    },
    "nb-003": {
        "topic": "industry_trade_supply",
        "events": ["production_operational_disruption"],
        "evidence": {
            "production_operational_disruption": "линия упаковки не работает со вчерашнего вечера"
        },
    },
    "nb-004": {
        "topic": "industry_trade_supply",
        "events": ["price_cost_change"],
        "evidence": {"price_cost_change": "цены на 6 процентов выше прежних"},
    },
    "nb-005": {
        "topic": "politics_government",
        "events": ["trade_restriction"],
        "evidence": {
            "trade_restriction": "утвердила квартальную квоту на импорт отдельных видов упаковочного сырья"
        },
    },
    "nb-006": {
        "topic": "politics_government",
        "events": ["sanctions"],
        "evidence": {
            "sanctions": "включении трёх зарубежных поставщиков в официальный санкционный перечень"
        },
    },
    "nb-007": {
        "topic": "law_regulation",
        "events": ["regulation_tax_change"],
        "evidence": {
            "regulation_tax_change": "Парламент принял поправку к общему порядку инвестиционного вычета"
        },
    },
    "nb-008": {
        "topic": "law_regulation",
        "events": ["legal_enforcement"],
        "evidence": {
            "legal_enforcement": "официально открыло проверку работы «Городского терминала»"
        },
    },
    "nb-009": {
        "topic": "labor_employment",
        "events": ["labor_workforce_event"],
        "evidence": {"labor_workforce_event": "сообщил о начале забастовки"},
    },
    "nb-010": {
        "topic": "economy_finance",
        "events": ["insolvency_default", "legal_enforcement"],
        "evidence": {
            "insolvency_default": "не перечислила очередной платёж по кредиту в установленный день",
            "legal_enforcement": "Кредитор подал иск о взыскании долга",
        },
        "review_note": "Пограничное: проверить, что просрочка одного кредитного платежа соответствует определению дефолта.",
    },
    "nb-011": {
        "topic": "business_companies",
        "events": ["investment_capacity_change"],
        "evidence": {
            "investment_capacity_change": "подписал соглашение о финансировании цеха"
        },
    },
    "nb-012": {
        "topic": "business_companies",
        "events": ["product_recall_quality_safety"],
        "evidence": {
            "product_recall_quality_safety": "попросила магазины снять с продажи 18 тысяч адаптеров из-за риска перегрева"
        },
    },
    "nb-013": {
        "topic": "technology_telecom",
        "events": ["cyber_security_incident"],
        "evidence": {
            "cyber_security_incident": "после атаки на внешнюю инфраструктуру"
        },
    },
    "nb-014": {
        "topic": "environment_disasters",
        "events": ["environment_disaster_impact", "supply_chain_disruption"],
        "evidence": {
            "environment_disaster_impact": "После подъёма воды муниципалитет ограничил проезд грузовых машин по мосту",
            "supply_chain_disruption": "сообщил о переносе части рейсов",
        },
    },
    "nb-015": {
        "topic": "environment_disasters",
        "events": [],
        "evidence": {},
        "review_note": "Пограничная тема: новость о засухе и региональном ограничении, при этом бизнес не затронут.",
    },
    "nb-016": {
        "topic": "industry_trade_supply",
        "events": ["corporate_transaction_restructuring"],
        "evidence": {
            "corporate_transaction_restructuring": "утвердил закрытие одного распределительного центра"
        },
    },
    "nb-017": {
        "topic": "technology_telecom",
        "events": [],
        "unlisted": True,
        "evidence": {
            "unlisted_business_event": "Соглашение на три года подписано обеими сторонами"
        },
    },
    "nb-018": {
        "topic": "politics_government",
        "events": [],
        "uncertain": True,
        "evidence": {
            "insufficient_evidence": "Официального решения и даты вступления меры в силу пока нет"
        },
    },
    "nb-019": {
        "topic": "business_companies",
        "events": [],
        "uncertain": True,
        "evidence": {"insufficient_evidence": "независимого подтверждения слуха нет"},
        "review_note": "Пограничное: компания отрицает слух и показывает платежи, независимого подтверждения сообщения нет.",
    },
    "nb-020": {
        "topic": "industry_trade_supply",
        "events": [],
        "uncertain": True,
        "evidence": {
            "insufficient_evidence": "допустил, что линия будет остановлена на следующей неделе, если подрядчик не завершит обслуживание турбины"
        },
    },
    "nb-021": {"topic": "law_regulation", "events": [], "evidence": {}},
    "nb-022": {"topic": "industry_trade_supply", "events": [], "evidence": {}},
    "nb-023": {
        "topic": "business_companies",
        "events": [],
        "review_note": "Пограничное: разовое опоздание покупателя с оплатой не приравнено к дефолту компании без признака долга/банкротства.",
    },
    "nb-024": {
        "topic": "industry_trade_supply",
        "events": [],
        "uncertain": True,
        "evidence": {
            "insufficient_evidence": "Ни одна из сторон не уточнила, какие именно партии затронуты"
        },
    },
    "nb-025": {
        "topic": "law_regulation",
        "events": ["legal_enforcement"],
        "evidence": {
            "legal_enforcement": "Арбитражный суд отказал подрядчику во взыскании дополнительной платы"
        },
    },
    "nb-026": {
        "topic": "economy_finance",
        "events": ["price_cost_change"],
        "evidence": {
            "price_cost_change": "повышении закупочной цены на оптические модули на 4 процента"
        },
    },
    "nb-027": {"topic": "technology_telecom", "events": [], "evidence": {}},
    "nb-028": {
        "topic": "economy_finance",
        "events": [],
        "uncertain": True,
        "evidence": {
            "insufficient_evidence": "Источник не поясняет, к какому именно продукту относятся отдельные цифры"
        },
    },
    "nb-029": {"topic": "industry_trade_supply", "events": [], "evidence": {}},
    "nb-030": {"topic": "business_companies", "events": [], "evidence": {}},
    "nb-031": {
        "topic": "business_companies",
        "events": ["corporate_transaction_restructuring"],
        "evidence": {
            "corporate_transaction_restructuring": "согласовали график погашения задолженности"
        },
        "review_note": "Пограничное: согласованный график может быть реструктуризацией долга, хотя платежи ещё не просрочены.",
    },
    "nb-032": {"topic": "health", "events": [], "evidence": {}},
    "nb-033": {
        "topic": "industry_trade_supply",
        "events": ["supply_chain_disruption"],
        "evidence": {"supply_chain_disruption": "сообщили о задержке вагонов на сутки"},
    },
    "nb-034": {
        "topic": "business_companies",
        "events": ["corporate_transaction_restructuring", "investment_capacity_change"],
        "evidence": {
            "corporate_transaction_restructuring": "утвердил продажу непрофильного склада",
            "investment_capacity_change": "одобрил строительство новой линии сборки",
        },
    },
    "nb-035": {
        "topic": "business_companies",
        "events": [],
        "evidence": {},
        "review_note": "Пограничное: отменено будущее изменение тарифа; фактического изменения цены не было.",
    },
    "nb-036": {
        "topic": "law_regulation",
        "events": [],
        "uncertain": True,
        "evidence": {
            "insufficient_evidence": "Одно ведомство заявило о приостановке выдачи разрешений, другое сообщило, что ранее выданные документы продолжают действовать"
        },
    },
    "nb-037": {"topic": "labor_employment", "events": [], "evidence": {}},
    "nb-038": {"topic": "technology_telecom", "events": [], "evidence": {}},
    "nb-039": {
        "topic": "technology_telecom",
        "events": ["shortage_capacity_constraint"],
        "evidence": {
            "shortage_capacity_constraint": "команда не успевает завершить проверку безопасности"
        },
        "review_note": "Пограничное: дефицит специалистов прямо не назван, но нехватка команды ограничивает срок проекта.",
    },
    "nb-040": {
        "topic": "other_uncertain",
        "events": [],
        "uncertain": True,
        "evidence": {
            "insufficient_evidence": "Редакция не подтверждает ни это утверждение, ни связь письма с какой-либо компанией"
        },
    },
    "xp-041-export-quota": {
        "topic": "politics_government",
        "events": ["trade_restriction"],
        "evidence": {"trade_restriction": "Таможня начала применять лимит 1 октября"},
    },
    "xp-042-ransomware": {
        "topic": "technology_telecom",
        "events": ["cyber_security_incident"],
        "evidence": {
            "cyber_security_incident": "подтвердила кибератаку: часть внутренних серверов зашифрована"
        },
    },
    "xp-043-strike": {
        "topic": "labor_employment",
        "events": ["labor_workforce_event"],
        "evidence": {"labor_workforce_event": "64 сотрудника начали забастовку"},
    },
    "xp-044-insolvency-lawsuit": {
        "topic": "economy_finance",
        "events": ["insolvency_default", "legal_enforcement"],
        "evidence": {
            "insolvency_default": "не перечислило держателям облигаций купон в установленную дату",
            "legal_enforcement": "Один из кредиторов отдельно подал в арбитраж иск о взыскании долга",
        },
    },
    "xp-045-flood-factory": {
        "topic": "environment_disasters",
        "events": ["environment_disaster_impact", "production_operational_disruption"],
        "evidence": {
            "environment_disaster_impact": "вода повредила электрощитовую завода",
            "production_operational_disruption": "подтвердила остановку сборочной линии",
        },
    },
    "xp-046-tax-law": {
        "topic": "law_regulation",
        "events": ["regulation_tax_change"],
        "evidence": {
            "regulation_tax_change": "Парламент принял закон о дополнительном сборе"
        },
    },
    "xp-047-sanctions-and-trade": {
        "topic": "politics_government",
        "events": ["sanctions", "trade_restriction"],
        "evidence": {
            "sanctions": "включило компанию «Норд-Компонент» в санкционный перечень и заморозило её активы",
            "trade_restriction": "запретило ввоз двух моделей контроллеров",
        },
    },
    "xp-048-shortage-supply": {
        "topic": "industry_trade_supply",
        "events": [
            "supply_chain_disruption",
            "shortage_capacity_constraint",
            "production_operational_disruption",
        ],
        "evidence": {
            "supply_chain_disruption": "Поставщик не доставил согласованную партию промышленного волокна",
            "shortage_capacity_constraint": "Остатка сырья хватит на четыре дня",
            "production_operational_disruption": "предприятие уже сократило выпуск двух изделий",
        },
        "review_note": "Пограничное: три кода описывают связанные, но отдельно подтверждённые звенья одной цепочки.",
    },
    "xp-049-capacity-investment": {
        "topic": "industry_trade_supply",
        "events": ["investment_capacity_change"],
        "evidence": {
            "investment_capacity_change": "утвердил капитальный проект стоимостью 2,4 млрд рублей"
        },
    },
    "xp-050-recall": {
        "topic": "health",
        "events": ["product_recall_quality_safety"],
        "evidence": {
            "product_recall_quality_safety": "обязательное предписание об отзыве партии"
        },
    },
}


def _dump(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> None:
    if (OUT / "live-results.json").exists():
        raise RuntimeError("refusing to rebuild a pilot after live results exist")
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    if _sha(SOURCE) != source_manifest.get("news_sha256"):
        raise RuntimeError("source candidate pool hash mismatch")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = [
        {"id": row["id"], "title": row["title"], "text": row["text"]}
        for row in source["cases"]
    ]
    rows.extend(ADDITIONAL)
    if len(rows) != 50 or len({row["id"] for row in rows}) != 50:
        raise ValueError("pilot must have exactly 50 unique cases")
    if set(LABELS) != {row["id"] for row in rows}:
        raise ValueError("every request case must have a pre-authored annotation")
    for row in rows:
        label = LABELS[row["id"]]
        if not row["title"].strip() or not row["text"].strip():
            raise ValueError(f"empty synthetic news: {row['id']}")
        for code, quote in label.get("evidence", {}).items():
            if quote not in row["text"]:
                raise ValueError(
                    f"evidence does not match article: {row['id']} / {code}"
                )

    news = {
        "dataset_id": "jev-ru-expanded-pilot",
        "version": "1.0.0",
        "status": "pre-registered-synthetic-only-exploratory",
        "language": "ru_with_one_mixed_language_case",
        "case_count": len(rows),
        "content_origin": "synthetic only; no real news or user text",
        "labels_in_request_file": False,
        "cases": rows,
    }
    annotations = {
        "schema_version": "t08-preliminary-annotations-v1",
        "status": "draft_single_curator_annotations_not_human_adjudicated",
        "authored_before_jev_calls": True,
        "jevs_outputs_used_for_annotation": False,
        "annotator_count": 1,
        "independent_ai_review_is_not_human_gold": True,
        "taxonomy_version": "0.3.0-spike",
        "cases": [
            {
                "case_id": row["id"],
                "topic": LABELS[row["id"]]["topic"],
                "events": LABELS[row["id"]].get("events", []),
                "unlisted_event": LABELS[row["id"]].get("unlisted", False),
                "insufficient_evidence": LABELS[row["id"]].get("uncertain", False),
                "evidence_spans": LABELS[row["id"]].get("evidence", {}),
                "review_note": LABELS[row["id"]].get("review_note"),
                "label_status": "preliminary_unapproved",
            }
            for row in rows
        ],
    }
    _dump(OUT / "news.json", news)
    _dump(OUT / "annotations.json", annotations)
    taxonomy = ROOT / "taxonomy.json"
    taxonomy_value = json.loads(taxonomy.read_text(encoding="utf-8"))
    approved_requests = {
        row["id"]: request_hash(make_request(row, taxonomy_value, model=DEFAULT_MODEL))
        for row in rows
    }
    manifest = {
        "study_id": news["dataset_id"] + "-" + news["version"],
        "status": "frozen_before_jev_run",
        "call_budget": 50,
        "maximum_new_jev_calls": 50,
        "retries": 0,
        "fallback_models": 0,
        "news_path": "spike/T08/experiments/jev-expanded-pilot-v1/news.json",
        "news_sha256": _sha(OUT / "news.json"),
        "source_candidate_news_sha256": _sha(SOURCE),
        "source_candidate_pool_blind": False,
        "annotations_path": "spike/T08/experiments/jev-expanded-pilot-v1/annotations.json",
        "annotations_sha256": _sha(OUT / "annotations.json"),
        "annotation_review_path": "spike/T08/experiments/jev-expanded-pilot-v1/ANNOTATION_REVIEW.md",
        "annotation_review_sha256": _sha(ANNOTATION_REVIEW),
        "dataset_builder_path": "spike/T08/experiments/jev-expanded-pilot-v1/build_dataset.py",
        "dataset_builder_sha256": _sha(Path(__file__)),
        "baseline_taxonomy_path": "spike/T08/taxonomy.json",
        "baseline_taxonomy_version": "0.3.0-spike",
        "baseline_taxonomy_sha256": _sha(taxonomy),
        "baseline_taxonomy_canonical_sha256": taxonomy_hash(taxonomy_value),
        "approved_request_sha256_by_case": approved_requests,
        "runner_path": "spike/T08/experiments/jev-expanded-pilot-v1/run_pilot.py",
        "runner_sha256": _sha(OUT / "run_pilot.py"),
        "request_model_id": "typesafe/jev",
        "runner_policy": "one request per case; reserve before request; any failure consumes attempt and stops run",
        "soft_stop_after_cost_rub": 10.0,
        "estimated_cost_per_request_rub": 0.20,
        "cost_guard_is_hard_cap": False,
        "price_reference": "Polza Jev catalog, observed 2026-10-15; price is mutable; response usage.cost_rub is recorded; estimated threshold may be exceeded by one request",
        "new_live_calls": 0,
        "live_results": "not_run",
        "gold_limit": "single-curator draft labels with evidence spans; not human-adjudicated and not a blind test",
        "request_safety": "only synthetic title/text sent; expected labels and notes are stored separately and excluded from request payload",
    }
    _dump(OUT / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "cases": len(rows),
                "new_cases": len(ADDITIONAL),
                "news_sha256": manifest["news_sha256"],
                "annotations_sha256": manifest["annotations_sha256"],
                "taxonomy_sha256": manifest["baseline_taxonomy_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    build()
