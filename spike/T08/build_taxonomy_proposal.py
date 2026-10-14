"""Build the unvalidated v0.4 taxonomy proposal without touching v0.3."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from jev_spike import SPIKE_DIR

SOURCE = SPIKE_DIR / "taxonomy.json"
TARGET_DIR = SPIKE_DIR / "experiments" / "taxonomy-v0.4-proposal"
TARGET = TARGET_DIR / "taxonomy.json"
MANIFEST = TARGET_DIR / "manifest.json"
SOURCE_SHA256 = "855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d"

TOPIC_CHANGES = {
    "business_companies": "Выбирай эту тему для истории о конкретной компании только если более узкая тема (право, труд, технологии, поставки, энергия или экология) не является главным предметом материала.",
    "industry_trade_supply": "Главный предмет — физическое производство, перевозка или поток товаров. Не смешивай тему с отдельными метками событий; задержка поставки сама по себе не доказывает фактический дефицит.",
    "energy_resources": "Используй для электроэнергии, топлива, добычи и рынков энергетических ресурсов. Вода, сырьё или любой производственный ресурс не относятся сюда автоматически.",
    "law_regulation": "Различай изменение общего правила и конкретное юридическое производство. Судебное заявление, расследование или исполнение решения может быть legal_enforcement; новая норма или налоговое правило — regulation_tax_change.",
    "other_uncertain": "Это резервная тема при невозможности выбрать одну из заданных тем. Не используй её как синоним недостатка доказательств бизнес-события или только потому, что событие выходит за список.",
}

EVENT_CHANGES = {
    "supply_chain_disruption": {
        "definition": "Фактическая задержка, остановка или существенное нарушение потока поставки, перевозки либо доступности входящего товара.",
        "include": "Поставки уже задержаны, сорваны или остановлены; укажи также shortage только если отдельно сообщается о недостатке запасов или мощности.",
        "exclude": "Одна только высокая цена, риск будущей задержки или дефицит без нарушения потока не подтверждают это событие.",
    },
    "shortage_capacity_constraint": {
        "definition": "Явно сообщается, что текущего запаса, ресурса или мощности недостаточно для спроса или нормальной работы.",
        "include": "Подтверждённая нехватка, исчерпание запасов, квота мощности или ограничение, которое уже сдерживает выпуск/обслуживание.",
        "exclude": "Не выводи дефицит из роста цены, поздней поставки, риска остановки или прогноза без прямого подтверждения нехватки.",
    },
    "production_operational_disruption": {
        "definition": "Фактическая остановка, сокращение или существенное нарушение действующей производственной либо операционной деятельности.",
        "include": "Завод/линия уже остановлены или работают с подтверждённым снижением выпуска; событие должно затрагивать текущую работу.",
        "exclude": "Возможная будущая остановка, плановое расширение, покупка оборудования или инвестиция в новую мощность не являются сбоем.",
    },
    "price_cost_change": {
        "definition": "Фактическое изменение цены или затрат либо официально утверждённое изменение с указанной датой вступления в силу.",
        "include": "Подтверждённое повышение/снижение цены или затрат; принятая цена может быть будущей, если сообщены решение и срок действия.",
        "exclude": "Слух, прогноз, неподтверждённая оценка или обсуждаемое, но не принятое изменение не подтверждают событие.",
    },
    "trade_restriction": {
        "definition": "Формально введённое или уже действующее правило/мера, которое ограничивает трансграничный поток товаров.",
        "include": "Запрет, квота, пошлина или иное прямо описанное ограничение импорта/экспорта; может сочетаться с sanctions, если отдельно подтверждена санкционная мера.",
        "exclude": "Обсуждение, проект или угроза меры без принятия; обычный рост стоимости торговли без ограничения потока.",
    },
    "sanctions": {
        "definition": "Официально введённая ограничительная мера, прямо обозначенная как санкция или включение в санкционный режим.",
        "include": "Санкции введены и назван объект/режим; trade_restriction ставь дополнительно только при явном ограничении товаров через границу.",
        "exclude": "Предложение, переговоры, угроза или обсуждение санкций без введённой меры.",
    },
    "regulation_tax_change": {
        "definition": "Принятое изменение общего нормативного или налогового правила, которое меняет обязательства либо условия деятельности.",
        "include": "Принятый налог, норматив или тарифный режим; при отдельно заявленном изменении цены можно отметить оба события.",
        "exclude": "Непринятый законопроект/обсуждение; индивидуальное судебное дело или расследование относится к legal_enforcement.",
    },
    "legal_enforcement": {
        "definition": "Формальное юридическое действие в отношении организации или лица: иск/заявление в суд, расследование, исполнение решения или процедура.",
        "include": "Начато официальное производство; обвинительный итог или признание нарушения не обязательны, если сам процесс подтверждён.",
        "exclude": "Само изменение общего правила; пропуск долга без отдельного юридического действия; слух о проверке.",
    },
    "insolvency_default": {
        "definition": "Подтверждённая неплатёжеспособность, формальная процедура банкротства или фактический пропуск обязательного платежа.",
        "include": "Пропущен платёж/объявлен дефолт/открыта процедура; legal_enforcement добавляй только при отдельном формальном правовом действии.",
        "exclude": "Рассмотрение возможности банкротства, кредитный риск или неподтверждённый слух без состоявшегося дефолта/процедуры.",
    },
    "investment_capacity_change": {
        "definition": "Подтверждённое решение или начатый проект по созданию, расширению либо существенному сокращению долгосрочной мощности.",
        "include": "Одобрены инвестиции, стройка, запуск новой линии или расширение мощности; labor_workforce_event возможен только при отдельно подтверждённом изменении персонала.",
        "exclude": "Текущая аварийная остановка/падение выпуска относится к production_operational_disruption; неподтверждённый план — не событие.",
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    if _sha256(SOURCE.read_bytes()) != SOURCE_SHA256:
        raise ValueError("baseline taxonomy v0.3 hash changed")
    taxonomy = json.loads(SOURCE.read_text(encoding="utf-8"))
    taxonomy["version"] = "0.4.0-spike"
    taxonomy["status"] = "unvalidated-experimental-proposal"
    taxonomy["description"] += (
        " Proposed boundary clarifications only; not live-tested, not approved, "
        "and not evidence of improved Jev quality."
    )
    for topic in taxonomy["topics"]:
        if topic["code"] in TOPIC_CHANGES:
            topic["definition"] = TOPIC_CHANGES[topic["code"]]
    for event in taxonomy["events"]:
        if event["code"] in EVENT_CHANGES:
            event.update(EVENT_CHANGES[event["code"]])
    taxonomy["annotation_rules"] = [
        *taxonomy["annotation_rules"],
        "Различай подтверждённое действие, принятое решение, обсуждение, прогноз, слух и отрицание; не считай намерение свершившимся событием.",
        "Оценивай каждую метку события независимо; несколько меток допустимы только при отдельных текстовых основаниях для каждой.",
        "Сначала выбирай тему главного предмета текста; упоминание компании или государственного органа само по себе тему не определяет.",
        "Сигнал события вне списка и недостаточность доказательств имеют разные значения. До изменения DTO это предложение не задаёт новый публичный формат ответа.",
    ]
    encoded = (json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    manifest = {
        "proposal_id": "t08-jev-taxonomy-proposal",
        "version": taxonomy["version"],
        "status": taxonomy["status"],
        "baseline_path": "spike/T08/taxonomy.json",
        "baseline_version": "0.3.0-spike",
        "baseline_sha256": SOURCE_SHA256,
        "proposal_path": "spike/T08/experiments/taxonomy-v0.4-proposal/taxonomy.json",
        "proposal_sha256": _sha256(encoded),
        "live_requests": 0,
        "approval": "awaiting_user_review",
        "evaluation_status": "not_evaluated_no_new_live_requests",
        "change_scope": "definition and annotation guidance only; codes and questions unchanged",
    }
    return taxonomy, manifest


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    taxonomy, manifest = build()
    TARGET.write_bytes(
        (json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    MANIFEST.write_bytes(
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(f"PROPOSAL={TARGET.relative_to(SPIKE_DIR)}")
    print(f"SHA256={manifest['proposal_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
