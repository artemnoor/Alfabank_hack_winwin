"""Build the unvalidated T08 taxonomy v0.4.2 proposal from v0.4.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stable_hash import sha256_text_bytes

ROOT = Path(__file__).resolve().parent
PARENT_DIR = ROOT / "experiments" / "taxonomy-v0.4.1-proposal"
PARENT = PARENT_DIR / "taxonomy.json"
PARENT_MANIFEST = PARENT_DIR / "manifest.json"
TARGET_DIR = ROOT / "experiments" / "taxonomy-v0.4.2-proposal"
TARGET = TARGET_DIR / "taxonomy.json"
MANIFEST = TARGET_DIR / "manifest.json"
PARENT_SHA256 = "80d40bbccd0c50220e26112418f571f3e883d162f5a5e40f94064719697e4a19"
PARENT_MANIFEST_SHA256 = (
    "9776bdd6c6cf90872afed92cbb3608d1a0124c186642593d504f966b2aedc396"
)
BASELINE_SHA256 = "855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d"


def _sha256(raw: bytes) -> str:
    return sha256_text_bytes(raw)


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    parent_raw = PARENT.read_bytes()
    parent_manifest_raw = PARENT_MANIFEST.read_bytes()
    if _sha256(parent_raw) != PARENT_SHA256:
        raise ValueError("v0.4.1 proposal changed; refusing to rewrite history")
    if _sha256(parent_manifest_raw) != PARENT_MANIFEST_SHA256:
        raise ValueError("v0.4.1 manifest changed; refusing to rewrite history")

    parent_manifest = json.loads(parent_manifest_raw.decode("utf-8"))
    taxonomy = json.loads(parent_raw.decode("utf-8"))
    if parent_manifest.get("baseline_sha256") != BASELINE_SHA256:
        raise ValueError("proposal parent is not based on frozen taxonomy v0.3")

    taxonomy["version"] = "0.4.2-spike"
    taxonomy["status"] = "unvalidated-experimental-proposal"
    taxonomy["description"] = (
        "Offline refinement of taxonomy boundaries from the 45 saved Jev outputs "
        "and independent AI label review. Codes and score thresholds are unchanged. "
        "This proposal is not human-approved, not live-tested, and does not establish "
        "improved Jev quality."
    )
    events = {row["code"]: row for row in taxonomy["events"]}
    events["shortage_capacity_constraint"].update(
        {
            "definition": (
                "Текущего подтверждённого запаса, ресурса или мощности недостаточно "
                "для спроса или нормальной работы."
            ),
            "include": (
                "Прямо сообщается о фактической нехватке либо недостаточном запасе, "
                "который уже ограничивает работу. Оцени эту метку отдельно от сбоя "
                "поставок, остановки производства и изменения цены; каждую метку "
                "подкрепляй отдельной фразой из текста."
            ),
            "exclude": (
                "Не выводи нехватку только из роста цены, поздней поставки, риска "
                "остановки, прогноза или наличия складов."
            ),
        }
    )
    events["production_operational_disruption"].update(
        {
            "definition": (
                "Фактическая остановка производства или прямо сообщённое существенное "
                "сокращение выпуска действующей линии/площадки."
            ),
            "include": (
                "В тексте прямо сказано, что производство или выпуск остановлен либо "
                "снижен. Указанный будущий срок учитывается только как официально "
                "принятое решение, а не как уже состоявшаяся остановка."
            ),
            "exclude": (
                "Недоступность площадки, отсутствие смены, задержка отгрузки или "
                "нехватка сырья сами по себе не доказывают остановку выпуска."
            ),
        }
    )
    events["trade_restriction"].update(
        {
            "include": (
                "Уже принятое/действующее ограничение на импорт или экспорт: запрет, "
                "квота, лицензирование либо таможенная пошлина. Одну и ту же меру "
                "не дублируй в regulation_tax_change без отдельного изменения общего "
                "налогового правила."
            ),
            "exclude": (
                "Обсуждение, проект или угроза без принятия; внутреннее налоговое "
                "правило; повышение цены без ограничения трансграничного потока."
            ),
        }
    )
    events["regulation_tax_change"].update(
        {
            "definition": (
                "Принятое изменение общего налогового или внутреннего нормативного "
                "правила, меняющее обязанности или условия деятельности."
            ),
            "include": (
                "Отмечай отдельное изменение общего правила, применимого шире одной "
                "таможенной меры. Для пошлины/квоты ставь trade_restriction; обе метки "
                "допустимы, если текст сообщает отдельные правовые изменения."
            ),
            "exclude": (
                "Квота или пошлина на конкретный импорт/экспорт без самостоятельного "
                "общего налогового правила; индивидуальный иск, штраф или расследование."
            ),
        }
    )
    events["sanctions"].update(
        {
            "definition": (
                "Официальная ограничительная мера, явно введённая как санкция либо "
                "как элемент санкционного режима."
            ),
            "include": (
                "Орган подтверждает введение санкции, включение в санкционный режим "
                "или заморозку активов именно как санкционную меру."
            ),
            "exclude": (
                "Обычный антимонопольный/административный штраф, судебное взыскание "
                "или наказание относятся к legal_enforcement, если санкционный режим "
                "не назван прямо."
            ),
        }
    )
    events["legal_enforcement"].update(
        {
            "include": (
                "Официально начатое расследование, поданный иск/заявление, принятое "
                "судом дело, исполнение решения или назначенный органом штраф. "
                "Признание нарушения не обязательно. Отдельное заявление кредитора "
                "после пропуска платежа можно отметить вместе с insolvency_default."
            ),
            "exclude": (
                "Сам пропуск платежа, слух или план расследования; стандартное "
                "открытие процедуры банкротства без отдельного искового/судебного "
                "действия; новое общее правило."
            ),
        }
    )
    events["corporate_transaction_restructuring"].update(
        {
            "include": (
                "Официально принятое или объявленное решение о сделке, продаже/"
                "выделении активов, формальном закрытии площадки или отдельной "
                "реструктуризации; будущая дата исполнения не отменяет статус решения. "
                "Сокращение штата ставь отдельно при самостоятельном сообщении об этом."
            ),
            "exclude": (
                "Сокращение персонала без отдельного закрытия/реорганизации; обычная "
                "смена руководителя; обсуждение сделки без решения."
            ),
        }
    )
    events["environment_disaster_impact"].update(
        {
            "include": (
                "Природное бедствие или экологический инцидент с прямо названным "
                "ущербом/ограничением ресурса, производства, поставок или объекта. "
                "Например, засуха и ограничение воды с подтверждённым сокращением выпуска."
            ),
            "exclude": (
                "Локальный пожар/авария внутри промышленного объекта без сообщённого "
                "загрязнения, экологического ущерба или внешнего воздействия; для "
                "остановки выпуска отдельно оцени production_operational_disruption."
            ),
        }
    )

    taxonomy["uncertainty_question"] = (
        "Достаточно ли в тексте ясных и подтверждённых сведений, чтобы установить, "
        "произошло ли описываемое деловое событие? Оцени только доказанность события, "
        "а не выбор основной темы. Не отвечай «да» лишь потому, что событие не входит "
        "в список: это отдельно проверяет unlisted_event."
    )
    taxonomy["uncertainty_criteria"] = {
        "true": (
            "Формулировка о событии неполна, спекулятивна, отрицается источником или "
            "содержит неразрешённое противоречие; фактическая опора для события неясна."
        ),
        "false": (
            "Описанное событие подтверждено достаточно ясно. Неопределённость основной "
            "темы и отсутствие подходящего event code сами по себе этот сигнал не включают."
        ),
    }
    taxonomy["annotation_rules"] = list(
        dict.fromkeys(
            [
                *taxonomy["annotation_rules"],
                "Выбирай одну основную тему по главному новому факту, а не по участнику или случайному слову; event labels оценивай независимо.",
                "Для каждого отдельного event code нужна собственная прямая evidence-опора; не выводи производство из отсутствия смены, право — из одного штрафного слова, экологию — из локального пожара.",
                "Пошлина/квота, судебное действие и изменение общего правила могут иметь несколько меток только если текст описывает отдельные основания/аспекты.",
                "Неопределённость доказательств события и событие вне списка — разные сигналы; сомнение в основной теме не должно переименовываться в недостаток доказательств события.",
            ]
        )
    )

    manifest = {
        "proposal_id": "t08-jev-taxonomy-proposal",
        "version": taxonomy["version"],
        "status": taxonomy["status"],
        "parent": {
            "version": "0.4.1-spike",
            "path": "spike/T08/experiments/taxonomy-v0.4.1-proposal/taxonomy.json",
            "sha256": PARENT_SHA256,
            "manifest_sha256": PARENT_MANIFEST_SHA256,
        },
        "baseline": {
            "version": "0.3.0-spike",
            "path": "spike/T08/taxonomy.json",
            "sha256": BASELINE_SHA256,
        },
        "proposal_path": "spike/T08/experiments/taxonomy-v0.4.2-proposal/taxonomy.json",
        "proposal_sha256": None,
        "source_error_audit": "spike/T08/ERROR_ANALYSIS_V2.1.json",
        "source_human_review_packet": "spike/T08/HUMAN_REVIEW_PACKET_V2.1.md",
        "saved_outputs_used_for_proposal": True,
        "new_jev_requests": 0,
        "approval": "awaiting_user_review",
        "evaluation_status": "not_live_tested; no quality improvement claim",
        "code_and_threshold_changes": False,
        "contract_or_production_changes": False,
        "topic_uncertainty_signal_changed": True,
        "requires_new_live_pilot_before_scoring": True,
        "gold_status": "preliminary_single_author; disputed cases require human adjudication",
    }
    return taxonomy, manifest


def write() -> dict[str, Any]:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    taxonomy, manifest = build()
    raw = (json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    TARGET.write_bytes(raw)
    manifest["proposal_sha256"] = _sha256(raw)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    result = write()
    print(f"TAXONOMY_PROPOSAL={result['version']}")
    print(f"SHA256={result['proposal_sha256']}")
