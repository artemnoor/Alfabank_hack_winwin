"""One-time, deterministic builder for the provisional T09-T13 corpus v1.

This script uses only the Python standard library. It refuses to overwrite any
frozen output. A revised corpus must use a new version and destination.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SHARED = Path(__file__).resolve().parents[1]
ROOT = SHARED.parents[1]
VERSION = "1.0.1"
ALLOW_REPLACE_OUTPUTS = False
DATASET_ID = "t09-t13-independent-v1"
AS_OF = "2026-10-14T00:00:00Z"
BASE_COMMIT = "ce640214be7c5ff2fdb451b9e290135a11b512a6"
PDF_PATH = Path(
    r"C:\CodexData\codex-remote-attachments\01a139c4-4c18-7961-871d-9a097becc117\0AE3329F-305C-4579-87D8-812744BE7943\1-AlfaBank_T08-T13_Jev_classification.pdf"
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def text_hash(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not ALLOW_REPLACE_OUTPUTS:
        raise FileExistsError(f"frozen output already exists: {path}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def versioned_ref(name: str, version: str = VERSION) -> dict[str, str]:
    return {"id": name, "version": version, "hash": digest({"id": name, "version": version})}


def entity(entity_id: str, kind: str, display_name: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "kind": versioned_ref("entity." + kind),
        "display_name": display_name,
    }


ENTITIES = {
    "company-a": entity("company-a", "company", "РадиоКомплект"),
    "company-a-near": entity("company-a-near", "company", "РадиоКомплект-Север"),
    "company-b": entity("company-b", "company", "Орбита Электроникс"),
    "company-b-parent": entity("company-b-parent", "company", "Орбита Холдинг"),
    "company-b-subsidiary": entity("company-b-subsidiary", "company", "Орбита Компоненты Восток"),
    "company-c": entity("company-c", "company", "ТехноСборка"),
    "supplier-b-x": entity("supplier-b-x", "organization", "МикроКаскад"),
    "supplier-b-y": entity("supplier-b-y", "organization", "Пассив-Вектор"),
    "supplier-c-old": entity("supplier-c-old", "organization", "СырьёМаршрут-Пром"),
    "supplier-c-current": entity("supplier-c-current", "organization", "Руда Альянс"),
    "supplier-rumor": entity("supplier-rumor", "organization", "Вектор Компоненты"),
    "component-mk7": entity("component-mk7", "component", "Микросхема МК-7"),
    "component-p12": entity("component-p12", "component", "Пассивный компонент П-12"),
    "material-nickel": entity("material-nickel", "material", "Никелевый гранулят Н-4"),
    "product-p17": entity("product-p17", "product", "Плата П-17"),
    "plant-b": entity("plant-b", "facility", "Сборочная площадка Луч"),
    "plant-c": entity("plant-c", "facility", "Производственная площадка Лесная"),
    "plant-north": entity("plant-north", "facility", "Завод Северный Модуль"),
    "plant-east": entity("plant-east", "facility", "Завод Северный Модуль Восток"),
    "warehouse-c": entity("warehouse-c", "warehouse", "Склад Лесной"),
    "port-vega": entity("port-vega", "port", "Порт Вега"),
    "route-c-vega": entity("route-c-vega", "route", "Маршрут Лесная-Вега"),
    "country-x": entity("country-x", "country", "Республика Каскад"),
    "country-y": entity("country-y", "country", "Республика Лира"),
    "country-z": entity("country-z", "country", "Союз Арка"),
    "country-q": entity("country-q", "country", "Республика Меридиан"),
}


def make_documents() -> list[dict[str, Any]]:
    rows = [
        ("doc-a-self", "company-a", "company_statement", "a-self", "2026-10-01T10:00:00Z", "РадиоКомплект торгует радиодеталями для промышленной электроники. Поставщики, страны закупок и доля импорта в заявлении не названы."),
        ("doc-a-source-denial", "company-a", "company_statement", "a-source-denial-20261014", "2026-10-14T08:00:00Z", "РадиоКомплект заявил, что не закупает микросхемы МК-7 из Республики Каскад. Заявление не раскрывает другие товары, периоды и косвенные цепочки."),
        ("doc-export-official", "regulator-x", "official_notice", "export-x-20261013", "2026-10-13T08:00:00Z", "Регулятор Республики Каскад с 13 октября ограничил экспорт микросхем МК-7 до отдельного уведомления."),
        ("doc-export-correction", "regulator-x", "official_correction", "export-x-correction-20261014", "2026-10-14T07:00:00Z", "Регулятор Республики Каскад уточнил: ограничение экспорта микросхем МК-7 действует до 30 ноября; исходное решение принято 13 октября."),
        ("doc-export-wire-en", "wire-north", "independent_news", "wire-x-20261013", "2026-10-13T09:20:00Z", "Country X's regulator restricted exports of MK-7 microchips from 13 October; no end date was announced."),
        ("doc-export-multi", "daily-ledger", "news_article", "daily-ledger-20261013", "2026-10-13T10:00:00Z", "Республика Каскад ограничила экспорт микросхем МК-7 с 13 октября. Компания «Орбита Электроникс» повысила отпускную цену платы П-17 на 4%."),
        ("doc-fire-north", "regional-north", "local_news", "fire-north-20261013", "2026-10-13T11:00:00Z", "Пожар остановил производственную линию завода «Северный Модуль» в городе Норд."),
        ("doc-fire-east", "regional-east", "local_news", "fire-east-20261013", "2026-10-13T11:10:00Z", "Пожар остановил производственную линию завода «Северный Модуль Восток» в городе Ист."),
        ("doc-port-official", "port-vega-authority", "official_notice", "port-vega-closure-20261013", "2026-10-13T06:00:00Z", "Администрация порта Вега приостановила приём грузов на 48 часов из-за шторма."),
        ("doc-port-independent", "logistics-review", "independent_news", "port-vega-independent-20261013", "2026-10-13T07:30:00Z", "Логистическое издание сообщает, что порт Вега временно не принимает грузы после шторма; ограничение объявила администрация порта."),
        ("doc-sanction", "treasury-x", "official_notice", "sanction-supplier-20261012", "2026-10-12T12:00:00Z", "Казначейство Республики Каскад ввело санкции против компании «МикроКаскад»."),
        ("doc-price-fact", "raw-material-co", "company_statement", "nickel-price-20261001", "2026-10-01T09:00:00Z", "Поставщик сообщил, что отпускная цена никелевого гранулята Н-4 выросла на 12% с 1 октября."),
        ("doc-price-forecast", "market-forecast", "forecast", "nickel-forecast-q4", "2026-10-13T13:00:00Z", "Аналитики прогнозируют возможный рост цены никелевого гранулята в следующем квартале; фактическое изменение пока не зафиксировано."),
        ("doc-default-rumor", "social-channel", "rumor", "supplier-default-rumor", "2026-10-13T14:00:00Z", "В отраслевом чате пишут, будто поставщик «Вектор Компоненты» объявил дефолт. Документального подтверждения нет."),
        ("doc-fire-rumor", "social-channel", "rumor", "north-plant-closure-rumor", "2026-10-13T14:30:00Z", "В соцсетях утверждают, что завод «Северный Модуль» закроется. Независимого подтверждения нет; остановка завода не установлена."),
        ("doc-tax", "revenue-service-y", "official_notice", "tax-change-y-20261010", "2026-10-10T08:00:00Z", "Налоговая служба Республики Лира опубликовала изменение импортной пошлины на отдельные группы компонентов с 1 ноября."),
        ("doc-cyber", "tech-bulletin", "news_article", "cyber-b-20261013", "2026-10-13T15:00:00Z", "В Орбита Электроникс расследуют киберинцидент в учётной системе. Источник не сообщает об остановке производства или утечке данных."),
        ("doc-line-stop", "company-b", "company_statement", "line-stop-b-20261014", "2026-10-14T05:00:00Z", "Орбита Электроникс сообщила о плановой остановке линии SMT-2 для обслуживания с 14 октября. Причина не связана с киберинцидентом."),
        ("doc-investment", "company-c", "company_statement", "investment-c-20261011", "2026-10-11T10:00:00Z", "ТехноСборка объявила о вложениях в новый участок обработки сырья. Размер вложений и срок выхода на проектную мощность не указаны."),
        ("doc-unrelated-country", "agency-q", "official_notice", "export-q-20261013", "2026-10-13T09:00:00Z", "Республика Меридиан ограничила экспорт микросхем другого типа МК-9. Республика Каскад и микросхема МК-7 в документе не упоминаются."),
        ("doc-stale-port", "port-vega-authority", "official_notice", "port-vega-old-20250201", "2025-02-01T07:00:00Z", "Администрация порта Вега закрыла причал на один день из-за ремонта. Сведения относятся к февралю 2025 года."),
        ("doc-industry-only", "industry-digest", "market_commentary", "electronics-outlook-20261013", "2026-10-13T16:00:00Z", "Сектор промышленной электроники может столкнуться с перебоями. Конкретные поставщики и компании не названы."),
        ("doc-parent-release", "orbita-holding", "company_statement", "parent-release-20261009", "2026-10-09T10:00:00Z", "Орбита Холдинг объявил программу модернизации дочерних предприятий. Релиз не перечисляет поставщиков компании Орбита Электроникс."),
        ("doc-b-official", "company-b", "company_statement", "b-supply-statement-20261005", "2026-10-05T10:00:00Z", "Орбита Электроникс закупает микросхемы МК-7 у поставщика МикроКаскад из Республики Каскад; сборочная площадка находится в городе Луч, а маршрут поставок проходит через порт Вега."),
        ("doc-b-independent", "electronics-journal", "independent_news", "b-supply-independent-20261006", "2026-10-06T08:00:00Z", "Отраслевой журнал подтверждает закупки Орбита Электроникс у МикроКаскад из Республики Каскад по микросхемам МК-7 и сборку на площадке в Луче с маршрутом через порт Вега."),
        ("doc-b-self-secondary", "company-b", "company_statement", "b-secondary-supplier-20261005", "2026-10-05T10:30:00Z", "Орбита Электроникс заявляет о закупке пассивных компонентов П-12 у Пассив-Вектор. Доли закупок не раскрыты."),
        ("doc-c-official", "company-c", "company_statement", "c-supply-statement-20261002", "2026-10-02T10:00:00Z", "ТехноСборка закупает никелевый гранулят Н-4 у Руда Альянс; сырьё хранится на складе Лесной и доставляется по маршруту Лесная-Вега через порт Вега."),
        ("doc-c-independent", "materials-journal", "independent_news", "c-supply-independent-20261003", "2026-10-03T09:00:00Z", "Отраслевое издание подтверждает поставки никелевого гранулята Н-4 компании ТехноСборка от Руда Альянс, склад Лесной и использование порта Вега."),
        ("doc-c-history", "company-c", "company_statement", "c-supplier-history-20250115", "2025-01-15T10:00:00Z", "До конца 2025 года ТехноСборка закупала никелевое сырьё у СырьёМаршрут-Пром."),
        ("doc-c-stock-a", "warehouse-log-a", "company_record", "c-stock-8d-20261013", "2026-10-13T17:00:00Z", "В складской ведомости ТехноСборки запас никелевого гранулята оценён в 8 дней производства на 13 октября."),
        ("doc-c-stock-b", "auditor-note-b", "independent_record", "c-stock-12d-20261013", "2026-10-13T18:00:00Z", "В независимой сверке запас никелевого гранулята ТехноСборки оценён в 12 дней производства на 13 октября."),
        ("doc-c-process", "company-c", "company_statement", "c-process-20261002", "2026-10-02T10:15:00Z", "ТехноСборка выполняет подготовку сырья и термообработку; данные о загрузке и пропускной способности не указаны."),
    ]
    docs = []
    for doc_id, publisher, source_type, group, published_at, text in rows:
        docs.append(
            {
                "document_id": doc_id,
                "version": 1,
                "origin": "synthetic",
                "source_type": source_type,
                "publisher_id": publisher,
                "publisher_root_id": publisher,
                "syndication_group_id": group,
                "published_at": published_at,
                "collected_at": published_at,
                "language": "en" if doc_id == "doc-export-wire-en" else "ru",
                "title": doc_id.replace("doc-", "").replace("-", " ").title(),
                "text": text,
                "content_hash": text_hash(text),
                "availability": "available",
            }
        )
    docs.append(
        {
            "document_id": "doc-archived-unavailable",
            "version": 1,
            "origin": "synthetic",
            "source_type": "unavailable_source",
            "publisher_id": "archive-withdrawn",
            "publisher_root_id": "archive-withdrawn",
            "syndication_group_id": "archive-withdrawn-item",
            "published_at": None,
            "collected_at": "2026-10-14T00:00:00Z",
            "language": "unknown",
            "title": "Unavailable synthetic source record",
            "text": None,
            "content_hash": text_hash("unavailable-source-placeholder-v1"),
            "availability": "missing",
        }
    )
    original = next(row for row in docs if row["document_id"] == "doc-export-official")
    quote = "ограничил экспорт микросхем МК-7"
    for index in range(1, 11):
        doc_id = f"doc-export-reprint-{index:02d}"
        text = f"Перепечатка {index}: регулятор Республики Каскад {quote} с 13 октября."
        docs.append(
            {
                "document_id": doc_id,
                "version": 1,
                "origin": "synthetic",
                "source_type": "syndicated_repost",
                "publisher_id": f"repost-outlet-{index:02d}",
                "publisher_root_id": "regulator-x",
                "syndication_group_id": "export-x-20261013",
                "published_at": f"2026-10-13T{10 + index:02d}:00:00Z",
                "collected_at": f"2026-10-13T{10 + index:02d}:05:00Z",
                "language": "ru",
                "title": f"Перепечатка сообщения об ограничении экспорта {index}",
                "text": text,
                "content_hash": text_hash(text),
                "availability": "available",
                "reprints_document_id": original["document_id"],
            }
        )
    return docs


DOCUMENTS = make_documents()
DOCS = {item["document_id"]: item for item in DOCUMENTS}


def object_ref(owner: str, object_id: str, revision: int, value_hash: str) -> dict[str, Any]:
    return {"owner": owner, "object_id": object_id, "revision": revision, "hash": value_hash}


def document_ref(document_id: str) -> dict[str, Any]:
    document = DOCS[document_id]
    return object_ref("Documents", document_id, document["version"], document["content_hash"])


def evidence_span(document_id: str, quote: str) -> dict[str, Any]:
    text = DOCS[document_id]["text"]
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        raise ValueError(f"quote must occur exactly once in {document_id}: {quote!r}")
    return {
        "kind": "text_span",
        "start": start,
        "end": start + len(quote),
        "quote_hash": text_hash(quote),
    }


def make_evidence(evidence_id: str, document_id: str, quote: str, verification: str = "verified_anchor", reliability: str = "unassessed") -> dict[str, Any]:
    locator = evidence_span(document_id, quote)
    source_ref = document_ref(document_id)
    body = {
        "source_ref": source_ref,
        "locator": locator,
        "source_hash": DOCS[document_id]["content_hash"],
        "verification": verification,
        "source_reliability": reliability,
        "reliability_method": None,
    }
    return {
        "ref": object_ref("Evidence", evidence_id, 1, digest(body)),
        **body,
        "test_claim": None,
    }


EVIDENCE: dict[str, dict[str, Any]] = {}


def add_evidence(evidence_id: str, document_id: str, quote: str, verification: str = "verified_anchor", reliability: str = "unassessed", test_claim: str | None = None) -> None:
    item = make_evidence(evidence_id, document_id, quote, verification, reliability)
    item["test_claim"] = test_claim
    EVIDENCE[evidence_id] = item


add_evidence("ev-a-activity", "doc-a-self", "РадиоКомплект торгует радиодеталями для промышленной электроники", test_claim="Компания заявила о направлении деятельности; это не доказывает страну или поставщика.")
add_evidence("ev-a-source-denial", "doc-a-source-denial", "не закупает микросхемы МК-7 из Республики Каскад", test_claim="Проверенный anchor подтверждает текст заявления, но не доказывает истинность отрицания или отсутствие косвенной зависимости.")
add_evidence("ev-export-official", "doc-export-official", "ограничил экспорт микросхем МК-7", test_claim="Anchor подтверждает текст официального синтетического уведомления, но не воздействие на конкретную компанию.")
add_evidence("ev-export-wire", "doc-export-wire-en", "restricted exports of MK-7 microchips", test_claim="Отдельная редакционная публикация; независимость задаётся publisher_root_id.")
add_evidence("ev-export-correction", "doc-export-correction", "уточнил: ограничение экспорта микросхем МК-7 действует до 30 ноября", test_claim="Later official statement corrects the validity end date of the same measure.")
add_evidence("ev-port-official", "doc-port-official", "приостановила приём грузов на 48 часов", test_claim="Anchor цитирует временное закрытие порта.")
add_evidence("ev-port-independent", "doc-port-independent", "порт Вега временно не принимает грузы", test_claim="Второй синтетический источник с отдельным publisher_root_id.")
add_evidence("ev-b-official", "doc-b-official", DOCS["doc-b-official"]["text"], test_claim="Тестовое заявление компании о поставщике, компоненте, площадке и маршруте.")
add_evidence("ev-b-independent", "doc-b-independent", DOCS["doc-b-independent"]["text"], test_claim="Независимая синтетическая публикация для локальной test-owner policy.")
add_evidence("ev-b-secondary", "doc-b-self-secondary", "заявляет о закупке пассивных компонентов П-12 у Пассив-Вектор", test_claim="Заявление компании: статус user_declared, не confirmed.")
add_evidence("ev-c-official", "doc-c-official", DOCS["doc-c-official"]["text"], test_claim="Тестовое заявление о текущем сырье, складе и маршруте.")
add_evidence("ev-c-independent", "doc-c-independent", DOCS["doc-c-independent"]["text"], test_claim="Независимое синтетическое подтверждение поставщика и инфраструктурных связей.")
add_evidence("ev-c-process", "doc-c-process", "ТехноСборка выполняет подготовку сырья и термообработку", test_claim="Заявленный процесс; производственная мощность неизвестна.")
add_evidence("ev-c-old-supplier", "doc-c-history", "закупала никелевое сырьё у СырьёМаршрут-Пром", test_claim="Исторический факт с ограниченным valid time.")
add_evidence("ev-c-stock-8d", "doc-c-stock-a", "запас никелевого гранулята оценён в 8 дней производства", test_claim="Одна версия запаса; противоречит другой записи.")
add_evidence("ev-c-stock-12d", "doc-c-stock-b", "запас никелевого гранулята ТехноСборки оценён в 12 дней производства", test_claim="Другая версия запаса; не усреднять и не выбирать автоматически.")
add_evidence("ev-rumor-default", "doc-default-rumor", "пишут, будто поставщик «Вектор Компоненты» объявил дефолт", test_claim="Verified anchor of rumor wording is not evidence that default occurred.")
add_evidence("ev-rumor-default-unverified", "doc-default-rumor", "пишут, будто поставщик «Вектор Компоненты» объявил дефолт", verification="unverified", test_claim="An unverified record is preserved separately; the text itself is not presented as checked.")
add_evidence("ev-fire-rumor", "doc-fire-rumor", "завод «Северный Модуль» закроется", test_claim="Rumored future closure is neither an observed fire nor a confirmed shutdown.")
add_evidence("ev-price-forecast", "doc-price-forecast", "прогнозируют возможный рост цены", test_claim="Forecast is not an observed price increase.")
add_evidence("ev-industry-only", "doc-industry-only", "Сектор промышленной электроники может столкнуться с перебоями", test_claim="Sector-level statement names no company or dependency.")
add_evidence("ev-fire-north", "doc-fire-north", DOCS["doc-fire-north"]["text"], test_claim="Reported fire at the North facility; near-name East facility is a separate event.")
add_evidence("ev-fire-east", "doc-fire-east", DOCS["doc-fire-east"]["text"], test_claim="Reported fire at the East facility; do not merge by title similarity.")
add_evidence("ev-sanction", "doc-sanction", DOCS["doc-sanction"]["text"], test_claim="Sanction notice names supplier; ownership and exposure are separate questions.")
add_evidence("ev-price-fact", "doc-price-fact", "цена никелевого гранулята Н-4 выросла на 12%", test_claim="Reported actual price change for a named material.")
add_evidence("ev-tax", "doc-tax", "изменение импортной пошлины на отдельные группы компонентов", test_claim="Tax change applies to a subset; company/product scope is not implied.")
add_evidence("ev-cyber", "doc-cyber", "расследуют киберинцидент в учётной системе", test_claim="Article explicitly does not report production stoppage or data theft.")
add_evidence("ev-line-stop", "doc-line-stop", "плановой остановке линии SMT-2 для обслуживания", test_claim="A maintenance stop is distinct from a cyber incident.")
add_evidence("ev-investment", "doc-investment", "объявила о вложениях в новый участок обработки сырья", test_claim="Investment announcement provides no amount or capacity date.")
add_evidence("ev-unrelated-country", "doc-unrelated-country", "Республика Меридиан ограничила экспорт микросхем другого типа МК-9", test_claim="Different country and product from export-x.")
add_evidence("ev-stale-port", "doc-stale-port", "закрыла причал на один день из-за ремонта", test_claim="Historical 2025 port event must not be treated as current.")
add_evidence("ev-parent-release", "doc-parent-release", "объявил программу модернизации дочерних предприятий", test_claim="Parent statement does not establish subsidiary suppliers or exposure.")
add_evidence("ev-multi-export", "doc-export-multi", "ограничила экспорт микросхем МК-7", test_claim="First event in a two-event article.")
add_evidence("ev-multi-price", "doc-export-multi", "повысила отпускную цену платы П-17 на 4%", test_claim="Second event in the same article; do not merge with the export restriction.")
for i in range(1, 11):
    doc_id = f"doc-export-reprint-{i:02d}"
    add_evidence(
        f"ev-export-reprint-{i:02d}",
        doc_id,
        "ограничил экспорт микросхем МК-7",
        test_claim="Ten publisher labels share one source root and one syndication group; do not count as ten corroborations.",
    )

_unavailable_body = {
    "source_ref": document_ref("doc-archived-unavailable"),
    "locator": {"kind": "whole_artifact"},
    "source_hash": DOCS["doc-archived-unavailable"]["content_hash"],
    "verification": "unverified",
    "source_reliability": "unassessed",
    "reliability_method": None,
}
EVIDENCE["ev-archived-unavailable"] = {
    "ref": object_ref("Evidence", "ev-archived-unavailable", 1, digest(_unavailable_body)),
    **_unavailable_body,
    "test_claim": "The immutable source identity is known but the content is unavailable; no quote or fact can be checked.",
}


def evidence_ref(evidence_id: str) -> dict[str, Any]:
    return EVIDENCE[evidence_id]["ref"]


def source_refs(document_ids: list[str]) -> list[dict[str, Any]]:
    return [document_ref(item) for item in document_ids]


def code_ref(code: str, namespace: str = "alfalab.business", version: str = VERSION) -> dict[str, str]:
    return {"namespace": namespace, "version": version, "code": code}


def value_text(value: str) -> dict[str, Any]:
    return {"kind": "text", "value": value}


def value_entity(value: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "entity", "value": value}


def value_unknown(reason: str) -> dict[str, Any]:
    return {"kind": "unknown", "reason": reason}


def value_number(value: str, unit: str) -> dict[str, Any]:
    return {"kind": "number", "value": value, "unit": code_ref(unit, "units")}


def provenance(
    origin: str = "synthetic",
    docs: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    input_refs: list[dict[str, Any]] | None = None,
    method: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "origin": origin,
        "source_refs": source_refs(docs or []),
        "input_statement_refs": input_refs or [],
        "producer_run_id": None,
        "derivation_method": method,
        "evidence_refs": [evidence_ref(item) for item in (evidence_ids or [])],
        "origin_verified": False,
    }


def statement(
    statement_id: str,
    subject: dict[str, Any],
    predicate: str,
    value: dict[str, Any],
    status: str,
    evidence_ids: list[str],
    doc_ids: list[str],
    valid_from: str | None,
    valid_to: str | None,
    recorded_at: str,
    revision: int = 1,
    origin: str | None = None,
    input_refs: list[dict[str, Any]] | None = None,
    method: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "statement_id": statement_id,
        "revision": revision,
        "subject": subject,
        "predicate": code_ref(predicate),
        "value": value,
        "epistemic_status": status,
        "validity": {
            "valid_from": valid_from,
            "valid_to": valid_to,
            "recorded_at": recorded_at,
        },
        "provenance": provenance(
            origin or ("user_declared" if status == "user_declared" else "synthetic"),
            doc_ids,
            evidence_ids,
            input_refs=input_refs,
            method=method,
        ),
    }


def missing_datum(path: str, detail: str, reason: str = "not_provided") -> dict[str, Any]:
    return {
        "path": path,
        "reason": reason,
        "detail": detail,
    }


def question_answer(question_id: str, status: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "status": status,
        "value": None,
        "provenance": provenance("unknown"),
    }


def business_snapshot(
    company_id: str,
    revision: int,
    statements: list[dict[str, Any]],
    missing: list[dict[str, Any]],
    contradictions: list[dict[str, Any]] | None = None,
    answers: list[dict[str, Any]] | None = None,
    recorded_at: str = "2026-10-14T00:00:00Z",
    max_questions: int = 3,
) -> dict[str, Any]:
    partition = {
        "company": ENTITIES[company_id],
        "statements": statements,
        "contradictions": contradictions or [],
        "missing_data": missing,
        "answers": answers or [],
        "preferences": {
            "max_questions": max_questions,
            "allow_event_prompts": True,
            "suppressed_targets": [],
        },
        "slice": {
            "owner": "Business",
            "partition_id": company_id,
            "revision": revision,
            "selection_key": "current-profile",
        },
        "as_of": {"valid_as_of": recorded_at, "known_as_of": recorded_at},
    }
    return {
        "ref": object_ref("Business", company_id, revision, digest(partition)),
        **partition,
    }


def profile_data() -> list[dict[str, Any]]:
    activity_v1 = statement(
        "a-activity-v1", ENTITIES["company-a"], "trades_in", value_text("Радиодетали для промышленной электроники"),
        "user_declared", ["ev-a-activity"], ["doc-a-self"], "2026-08-01T00:00:00Z", None,
        "2026-08-01T10:00:00Z", revision=1,
    )
    sparse_v1 = business_snapshot(
        "company-a", 1, [activity_v1],
        [missing_datum("/dependencies/suppliers", "Поставщики не названы.")],
        answers=[question_answer("supplier-countries", "skipped")],
        recorded_at="2026-08-01T00:00:00Z",
    )
    activity_v2 = statement(
        "a-activity-v2", ENTITIES["company-a"], "trades_in", value_text("Оптовая торговля радиодеталями"),
        "user_declared", ["ev-a-activity"], ["doc-a-self"], "2026-10-01T00:00:00Z", None,
        "2026-10-01T10:00:00Z", revision=2,
    )
    supplier_unknown = statement(
        "a-supplier-unknown", ENTITIES["company-a"], "purchases_from", value_unknown("Поставщики не предоставлены"),
        "unknown", [], [], None, None, "2026-10-01T10:00:00Z",
    )
    sparse_v2 = business_snapshot(
        "company-a", 2, [activity_v2, supplier_unknown],
        [
            missing_datum("/dependencies/suppliers", "Неизвестны конкретные поставщики."),
            missing_datum("/sourcing/countries", "Неизвестны страны закупок."),
            missing_datum("/procurement/volume", "Неизвестны объёмы закупок."),
            missing_datum("/procurement/import_share", "Неизвестна доля импорта."),
        ],
        answers=[question_answer("supplier-countries", "skipped")],
        recorded_at="2026-10-01T00:00:00Z",
    )

    b_evidence = ["ev-b-official", "ev-b-independent"]
    b_docs = ["doc-b-official", "doc-b-independent"]
    b_statements = [
        statement("b-buys-microkaskad", ENTITIES["company-b"], "purchases_from", value_entity(ENTITIES["supplier-b-x"]), "confirmed", b_evidence, b_docs, "2026-01-01T00:00:00Z", None, "2026-10-06T09:00:00Z"),
        statement("b-supplier-supplies-mk7", ENTITIES["supplier-b-x"], "supplies", value_entity(ENTITIES["component-mk7"]), "confirmed", b_evidence, b_docs, "2026-01-01T00:00:00Z", None, "2026-10-06T09:00:00Z"),
        statement("b-uses-mk7", ENTITIES["company-b"], "uses_component", value_entity(ENTITIES["component-mk7"]), "confirmed", b_evidence, b_docs, "2026-01-01T00:00:00Z", None, "2026-10-06T09:00:00Z"),
        statement("b-supplier-country", ENTITIES["supplier-b-x"], "located_in", value_entity(ENTITIES["country-x"]), "confirmed", b_evidence, b_docs, "2026-01-01T00:00:00Z", None, "2026-10-06T09:00:00Z"),
        statement("b-site", ENTITIES["company-b"], "operates_at", value_entity(ENTITIES["plant-b"]), "confirmed", b_evidence, b_docs, "2025-06-01T00:00:00Z", None, "2026-10-06T09:00:00Z"),
        statement("b-route-vega", ENTITIES["company-b"], "ships_via", value_entity(ENTITIES["port-vega"]), "confirmed", b_evidence, b_docs, "2025-06-01T00:00:00Z", None, "2026-10-06T09:00:00Z"),
        statement("b-secondary-supplier", ENTITIES["company-b"], "purchases_from", value_entity(ENTITIES["supplier-b-y"]), "user_declared", ["ev-b-secondary"], ["doc-b-self-secondary"], "2026-02-01T00:00:00Z", None, "2026-10-05T10:30:00Z"),
        statement("b-secondary-component", ENTITIES["company-b"], "uses_component", value_entity(ENTITIES["component-p12"]), "user_declared", ["ev-b-secondary"], ["doc-b-self-secondary"], "2026-02-01T00:00:00Z", None, "2026-10-05T10:30:00Z"),
    ]
    b_snapshot = business_snapshot(
        "company-b", 2, b_statements,
        [missing_datum("/procurement/volume", "Поставщик и компоненты известны, но объём не указан.")],
        answers=[question_answer("procurement-share", "declined")],
        recorded_at="2026-10-14T00:00:00Z",
    )

    c_evidence = ["ev-c-official", "ev-c-independent"]
    c_docs = ["doc-c-official", "doc-c-independent"]
    c_statements = [
        statement("c-old-supplier", ENTITIES["company-c"], "purchases_from", value_entity(ENTITIES["supplier-c-old"]), "user_declared", ["ev-c-old-supplier"], ["doc-c-history"], "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z", "2025-01-15T10:00:00Z"),
        statement("c-current-supplier", ENTITIES["company-c"], "purchases_from", value_entity(ENTITIES["supplier-c-current"]), "confirmed", c_evidence, c_docs, "2026-01-01T00:00:00Z", None, "2026-10-03T09:00:00Z"),
        statement("c-supplier-supplies-nickel", ENTITIES["supplier-c-current"], "supplies", value_entity(ENTITIES["material-nickel"]), "confirmed", c_evidence, c_docs, "2026-01-01T00:00:00Z", None, "2026-10-03T09:00:00Z"),
        statement("c-supplier-route", ENTITIES["supplier-c-current"], "ships_via", value_entity(ENTITIES["route-c-vega"]), "confirmed", c_evidence, c_docs, "2026-01-01T00:00:00Z", None, "2026-10-03T09:00:00Z"),
        statement("c-uses-nickel", ENTITIES["company-c"], "uses_material", value_entity(ENTITIES["material-nickel"]), "confirmed", c_evidence, c_docs, "2026-01-01T00:00:00Z", None, "2026-10-03T09:00:00Z"),
        statement("c-warehouse", ENTITIES["company-c"], "stores_at", value_entity(ENTITIES["warehouse-c"]), "confirmed", c_evidence, c_docs, "2026-01-01T00:00:00Z", None, "2026-10-03T09:00:00Z"),
        statement("c-route-vega", ENTITIES["company-c"], "ships_via", value_entity(ENTITIES["route-c-vega"]), "confirmed", c_evidence, c_docs, "2026-01-01T00:00:00Z", None, "2026-10-03T09:00:00Z"),
        statement("c-route-port", ENTITIES["route-c-vega"], "passes_through", value_entity(ENTITIES["port-vega"]), "confirmed", c_evidence, c_docs, "2026-01-01T00:00:00Z", None, "2026-10-03T09:00:00Z"),
        statement("c-process", ENTITIES["company-c"], "processes", value_text("Подготовка сырья и термообработка"), "user_declared", ["ev-c-process"], ["doc-c-process"], "2026-01-01T00:00:00Z", None, "2026-10-02T10:15:00Z"),
        statement("c-stock-8-days", ENTITIES["company-c"], "inventory_cover", value_number("8", "production_day"), "disputed", ["ev-c-stock-8d"], ["doc-c-stock-a"], "2026-10-13T00:00:00Z", None, "2026-10-13T17:00:00Z"),
        statement("c-stock-12-days", ENTITIES["company-c"], "inventory_cover", value_number("12", "production_day"), "disputed", ["ev-c-stock-12d"], ["doc-c-stock-b"], "2026-10-13T00:00:00Z", None, "2026-10-13T18:00:00Z"),
        statement("c-volume-unknown", ENTITIES["company-c"], "production_volume", value_unknown("Объём не раскрыт"), "unknown", [], [], None, None, "2026-10-03T09:00:00Z"),
    ]
    c_snapshot = business_snapshot(
        "company-c", 3, c_statements,
        [
            missing_datum("/production/volume", "Объём производства не раскрыт."),
            missing_datum("/procurement/value", "Стоимость закупок не раскрыта."),
        ],
        contradictions=[{"statement_ids": ["c-stock-8-days", "c-stock-12-days"], "reason": "Источники дают несовпадающий запас сырья на одну дату; исходные значения сохранены."}],
        answers=[question_answer("inventory-value", "skipped")],
        recorded_at="2026-10-14T00:00:00Z",
        max_questions=2,
    )
    return [
        {"company_id": "company-a", "display_name": ENTITIES["company-a"]["display_name"], "snapshots": [sparse_v1, sparse_v2]},
        {"company_id": "company-b", "display_name": ENTITIES["company-b"]["display_name"], "parent_id": "company-b-parent", "subsidiary_id": "company-b-subsidiary", "snapshots": [b_snapshot]},
        {"company_id": "company-c", "display_name": ENTITIES["company-c"]["display_name"], "snapshots": [c_snapshot]},
    ]


COMPANY_PROFILES = profile_data()
PROFILE_BY_ID = {item["company_id"]: item for item in COMPANY_PROFILES}
PROFILE_SNAPSHOT_BY_ID = {item["company_id"]: item["snapshots"][-1] for item in COMPANY_PROFILES}
STATEMENTS = {
    item["statement_id"]: item
    for profile in COMPANY_PROFILES
    for snapshot in profile["snapshots"]
    for item in snapshot["statements"]
}


def statement_ref_for_snapshot(snapshot: dict[str, Any], statement_id: str) -> dict[str, Any]:
    selected = next(item for item in snapshot["statements"] if item["statement_id"] == statement_id)
    return {
        "aggregate_ref": snapshot["ref"],
        "statement_id": statement_id,
        "revision": selected["revision"],
        "hash": digest(selected),
    }


def graph_test_inputs() -> list[dict[str, Any]]:
    base_a = PROFILE_SNAPSHOT_BY_ID["company-a"]
    hypothesis = statement(
        "a-hypothetical-source-country-x",
        ENTITIES["company-a"],
        "sources_from_country",
        value_entity(ENTITIES["country-x"]),
        "hypothetical",
        [],
        [],
        "2026-10-14T00:00:00Z",
        None,
        "2026-10-14T08:30:00Z",
        origin="synthetic",
    )
    negative = statement(
        "a-explicit-not-source-country-x",
        ENTITIES["company-a"],
        "does_not_source_from_country",
        value_entity(ENTITIES["country-x"]),
        "user_declared",
        ["ev-a-source-denial"],
        ["doc-a-source-denial"],
        "2026-10-14T00:00:00Z",
        None,
        "2026-10-14T08:00:00Z",
        origin="user_declared",
    )
    a_overlay = business_snapshot(
        "company-a",
        3,
        [*base_a["statements"], hypothesis, negative],
        base_a["missing_data"],
        contradictions=[{
            "statement_ids": [hypothesis["statement_id"], negative["statement_id"]],
            "reason": "A hypothetical candidate conflicts with a scoped company declaration; neither resolves every product, period, or indirect path.",
        }],
        answers=base_a["answers"],
        recorded_at="2026-10-14T08:30:00Z",
    )

    def record(input_id: str, snapshot: dict[str, Any], candidate: dict[str, Any], description: str, expected: list[str], limitations: list[str], source_refs: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"aggregate_snapshot": snapshot, "candidate_statement": candidate}
        return {
            "input_id": input_id,
            "version": VERSION,
            "origin": "synthetic",
            "provenance": {
                "creator": "hand-authored deterministic graph-input builder",
                "origin": "synthetic",
                "source_refs": source_refs,
                "model_outputs_used_as_labels": False,
            },
            "description": description,
            "inputs": source_refs,
            "payload": payload,
            "expected_properties": expected,
            "limitations": limitations,
            "data_hash": digest(payload),
            "manual_approval": "provisional",
        }

    a_ref_hyp = statement_ref_for_snapshot(a_overlay, hypothesis["statement_id"])
    a_ref_negative = statement_ref_for_snapshot(a_overlay, negative["statement_id"])
    input_hyp = record(
        "hypothetical-only",
        a_overlay,
        hypothesis,
        "A scoped hypothetical sourcing-country candidate for sparse company A; it is test input, not an established dependency.",
        ["Keep epistemic_status=hypothetical.", "Do not publish a positive fact edge from the hypothetical candidate."],
        ["The hypothetical does not establish supplier identity, volume, import share, or any unlisted period/product."],
        [{"kind": "BusinessSnapshot", "ref": a_overlay["ref"]}, {"kind": "StatementRef", "ref": a_ref_hyp}],
    )
    input_negative = record(
        "explicit-negative-country-x",
        a_overlay,
        negative,
        "A company-declared, product-scoped negative sourcing statement with an exact synthetic quote anchor.",
        ["Retain the explicit negative predicate and its source/evidence refs.", "Do not turn the negative declaration into a positive dependency edge or universal proof of no risk."],
        ["verified_anchor establishes that the quoted declaration exists, not that its claim is true; scope is MK-7 and the stated period only."],
        [{"kind": "BusinessSnapshot", "ref": a_overlay["ref"]}, {"kind": "StatementRef", "ref": a_ref_negative}, {"kind": "EvidenceRef", "ref": evidence_ref("ev-a-source-denial")}],
    )

    base_b = PROFILE_SNAPSHOT_BY_ID["company-b"]
    inference_refs = [
        statement_ref_for_snapshot(base_b, "b-buys-microkaskad"),
        statement_ref_for_snapshot(base_b, "b-supplier-country"),
    ]
    inferred = statement(
        "b-inferred-country-x-dependency",
        ENTITIES["company-b"],
        "depends_on_country",
        value_entity(ENTITIES["country-x"]),
        "inferred",
        [],
        [],
        "2026-01-01T00:00:00Z",
        None,
        "2026-10-14T08:30:00Z",
        origin="derived",
        input_refs=inference_refs,
        method=versioned_ref("spike.graph.rule.company-supplier-location", "0.1.0"),
    )
    input_inferred = record(
        "inferred-company-country-x",
        base_b,
        inferred,
        "A proposed inferred relation derived from the explicit company-to-supplier and supplier-to-country statements in the supplied Business snapshot.",
        ["Keep epistemic_status=inferred.", "Preserve the named method and both resolvable input_statement_refs.", "Do not present the inferred country dependency as an independently confirmed fact."],
        ["This rule tests a candidate implication only; it does not establish supplier exclusivity, shipment share, transaction scope, or impact magnitude."],
        [{"kind": "BusinessSnapshot", "ref": base_b["ref"]}, *[{"kind": "StatementRef", "ref": ref} for ref in inference_refs]],
    )
    return [input_hyp, input_inferred, input_negative]


def statement_ref(company_id: str, statement_id: str) -> dict[str, Any]:
    snapshot = PROFILE_SNAPSHOT_BY_ID[company_id]
    selected = next(item for item in snapshot["statements"] if item["statement_id"] == statement_id)
    return {
        "aggregate_ref": snapshot["ref"],
        "statement_id": statement_id,
        "revision": selected["revision"],
        "hash": digest(selected),
    }


def event_statement(
    statement_id: str,
    subject: dict[str, Any],
    predicate: str,
    value: dict[str, Any],
    status: str,
    evidence_ids: list[str],
    docs: list[str],
    recorded_at: str,
) -> dict[str, Any]:
    item = statement(
        statement_id,
        subject,
        predicate,
        value,
        status,
        evidence_ids,
        docs,
        None,
        None,
        recorded_at,
    )
    item["predicate"] = code_ref(predicate, "alfalab.events")
    return item


def event_record(
    event_id: str,
    event_type: str,
    statements: list[dict[str, Any]],
    mention_ids: list[str],
    missing: list[dict[str, Any]] | None = None,
    lifecycle: str = "active",
) -> dict[str, Any]:
    body = {
        "event_type": code_ref(event_type, "alfalab.event-taxonomy"),
        "lifecycle": lifecycle,
        "statements": statements,
        "mention_ids": mention_ids,
        "lineage_refs": [],
        "missing_data": missing or [],
    }
    return {"ref": object_ref("Events", event_id, 1, digest(body)), **body}


EVENT_EXPORT = event_record(
    "event-export-x-mk7",
    "export_restriction",
    [
        event_statement(
            "event-export-claim",
            ENTITIES["country-x"],
            "restricts_export",
            value_entity(ENTITIES["component-mk7"]),
            "confirmed",
            ["ev-export-official", "ev-export-wire"],
            ["doc-export-official", "doc-export-wire-en"],
            "2026-10-13T09:20:00Z",
        ),
        event_statement(
            "event-export-expiry-v1",
            ENTITIES["country-x"],
            "restriction_end_date",
            value_unknown("Первоначально конечная дата не была указана"),
            "unknown",
            [],
            ["doc-export-official"],
            "2026-10-13T08:00:00Z",
        ),
        event_statement(
            "event-export-expiry-v2",
            ENTITIES["country-x"],
            "restriction_end_date",
            {"kind": "time", "value": "2026-11-30T23:59:59Z"},
            "observed",
            ["ev-export-correction"],
            ["doc-export-correction"],
            "2026-10-14T07:00:00Z",
        ),
    ],
    ["mention-export-official-ru", "mention-export-wire-en", "mention-export-multi-story"],
    [missing_datum("/event/valid_to", "В официальном сообщении конечная дата не указана.")],
)
EVENT_FIRE_NORTH = event_record(
    "event-fire-north-plant",
    "facility_fire",
    [event_statement("event-fire-north-claim", ENTITIES["plant-north"], "fire_at", value_entity(ENTITIES["plant-north"]), "observed", ["ev-fire-north"], ["doc-fire-north"], "2026-10-13T11:00:00Z")],
    ["mention-fire-north"],
)
EVENT_FIRE_EAST = event_record(
    "event-fire-east-plant",
    "facility_fire",
    [event_statement("event-fire-east-claim", ENTITIES["plant-east"], "fire_at", value_entity(ENTITIES["plant-east"]), "observed", ["ev-fire-east"], ["doc-fire-east"], "2026-10-13T11:10:00Z")],
    ["mention-fire-east"],
)


def business_slice(company_id: str) -> dict[str, Any]:
    snapshot = PROFILE_SNAPSHOT_BY_ID[company_id]
    return {
        "owner": "Business",
        "partition_id": company_id,
        "revision": snapshot["ref"]["revision"],
        "selection_key": snapshot["slice"]["selection_key"],
    }


def graph_node(node_id: str, entity_id: str, company_id: str, statement_ids: list[str], evidence_ids: list[str], docs: list[str]) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "entity": ENTITIES[entity_id],
        "statement_refs": [statement_ref(company_id, sid) for sid in statement_ids],
        "provenance": provenance("synthetic", docs, evidence_ids),
    }


def graph_edge(edge_id: str, source: str, target: str, relation: str, statement_ids: list[str], evidence_ids: list[str], docs: list[str], status: str = "confirmed", company_id: str = "company-b") -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "relation": code_ref(relation, "alfalab.supply-chain-ontology"),
        "epistemic_status": status,
        "statement_refs": [statement_ref(company_id, sid) for sid in statement_ids],
        "evidence_refs": [evidence_ref(eid) for eid in evidence_ids],
        "provenance": provenance("synthetic", docs, evidence_ids),
    }


def graph_snapshot_shared() -> dict[str, Any]:
    refs = ["ev-b-official", "ev-b-independent"]
    docs = ["doc-b-official", "doc-b-independent"]
    c_refs = ["ev-c-official", "ev-c-independent"]
    c_docs = ["doc-c-official", "doc-c-independent"]
    nodes = [
        graph_node("node-company-a", "company-a", "company-a", ["a-activity-v2", "a-supplier-unknown"], ["ev-a-activity"], ["doc-a-self"]),
        graph_node("node-company-b", "company-b", "company-b", ["b-buys-microkaskad", "b-uses-mk7", "b-site", "b-route-vega"], refs, docs),
        graph_node("node-supplier-b-x", "supplier-b-x", "company-b", ["b-buys-microkaskad", "b-supplier-supplies-mk7", "b-supplier-country"], refs, docs),
        graph_node("node-component-mk7", "component-mk7", "company-b", ["b-supplier-supplies-mk7", "b-uses-mk7"], refs, docs),
        graph_node("node-plant-b", "plant-b", "company-b", ["b-site"], refs, docs),
        graph_node("node-country-x", "country-x", "company-b", ["b-supplier-country"], refs, docs),
        {
            "node_id": "node-port-vega",
            "entity": ENTITIES["port-vega"],
            "statement_refs": [statement_ref("company-b", "b-route-vega"), statement_ref("company-c", "c-route-port")],
            "provenance": provenance("synthetic", docs + c_docs, refs + c_refs),
        },
        graph_node("node-supplier-b-y", "supplier-b-y", "company-b", ["b-secondary-supplier"], ["ev-b-secondary"], ["doc-b-self-secondary"]),
        graph_node("node-component-p12", "component-p12", "company-b", ["b-secondary-component"], ["ev-b-secondary"], ["doc-b-self-secondary"]),
        graph_node("node-company-c", "company-c", "company-c", ["c-current-supplier", "c-uses-nickel", "c-warehouse", "c-route-vega"], c_refs, c_docs),
        graph_node("node-supplier-c-current", "supplier-c-current", "company-c", ["c-current-supplier", "c-supplier-supplies-nickel", "c-supplier-route"], c_refs, c_docs),
        graph_node("node-material-nickel", "material-nickel", "company-c", ["c-supplier-supplies-nickel", "c-uses-nickel"], c_refs, c_docs),
        graph_node("node-warehouse-c", "warehouse-c", "company-c", ["c-warehouse"], c_refs, c_docs),
        graph_node("node-route-c-vega", "route-c-vega", "company-c", ["c-route-vega", "c-supplier-route", "c-route-port"], c_refs, c_docs),
    ]
    edges = [
        graph_edge("edge-b-purchases-microkaskad", "node-company-b", "node-supplier-b-x", "purchases_from", ["b-buys-microkaskad"], refs, docs),
        graph_edge("edge-microkaskad-supplies-mk7", "node-supplier-b-x", "node-component-mk7", "supplies", ["b-supplier-supplies-mk7"], refs, docs),
        graph_edge("edge-b-uses-mk7", "node-company-b", "node-component-mk7", "uses_component", ["b-uses-mk7"], refs, docs),
        graph_edge("edge-b-operates-plant", "node-company-b", "node-plant-b", "operates_at", ["b-site"], refs, docs),
        graph_edge("edge-supplier-x-country", "node-supplier-b-x", "node-country-x", "located_in", ["b-supplier-country"], refs, docs),
        graph_edge("edge-b-route-port-vega", "node-company-b", "node-port-vega", "ships_via", ["b-route-vega"], refs, docs),
        graph_edge("edge-b-secondary-purchases", "node-company-b", "node-supplier-b-y", "purchases_from", ["b-secondary-supplier"], ["ev-b-secondary"], ["doc-b-self-secondary"], "user_declared"),
        graph_edge("edge-b-secondary-uses", "node-company-b", "node-component-p12", "uses_component", ["b-secondary-component"], ["ev-b-secondary"], ["doc-b-self-secondary"], "user_declared"),
        graph_edge("edge-c-purchases-ore-alliance", "node-company-c", "node-supplier-c-current", "purchases_from", ["c-current-supplier"], c_refs, c_docs, company_id="company-c"),
        graph_edge("edge-ore-alliance-supplies-nickel", "node-supplier-c-current", "node-material-nickel", "supplies", ["c-supplier-supplies-nickel"], c_refs, c_docs, company_id="company-c"),
        graph_edge("edge-c-uses-nickel", "node-company-c", "node-material-nickel", "uses_material", ["c-uses-nickel"], c_refs, c_docs, company_id="company-c"),
        graph_edge("edge-c-stores-warehouse", "node-company-c", "node-warehouse-c", "stores_at", ["c-warehouse"], c_refs, c_docs, company_id="company-c"),
        graph_edge("edge-c-ships-route", "node-company-c", "node-route-c-vega", "ships_via", ["c-route-vega"], c_refs, c_docs, company_id="company-c"),
        graph_edge("edge-c-supplier-route", "node-supplier-c-current", "node-route-c-vega", "ships_via", ["c-supplier-route"], c_refs, c_docs, company_id="company-c"),
        graph_edge("edge-c-route-port", "node-route-c-vega", "node-port-vega", "passes_through", ["c-route-port"], c_refs, c_docs, company_id="company-c"),
    ]
    manifest = {
        "ontology": versioned_ref("alfalab.supply-chain-ontology"),
        "rules": versioned_ref("spike.graph-projection-rules", "0.1.0"),
        "input_slices": [business_slice("company-a"), business_slice("company-b"), business_slice("company-c")],
        "as_of": {"valid_as_of": AS_OF, "known_as_of": AS_OF},
        "builder": versioned_ref("spike.offline-graph-builder", "0.1.0"),
        "config_hash": digest({"projection": "company-b-current-partial-v1"}),
    }
    return {
        "graph_id": "graph-shared-companies-current",
        "revision": 1,
        "nodes": nodes,
        "edges": edges,
        "manifest": manifest,
        "completeness": "partial",
        "missing_data": [
            missing_datum("/company-a/dependencies/suppliers", "У РадиоКомплект поставщики неизвестны; отсутствие ребра не доказывает отсутствия зависимости."),
            missing_datum("/dependencies/tier_2", "Многоуровневые поставщики не перечислены."),
            missing_datum("/procurement/volume", "Объёмы закупок не раскрыты."),
            missing_datum("/company-c/inventory_cover", "Сохраняется противоречие между источниками: 8 и 12 производственных дней.", "contradictory"),
        ],
    }


GRAPH_SHARED = graph_snapshot_shared()


RESOLUTION_CASE_ROWS = [
    ("same-export-ru-en", ["doc-export-official", "doc-export-wire-en"], "attach", "Разные языки, действие, товар, страна и дата указывают на один синтетический запрет."),
    ("same-export-ten-reprints", ["doc-export-official", *[f"doc-export-reprint-{i:02d}" for i in range(1, 11)]], "attach", "Десять перепечаток принадлежат одному syndication_group и не становятся десятью независимыми событиями."),
    ("same-port-closure-two-sources", ["doc-port-official", "doc-port-independent"], "attach", "Совпадают порт, временное закрытие и причина; формулировки отличаются."),
    ("same-export-with-correction", ["doc-export-official", "doc-export-correction"], "correct", "Позднее официальное сообщение уточняет конечную дату того же ограничения; прежнее утверждение сохраняется в истории."),
    ("fire-same-title-north-east", ["doc-fire-north", "doc-fire-east"], "create", "Разные заводы и города дают два события при почти одинаковом заголовке."),
    ("split-two-events-one-article", ["doc-export-multi"], "split", "Одна статья содержит экспортное ограничение и отдельное повышение цены."),
    ("merge-duplicate-export-records", ["doc-export-official", "doc-export-reprint-01", "doc-export-reprint-02"], "merge", "Два ранее созданных дубля относятся к одному решению и должны сохранить lineage."),
    ("company-near-name", ["doc-industry-only"], "defer", "Секторное описание не разрешает выбрать РадиоКомплект или РадиоКомплект-Север."),
    ("parent-vs-subsidiary", ["doc-parent-release"], "defer", "Орбита Холдинг, Орбита Электроникс и Орбита Компоненты Восток имеют разные IDs; родство не равно идентичности."),
    ("supplier-sanction-vs-export-ban", ["doc-sanction", "doc-export-official"], "create", "Санкция против организации и ограничение экспорта товара имеют разные механизмы."),
    ("same-product-different-country", ["doc-export-official", "doc-unrelated-country"], "create", "МК-7 и МК-9, а также страны Каскад и Меридиан различаются."),
    ("actual-price-vs-forecast", ["doc-price-fact", "doc-price-forecast"], "create", "Зафиксированное изменение и прогноз возможного роста не являются одним событием."),
    ("rumored-default-not-confirmed", ["doc-default-rumor"], "defer", "Слух о дефолте не превращается в установленное событие."),
    ("rumored-plant-closure-vs-fire", ["doc-fire-north", "doc-fire-rumor"], "defer", "Пожар на площадке и неподтверждённое будущее закрытие требуют разных статусов."),
    ("old-vs-current-port-closure", ["doc-stale-port", "doc-port-official"], "create", "События различаются датой, причиной и объектом причала/порта; старое не обновляет новое."),
    ("cyber-vs-maintenance-stop", ["doc-cyber", "doc-line-stop"], "create", "Киберинцидент и плановое обслуживание линии названы отдельно."),
    ("tax-change-vs-sanction", ["doc-tax", "doc-sanction"], "create", "Изменение пошлины и санкция против компании имеют различные типы воздействия."),
    ("investment-vs-production-stop", ["doc-investment", "doc-line-stop"], "create", "Новая инвестиция не является остановкой линии."),
    ("unknown-date-export", ["doc-export-official"], "defer", "Без временного контекста нельзя привязать похожий текст к конкретной редакции меры."),
    ("export-product-typo-candidate", ["doc-export-official", "doc-unrelated-country"], "defer", "Кандидатное совпадение по слову микросхема недостаточно при разных кодах товара и стране."),
    ("new-investment-same-company", ["doc-investment", "doc-parent-release"], "create", "Объявление ТехноСборки и релиз материнской компании не один факт."),
    ("repost-not-independent-corroboration", ["doc-export-official", *[f"doc-export-reprint-{i:02d}" for i in range(1, 6)]], "attach", "Сохранить все mentions, но кластеризовать общий первичный источник."),
    ("different-fire-facility-alias", ["doc-fire-north", "doc-fire-east"], "create", "Названия заводов имеют общий префикс, но entity IDs и города различны."),
    ("multi-article-price-and-export", ["doc-export-multi", "doc-export-official", "doc-price-fact"], "attach", "Экспорт mention присоединяется к export event; price mention остаётся самостоятельным."),
    ("potential-vs-actual-shutdown", ["doc-line-stop", "doc-cyber"], "defer", "Киберинцидент не доказывает, что производство остановилось; плановая остановка описана отдельно."),
    ("historical-supplier-change", ["doc-c-history", "doc-c-official"], "correct", "Изменился текущий поставщик; прежняя связь закрывается по valid time, запись не удаляется."),
    ("source-version-correction", ["doc-export-official", "doc-export-correction"], "correct", "Новая версия уточняет срок, не создавая второй запрет."),
    ("partial-actor-only", ["doc-industry-only"], "defer", "Не названы компания, поставщик или точный участник события."),
    ("country-name-overlap", ["doc-export-official", "doc-tax"], "create", "Совпадение международной тематики не связывает разные страны и разные меры."),
    ("same-supplier-different-events", ["doc-sanction", "doc-default-rumor"], "defer", "Санкция подтверждена как notice, дефолт остаётся слухом и не должен сливаться с санкцией."),
    ("no-source-support", ["doc-industry-only"], "defer", "Общий прогноз сектора не позволяет создать company-specific event."),
    ("near-identical-title-different-sites", ["doc-fire-north", "doc-fire-east"], "create", "Сходство текста не перевешивает несовпадающие объекты и географию."),
]


def resolution_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": case_id,
            "input_document_ids": document_ids,
            "provisional_expectation": decision,
            "expected_properties": [property_text, "False merge считается более дорогой ошибкой, чем временный duplicate/defer."],
            "manual_approval": "provisional",
        }
        for case_id, document_ids, decision, property_text in RESOLUTION_CASE_ROWS
    ]


BUSINESS_CASE_ROWS = [
    ("sparse-export-country", "company-a", "event-export-x-mk7", "supplier countries", "Не выводить страну закупок из отрасли; вопрос может изменить экспозицию."),
    ("sparse-export-vendor", "company-a", "event-export-x-mk7", "named suppliers", "Запрашивать поставщиков, а не размер офиса."),
    ("skipped-is-not-no", "company-a", "event-export-x-mk7", "supplier countries", "Skipped ответ оставляет зависимость unknown."),
    ("sparse-import-share", "company-a", "event-export-x-mk7", "import share for MK-7", "Import share remains unknown until supplied."),
    ("b-export-purchase-volume", "company-b", "event-export-x-mk7", "MK-7 purchase volume", "Known supplier path does not invent procurement volume."),
    ("b-export-alternative-supplier", "company-b", "event-export-x-mk7", "alternative qualified suppliers", "Second supplier for other component is not an alternative for MK-7 unless stated."),
    ("b-port-alternate-route", "company-b", "event-port-vega", "alternate shipping routes", "Known route through Vega does not prove no alternative route."),
    ("b-sanction-scope", "company-b", "event-sanction-microkaskad", "sanction scope and affected component", "A supplier mention alone does not prove the legal measure applies to a transaction."),
    ("b-budget-one-question", "company-b", "event-export-x-mk7", "highest decision-relevant unknown", "A one-question budget should select a high-impact unknown."),
    ("b-budget-three-questions", "company-b", "event-port-vega", "alternate route, inventory, delivery timing", "Do not exceed preferences.max_questions."),
    ("c-price-input-quantity", "company-c", "event-price-nickel-actual", "procurement quantity and price basis", "No financial estimate without quantities and units."),
    ("c-contradictory-inventory", "company-c", "event-port-vega", "current inventory record with date", "Keep 8-day and 12-day statements and request reconciliation."),
    ("c-port-route-check", "company-c", "event-port-vega", "route dependency and alternate route", "Route exists in the profile; alternative route is unknown."),
    ("c-process-capacity", "company-c", "event-price-nickel-actual", "capacity and substitution flexibility", "Process description does not imply production capacity."),
    ("c-historical-supplier", "company-c", "event-sanction-microkaskad", "current supplier identity", "Do not use a supplier whose validity ended in 2025 as current."),
    ("declined-answer-preserved", "company-b", "event-export-x-mk7", "procurement share", "Declined answer remains unknown and retains its status."),
    ("forecast-vs-actual", "company-c", "event-price-nickel-forecast", "whether forecast has materialized", "Forecast is not a confirmed price change."),
    ("tax-product-scope", "company-b", "event-tax-lira", "applicable tariff code and sourcing country", "A tax notice does not establish the company's country of import."),
    ("industry-only-no-profile-fact", "company-a", "event-industry-outlook", "none without company-specific relevance", "Do not add supplier, geography, or dependency from sector similarity."),
    ("unknown-answer-not-negative", "company-a", "event-port-vega", "shipping route", "No answer or missing fact does not mean the company avoids the port."),
    ("question-preference-suppression", "company-c", "event-port-vega", "unsuppressed route unknown", "Honor suppressed_targets from the profile."),
    ("investment-amount-unknown", "company-c", "event-investment-techno", "investment amount and timing", "Announcement does not reveal amount or capacity date."),
]


def business_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": case_id,
            "company_id": company_id,
            "event_id": event_id,
            "focus": focus,
            "expected_properties": [property_text, "Question ranking is a provisional heuristic, not a calibrated information-gain estimate."],
            "manual_approval": "provisional",
        }
        for case_id, company_id, event_id, focus, property_text in BUSINESS_CASE_ROWS
    ]


EVIDENCE_CASES = [
    ("exact-anchor", "ev-export-official", "Only source-span integrity can be established from this check."),
    ("wrong-quote", "ev-export-official", "A quote not present in the cited immutable version fails anchor verification."),
    ("wrong-source-hash", "ev-export-official", "A mismatching whole-source hash must not be marked verified_anchor."),
    ("source-version-mismatch", "ev-export-correction", "Evidence is pinned to one document version; another version is a different ref."),
    ("source-unavailable", "doc-archived-unavailable", "Unavailable content remains unverified; missing text is not inferred."),
    ("verified-rumor-wording", "ev-rumor-default", "The quoted rumor is present, but the supplier default remains unconfirmed."),
    ("ten-syndicated-copies", "ev-export-reprint-01..10", "Ten copies share one syndication group and do not count as independent corroboration."),
    ("independent-roots", "ev-b-official + ev-b-independent", "Separate publisher roots can be presented to an explicit synthetic owner policy."),
    ("contradictory-stock", "ev-c-stock-8d + ev-c-stock-12d", "Preserve both verified anchors and mark the business fact disputed."),
    ("stale-source", "ev-stale-port", "A valid old anchor stays historical; it does not imply a current closure."),
    ("model-hypothesis", "no evidence ref", "Model output alone cannot move a hypothesis to confirmed."),
    ("confirmed-needs-owner-policy", "local-policy-reference", "Evidence refs and anchor validity alone do not authorize confirmed."),
]


GRAPH_CASES = [
    ("direct-country-supplier-company-path", "company-b", "Найти путь country-x → supplier-b-x → component-mk7 → company-b по переданным рёбрам."),
    ("direct-company-to-port", "company-b", "Маршрут через порт Вега имеет statement/evidence refs."),
    ("indirect-company-c-route", "company-c", "Путь проходит через route-c-vega; каждый hop ссылается на statement."),
    ("no-supplier-path-for-a", "company-a", "У company-a нет supplier edge; вернуть no path in supplied graph, не доказанное отсутствие риска."),
    ("unknown-is-not-negative", "company-a", "MissingDatum о поставщиках сохраняет open-world unknown."),
    ("stock-conflict", "company-c", "Противоречивые 8/12 days не материализуются как одно точное ребро/значение."),
    ("current-projection", "company-b", "Projection manifest pinned to supplied slice and as_of."),
    ("relevant-update-stales-projection", "company-b", "Обновление выбранного Business slice делает текущий graph stale."),
    ("unrelated-partition-update", "company-b", "Изменение несвязанного partition не обязано устаревать запрошенный scoped graph."),
    ("historical-supplier-edge", "company-c", "Supplier СырьёМаршрут-Пром действует только до конца 2025 года."),
    ("alias-does-not-merge-legal-entities", "company-b-parent", "Parent, subsidiary and company IDs remain distinct graph nodes."),
    ("alternate-ontology", "graph-shared-companies-current", "Ontology changes require a new projection; original statements remain unchanged."),
    ("hypothetical-only", "hypothetical-only", "The candidate stays hypothetical and does not become a factual/published dependency edge."),
    ("inferred-relation-grounding", "inferred-company-country-x", "The inferred candidate preserves an explicit method and two resolvable input StatementRefs; status remains inferred."),
    ("explicit-negative-not-positive-dependency", "explicit-negative-country-x", "Preserve the sourced negative company declaration without converting it into a positive edge or a universal no-risk conclusion."),
]


IMPACT_CASE_ROWS = [
    ("export-b-direct", "event-export-x-mk7", "company-b", "Potential mechanism may be stated only along the explicit country/supplier/component path."),
    ("export-a-unknown-supplier", "event-export-x-mk7", "company-a", "No direct path; preserve unknown sourcing and ask a targeted question."),
    ("port-b-known-route", "event-port-vega", "company-b", "Known route supports possible logistics exposure, not a quantified delay."),
    ("port-c-known-route-stock-conflict", "event-port-vega", "company-c", "Use route path; keep inventory contradiction and avoid a single buffer number."),
    ("nickel-price-c", "event-price-nickel-actual", "company-c", "Material relation exists; purchase volume and financial impact remain unknown."),
    ("nickel-price-a-no-material", "event-price-nickel-actual", "company-a", "No material/supplier path; sector similarity alone is insufficient."),
    ("sanction-b-supplier", "event-sanction-microkaskad", "company-b", "Supplier path is direct, but transaction scope and operational effect remain conditional."),
    ("sanction-a-unknown", "event-sanction-microkaskad", "company-a", "Unknown supplier does not prove exposure or non-exposure."),
    ("fire-north-a", "event-fire-north-plant", "company-a", "No supported business path; do not infer from manufacturing/electronics sector."),
    ("fire-east-b", "event-fire-east-plant", "company-b", "Near-name facility is not company-b without entity evidence."),
    ("supplier-default-rumor-b", "event-default-rumor", "company-b", "Rumor and different supplier cannot support a confident impact."),
    ("supplier-default-rumor-a", "event-default-rumor", "company-a", "No supplier match and rumor status both lower factual support."),
    ("tax-lira-b", "event-tax-lira", "company-b", "No evidenced sourcing link to Lira; return unknown/none-found for supplied graph."),
    ("cyber-b", "event-cyber-orbita", "company-b", "Direct company mention does not establish production stop or data loss."),
    ("line-stop-b-maintenance", "event-line-stop-orbita", "company-b", "Planned maintenance stop is not a supply disruption; amount and duration unknown."),
    ("investment-c", "event-investment-techno", "company-c", "Announcement is not proof of current production benefit or capacity."),
    ("export-q-product-mismatch", "event-export-meridian-mk9", "company-b", "Country/product mismatch prevents a positive conclusion from name/category overlap."),
    ("stale-port-closure-c", "event-port-old-2025", "company-c", "Historical 2025 event must not be reported as current exposure."),
    ("industry-only-a", "event-industry-outlook", "company-a", "No company-specific evidence; prohibit confident impact based only on sector."),
    ("export-b-known-supplier-no-volume", "event-export-x-mk7", "company-b", "Show mechanism; financial quantity stays null because volume is unknown."),
    ("export-b-explicit-numeric-assumptions", "event-export-x-mk7", "company-b", "Calculate only the explicitly supplied scenario metric; label gross procurement exposure, not loss."),
    ("export-b-source-conflict", "event-export-x-mk7", "company-b", "A conflict in evidence limits confidence; preserve both source refs."),
    ("port-c-no-alternate-route", "event-port-vega", "company-c", "Primary route is evidenced; alternate route is unknown, not absent."),
    ("multiple-events-one-article", "event-export-x-mk7", "company-b", "The source document has a second separate price-change mention; keep both mentions and event mechanisms separate."),
    ("same-headline-other-facility", "event-fire-east-plant", "company-a", "Do not use similar event wording to create an unsupported relationship."),
    ("forecast-is-not-realized", "event-price-nickel-forecast", "company-c", "Potential future price scenario cannot be described as a realized increase."),
    ("historical-supplier-not-current", "event-export-x-mk7", "company-c", "Expired relationship is not current; apply valid-time filter."),
    ("stock-conflict-no-averaging", "event-port-vega", "company-c", "Do not average 8 and 12 days or calculate cash loss."),
    ("graph-partial", "event-export-x-mk7", "company-b", "A partial graph can support listed paths only; no market-wide completeness claim."),
    ("no-path-not-no-risk", "event-export-x-mk7", "company-a", "Absence of a supplied path is not evidence of zero risk."),
]


def impact_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": case_id,
            "event_id": event_id,
            "company_id": company_id,
            "graph_id": "graph-shared-companies-current",
            "approaches": ["C", "D"],
            "same_inputs_required": True,
            "provisional_expectations": [property_text],
            "manual_approval": "provisional",
        }
        for case_id, event_id, company_id, property_text in IMPACT_CASE_ROWS
    ]


def data_payload() -> dict[str, Any]:
    event_catalog = [
        {"event_id": "event-export-x-mk7", "type": "export_restriction", "document_ids": ["doc-export-official", "doc-export-correction", "doc-export-wire-en", "doc-export-multi"], "evidence_ids": ["ev-export-official", "ev-export-correction", "ev-export-wire", "ev-multi-export"], "status": "synthetic notice; correction history retained"},
        {"event_id": "event-sanction-microkaskad", "type": "sanctions", "document_ids": ["doc-sanction"], "evidence_ids": ["ev-sanction"], "status": "synthetic official notice"},
        {"event_id": "event-port-vega", "type": "port_closure", "document_ids": ["doc-port-official", "doc-port-independent"], "evidence_ids": ["ev-port-official", "ev-port-independent"], "status": "synthetic 48-hour notice"},
        {"event_id": "event-fire-north-plant", "type": "facility_fire", "document_ids": ["doc-fire-north"], "evidence_ids": ["ev-fire-north"], "status": "reported at plant-north"},
        {"event_id": "event-fire-east-plant", "type": "facility_fire", "document_ids": ["doc-fire-east"], "evidence_ids": ["ev-fire-east"], "status": "reported at distinct plant-east"},
        {"event_id": "event-price-nickel-actual", "type": "raw_material_price_increase", "document_ids": ["doc-price-fact"], "evidence_ids": ["ev-price-fact"], "status": "synthetic supplier statement; not company loss"},
        {"event_id": "event-default-rumor", "type": "supplier_default", "document_ids": ["doc-default-rumor"], "evidence_ids": ["ev-rumor-default"], "status": "rumor only; unconfirmed"},
        {"event_id": "event-tax-lira", "type": "tax_change", "document_ids": ["doc-tax"], "evidence_ids": ["ev-tax"], "status": "synthetic notice with limited product scope"},
        {"event_id": "event-cyber-orbita", "type": "cyber_incident", "document_ids": ["doc-cyber"], "evidence_ids": ["ev-cyber"], "status": "investigation reported; no production stop asserted"},
        {"event_id": "event-line-stop-orbita", "type": "production_line_stop", "document_ids": ["doc-line-stop"], "evidence_ids": ["ev-line-stop"], "status": "planned maintenance"},
        {"event_id": "event-investment-techno", "type": "new_investment", "document_ids": ["doc-investment"], "evidence_ids": ["ev-investment"], "status": "amount and commissioning date unknown"},
        {"event_id": "event-export-meridian-mk9", "type": "export_restriction", "document_ids": ["doc-unrelated-country"], "evidence_ids": ["ev-unrelated-country"], "status": "negative comparison case; different country and product"},
        {"event_id": "event-price-nickel-forecast", "type": "price_forecast", "document_ids": ["doc-price-forecast"], "evidence_ids": ["ev-price-forecast"], "status": "forecast only; not a realized price change"},
        {"event_id": "event-port-old-2025", "type": "historical_port_closure", "document_ids": ["doc-stale-port"], "evidence_ids": ["ev-stale-port"], "status": "expired 2025 maintenance closure; historical negative case"},
        {"event_id": "event-industry-outlook", "type": "sector_forecast", "document_ids": ["doc-industry-only"], "evidence_ids": ["ev-industry-only"], "status": "sector-level commentary; no named company or dependency"},
    ]
    negative_cases = [
        {"case_id": "negative-industry-only", "document_ids": ["doc-industry-only"], "property": "No positive company impact without a non-sector-specific explicit basis."},
        {"case_id": "negative-near-name", "entity_ids": ["company-a", "company-a-near"], "property": "Name similarity alone must not resolve legal-entity identity."},
        {"case_id": "negative-parent-subsidiary", "entity_ids": ["company-b-parent", "company-b", "company-b-subsidiary"], "property": "Parent/subsidiary relationship does not merge entities or prove shared suppliers."},
        {"case_id": "negative-other-country", "document_ids": ["doc-unrelated-country"], "property": "Country Mеридиан and MK-9 are not the Country X/MK-7 restriction."},
        {"case_id": "negative-rumor", "document_ids": ["doc-default-rumor", "doc-fire-rumor"], "property": "Rumor remains unconfirmed even if its anchor is present."},
        {"case_id": "negative-forecast", "document_ids": ["doc-price-forecast"], "property": "Forecast is not a realized price event."},
        {"case_id": "negative-stale", "document_ids": ["doc-stale-port"], "property": "A 2025 closure is not current in an October 2026 assessment."},
        {"case_id": "negative-unknown-supplier", "company_id": "company-a", "property": "Unknown supplier does not prove either exposure or non-exposure."},
    ]
    confirmed_statement_ids = sorted(
        statement_item["statement_id"]
        for profile in COMPANY_PROFILES
        for snapshot in profile["snapshots"]
        for statement_item in snapshot["statements"]
        if statement_item["epistemic_status"] == "confirmed"
    ) + ["event-export-claim"]
    return {
        "schema": "alfalab.spike.synthetic-corpus/v1",
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "as_of": {"valid_as_of": AS_OF, "known_as_of": AS_OF},
        "provenance": {
            "origin": "synthetic",
            "creator": "hand-authored deterministic fixture builder",
            "base_commit": BASE_COMMIT,
            "supersedes_version": "1.0.0",
            "pdf_source": PDF_PATH.name,
            "external_sources_used_for_facts": False,
            "model_outputs_used_as_labels": False,
        },
        "entities": list(ENTITIES.values()),
        "entity_resolution_cases": [
            {"left": "company-a", "right": "company-a-near", "relation": "near_name_distinct_ids", "expected_property": "Do not merge by name similarity."},
            {"left": "company-b-parent", "right": "company-b", "relation": "parent_of", "expected_property": "Related but legally distinct entities."},
            {"left": "company-b-parent", "right": "company-b-subsidiary", "relation": "parent_of", "expected_property": "Related but legally distinct entities."},
            {"left": "company-b", "right": "company-b-subsidiary", "relation": "sibling_entities", "expected_property": "Do not treat one subsidiary's facts as another's."},
            {"entity_id": "company-b", "aliases": ["Орбита Электроникс", "Orbit Electronics", "Орбита Электроникс АО"], "expected_property": "Aliases may resolve to company-b only when the alias registry says so."},
            {"entity_id": "supplier-b-x", "aliases": ["МикроКаскад", "MicroKaskad"], "expected_property": "Transliteration alias does not imply a different supplier is identical."},
            {"left": "plant-north", "right": "plant-east", "relation": "near_name_distinct_facilities", "expected_property": "Same words in facility names do not imply same incident or site."},
        ],
        "source_documents": DOCUMENTS,
        "source_grouping_expectations": {
            "syndication_group_id": "export-x-20261013",
            "document_ids": [f"doc-export-reprint-{i:02d}" for i in range(1, 11)],
            "publisher_root_id": "regulator-x",
            "expected_property": "Ten copies are one syndication family; a different outlet label is not independent corroboration.",
        },
        "evidence_catalog": list(EVIDENCE.values()),
        "company_profiles": COMPANY_PROFILES,
        "t12_graph_inputs": graph_test_inputs(),
        "synthetic_confirmed_assertion_policy": {
            "policy_id": "test-owner-policy-t09-t13-v1",
            "version": VERSION,
            "scope": "Only this provisional synthetic corpus; never a production trust threshold or authorization.",
            "authorized_statement_ids": confirmed_statement_ids,
            "requirements": [
                "The local owner explicitly opts in for each named synthetic statement.",
                "Each assertion has at least two Evidence refs with exact verified anchors against immutable synthetic source versions.",
                "Supporting documents have distinct publisher_root_id values; syndicated copies count as one root.",
                "No unresolved same-time contradiction exists for the assertion.",
                "A verified anchor establishes only that a quote is present; the policy separately evaluates the claim and its independent support.",
            ],
            "explicit_non_policy": "No universal source reliability score or production confirmed threshold is asserted.",
        },
        "news_event_catalog": event_catalog,
        "t09_resolution_cases": resolution_cases(),
        "t10_business_question_cases": business_cases(),
        "t11_evidence_policy_cases": [
            {"case_id": case_id, "input_ref": ref, "expected_properties": [expectation], "manual_approval": "provisional"}
            for case_id, ref, expectation in EVIDENCE_CASES
        ],
        "t12_graph_cases": [
            {"case_id": case_id, "input_ref": ref, "expected_properties": [expectation], "manual_approval": "provisional"}
            for case_id, ref, expectation in GRAPH_CASES
        ],
        "t13_impact_cases": impact_cases(),
        "non_positive_evidence_cases": negative_cases,
        "controlled_numeric_scenario": {
            "scenario_id": "numeric-assumptions-only-v1",
            "classification": "synthetic",
            "company_id": "company-b",
            "event_id": "event-export-x-mk7",
            "inputs": [
                {"name": "monthly_quantity", "value": "800", "unit": "items/month", "origin": "explicit_test_assumption"},
                {"name": "unit_price", "value": "50", "unit": "RUB/item", "origin": "explicit_test_assumption"},
                {"name": "affected_share", "value": "0.25", "unit": "fraction", "origin": "explicit_test_assumption"},
            ],
            "expected_calculation": {"name": "gross_procurement_value_on_affected_share", "value": "10000", "unit": "RUB/month"},
            "limitations": ["This is an explicitly supplied scenario, not a company fact.", "The arithmetic is gross procurement exposure, not loss, likelihood, or materiality.", "No amount may be inferred from the ordinary company-b profile, whose purchase volume is unknown."],
        },
        "invalid_or_unavailable_source_cases": [
            {"case_id": "wrong-quote", "source_ref": "doc-export-official@1", "mutation": "quote not present", "expected_property": "verification must fail or remain unverified"},
            {"case_id": "wrong-hash", "source_ref": "doc-export-official@1", "mutation": "replace source hash with sha256:" + "0" * 64, "expected_property": "verification must fail"},
            {"case_id": "other-version", "source_ref": "doc-export-official@2", "mutation": "change immutable source revision", "expected_property": "do not resolve against revision 1"},
            {"case_id": "unavailable-source", "source_ref": "doc-archived-unavailable@1", "mutation": "source content unavailable", "expected_property": "remain unverified; do not infer quote or truth"},
        ],
        "financial_scenarios": [
            {"scenario_id": "unknown-financial-volume", "company_id": "company-a", "event_id": "event-export-x-mk7", "inputs": [], "expected_property": "financial_quantity=null; no loss estimate"},
            {"scenario_id": "explicit-assumptions", "ref": "numeric-assumptions-only-v1", "expected_property": "Only calculate the provided conditional gross procurement value; never label it loss."},
        ],
    }


OPERATION_IDS = [
    "Understanding.extract",
    "Events.propose_resolution",
    "Events.apply",
    "Events.read",
    "Business.propose_profile",
    "Business.propose_questions",
    "Business.apply",
    "Business.read",
    "Evidence.register",
    "Evidence.read",
    "Graph.build",
    "Graph.publish",
    "Graph.query",
    "Matching.match",
    "Impact.assess",
    "Recommendations.propose",
]

APPROVED_FIXTURES = {
    "Understanding.extract": "two-events",
    "Events.read": "partition-page",
    "Business.read": "current-minimal",
    "Evidence.read": "span-with-source",
    "Graph.query": "current-chain",
}

FIXTURE_CASES = {
    "understanding-extract": (
        "Understanding.extract",
        "Двухсобытийная подготовленная публикация об экспортном ограничении и отдельном изменении цены.",
        ["doc-export-multi"],
        [
            "Output contains two separate mentions with exact spans in the supplied prepared text.",
            "Mentions carry observed text-level claims and do not authorize confirmed business impact.",
            "The fixture material is independently authored and does not call T08.",
        ],
        ["Expected properties are provisional scenario labels, not extraction-quality measurements."],
    ),
    "events-read": (
        "Events.read",
        "Materialized synthetic event read snapshot with an official correction and two distinct near-name fires.",
        ["event-export-x-mk7", "event-fire-north-plant", "event-fire-east-plant"],
        [
            "Export event preserves the initial unknown end date and later correction as bitemporal statements.",
            "The two fire records retain distinct event and facility IDs despite similar titles.",
            "Every confirmed event statement references Evidence records and the local test owner policy.",
        ],
        ["This is a prepared read payload; it is not a production Events database or algorithm output."],
    ),
    "business-read": (
        "Business.read",
        "Sparse current profile for the fictional radio-parts trader, including explicitly unknown dependencies.",
        ["company-a", "a-activity-v1", "a-activity-v2"],
        [
            "The current snapshot contains no inferred supplier, procurement country, volume, or import share.",
            "Skipped question status remains a skipped answer and does not become a negative fact.",
            "Earlier profile snapshot is retained in the frozen corpus for history tests.",
        ],
        ["The response selects revision 2; it does not represent a live Business owner read."],
    ),
    "evidence-read": (
        "Evidence.read",
        "Metadata-only evidence snapshot with checked anchors, an unverified record, and syndicated copies.",
        sorted(EVIDENCE),
        [
            "Verified anchor means the exact quoted span is present in the pinned source version.",
            "Verified anchors do not establish that a source claim is true or that a company is exposed.",
            "Ten syndicated copies share one source root/group and are not ten independent corroborations.",
            "The unavailable archive has no checked quote and remains unverified.",
        ],
        ["Source text is not returned in the operation payload; synthetic source text is separately in data.json."],
    ),
    "graph-query": (
        "Graph.query",
        "Partial multi-company projection containing only explicitly sourced relationships.",
        ["graph-shared-companies-current", "company-a", "company-b", "company-c"],
        [
            "Known B and C paths are composed from existing statement references and Evidence references.",
            "Company A remains disconnected for suppliers while explicit missing_data preserves open-world unknown.",
            "Graph completeness remains partial, and the snapshot is pinned to three Business slices and one time cut.",
            "No inferred edges are included; an absent edge is not interpreted as no dependency.",
        ],
        ["The source-owner partitions are synthetic and isolated; freshness is validated against this declared snapshot only."],
    ),
}


def portable_file_hash(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}:
        payload = raw
    else:
        payload = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return digest_bytes(payload)


def source_file_hash(relative_path: str) -> str:
    return portable_file_hash(ROOT / relative_path)


def source_references() -> list[dict[str, Any]]:
    refs = [
        {"path": "docs/specs/framework-v1/contracts/operations.json", "sha256": source_file_hash("docs/specs/framework-v1/contracts/operations.json")},
        {"path": "docs/specs/framework-v1/contracts/openapi.json", "sha256": source_file_hash("docs/specs/framework-v1/contracts/openapi.json")},
        {"path": "packages/contracts/src/alfalab_contracts/_generated.py", "sha256": source_file_hash("packages/contracts/src/alfalab_contracts/_generated.py")},
        {"path": "packages/contracts/src/alfalab_contracts/models.py", "sha256": source_file_hash("packages/contracts/src/alfalab_contracts/models.py")},
        {"path": "packages/contracts/src/alfalab_contracts/registry.py", "sha256": source_file_hash("packages/contracts/src/alfalab_contracts/registry.py")},
        {"path": "packages/contracts/src/alfalab_contracts/semantics.py", "sha256": source_file_hash("packages/contracts/src/alfalab_contracts/semantics.py")},
        {"path": "docs/specs/framework-v1/02-contracts.md", "sha256": source_file_hash("docs/specs/framework-v1/02-contracts.md")},
        {"path": "docs/specs/framework-v1/08-verification.md", "sha256": source_file_hash("docs/specs/framework-v1/08-verification.md")},
    ]
    return refs


def operation_lock_and_schema() -> tuple[dict[str, Any], dict[str, Any]]:
    import sys

    sys.path.insert(0, str(ROOT / "packages/contracts/src"))
    from alfalab_contracts.registry import load_operation_registry

    operations_path = ROOT / "docs/specs/framework-v1/contracts/operations.json"
    openapi_path = ROOT / "docs/specs/framework-v1/contracts/openapi.json"
    registry, contracts = load_operation_registry(operations_path, openapi_path)
    openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    schemas = openapi["components"]["schemas"]
    locked_ops = []
    union_components: set[str] = set()
    for operation_id in OPERATION_IDS:
        contract = contracts[operation_id]
        entry = contract.descriptor
        closure: set[str] = set()
        pending = [entry.request_model, entry.response_model]
        while pending:
            name = pending.pop()
            if name in closure:
                continue
            closure.add(name)
            schema = schemas[name]
            pending.extend(_schema_refs(schema))
        union_components.update(closure)
        locked_ops.append(
            {
                "operation_id": entry.operation_id,
                "owner": entry.owner,
                "kind": entry.kind,
                "path": entry.path,
                "method": entry.method,
                "contract_version": entry.contract_version,
                "request_model": entry.request_model,
                "input_model": entry.input_model,
                "output_model": entry.output_model,
                "response_model": entry.response_model,
                "schema_hash": entry.schema_hash,
                "component_names": sorted(closure),
            }
        )
    lock = {
        "schema": "alfalab.spike.contract-lock/v1",
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "base_commit": BASE_COMMIT,
        "operation_registry_version": registry.version,
        "operation_registry_hash": source_file_hash("docs/specs/framework-v1/contracts/operations.json"),
        "openapi_hash": source_file_hash("docs/specs/framework-v1/contracts/openapi.json"),
        "source_refs": source_references(),
        "operations": locked_ops,
        "manual_approval": "provisional",
    }
    snapshot = {
        "schema": "alfalab.spike.openapi-closure/v1",
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "openapi_path": "docs/specs/framework-v1/contracts/openapi.json",
        "openapi_sha256": source_file_hash("docs/specs/framework-v1/contracts/openapi.json"),
        "component_names": sorted(union_components),
        "schemas": {name: schemas[name] for name in sorted(union_components)},
        "manual_approval": "provisional",
    }
    return lock, snapshot


def _schema_refs(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.append(ref.removeprefix("#/components/schemas/"))
        for child in value.values():
            found.extend(_schema_refs(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_schema_refs(child))
    return found


def approved_fixture_refs() -> dict[str, Any]:
    index_path = ROOT / "fixtures/approved/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    fixture_refs = []
    for operation_id, fixture_id in APPROVED_FIXTURES.items():
        manifest_path = f"fixtures/approved/{operation_id}/{fixture_id}/manifest.json"
        index_key = f"{operation_id}/{fixture_id}/manifest.json"
        portable_hash = portable_file_hash(ROOT / manifest_path)
        approved_index_hash = index["files"][index_key]
        fixture_refs.append(
            {
                "operation_id": operation_id,
                "fixture_id": fixture_id,
                "path": manifest_path,
                "sha256": portable_hash,
                "approved_index_sha256": approved_index_hash,
            }
        )
    datasets = []
    for dataset_id in ["radio-export-v1", "steel-buffer-v1"]:
        entry = index["datasets"][dataset_id]
        data_hash = portable_file_hash(ROOT / entry["data_path"])
        manifest_hash = portable_file_hash(ROOT / entry["manifest_path"])
        datasets.append(
            {
                "dataset_id": dataset_id,
                "data_path": entry["data_path"],
                "data_sha256": data_hash,
                "approved_data_index_sha256": "sha256:" + entry["data_sha256"],
                "manifest_path": entry["manifest_path"],
                "manifest_sha256": manifest_hash,
                "approved_manifest_index_sha256": "sha256:" + entry["manifest_sha256"],
            }
        )
    return {
        "schema": "alfalab.spike.approved-fixture-refs/v1",
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "index_path": "fixtures/approved/index.json",
        "index_sha256": portable_file_hash(index_path),
        "fixture_refs": fixture_refs,
        "dataset_refs": datasets,
        "manual_approval": "provisional",
        "note": "These are read-only pointers to previously approved fixtures; this provisional corpus is not approved by reference.",
    }


def execution_envelopes(
    operation_id: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    source_document_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture_name = next(name for name, case in FIXTURE_CASES.items() if case[0] == operation_id)
    request_id = "fixture-" + fixture_name + "-v1"
    run_id = "materialized-" + fixture_name + "-v1"
    implementation = versioned_ref("mock.baseline")
    request = {
        "contract_version": "1.0.0",
        "request_id": request_id,
        "sandbox_id": "spike-t09-t13-offline",
        "implementation": {"id": implementation["id"], "version": implementation["version"], "parameters": {"scenario": "default"}},
        "execution": {"mode": "live", "recording": "full", "analytical_time": AS_OF, "random_seed": 20261014, "timeout_ms": 30000},
        "data_declaration": "synthetic",
        "payload": input_payload,
    }
    source_document_ids = sorted(set(source_document_ids))
    meta = {
        "run_id": run_id,
        "operation_id": operation_id,
        "contract_version": "1.0.0",
        "implementation": implementation,
        "execution_mode": "live",
        "environment": "testing",
        "configuration_hash": digest({"fixture_id": fixture_name, "version": VERSION}),
        "duration_ms": 0,
        "lineage": {
            "synthetic_source": True,
            "mock_derivation": True,
            "unknown_origin": False,
            "source_refs": source_refs(source_document_ids),
        },
        "trace_status": "complete",
        "replay_status": "available",
        "measurements": [],
        "data_policy": {
            "policy": versioned_ref("spike.synthetic-fixture-policy"),
            "classification": "synthetic",
            "processing_allowed": True,
            "egress_allowed": False,
            "recording": "full",
            "export_allowed": False,
            "reason_codes": ["offline_synthetic_fixture"],
        },
    }
    response = {"meta": meta, "status": "success", "payload": output_payload}
    return request, response


def materialized_fixture_payloads() -> dict[str, dict[str, Any]]:
    doc = DOCS["doc-export-multi"]
    text = doc["text"]
    raw_hash = text_hash(text)
    input_material = {
        "material": {
            "material_id": "material-doc-export-multi-v1",
            "source_id": "daily-ledger",
            "source_url": None,
            "title": doc["title"],
            "text": text,
            "published_at": doc["published_at"],
            "collected_at": doc["collected_at"],
            "content_hash": doc["content_hash"],
            "language": "ru",
            "provenance": provenance("synthetic", ["doc-export-multi"]),
        },
        "raw_hash": raw_hash,
        "prepared_hash": raw_hash,
        "quality": "valid",
        "span_map": [{"prepared_start": 0, "prepared_end": len(text), "raw_start": 0, "raw_end": len(text)}],
        "warnings": [],
    }
    export_quote = "ограничила экспорт микросхем МК-7 с 13 октября"
    price_quote = "повысила отпускную цену платы П-17 на 4%"
    export_statement = statement(
        "extract-export-restriction", ENTITIES["country-x"], "restricts_export",
        value_entity(ENTITIES["component-mk7"]), "observed", [], ["doc-export-multi"],
        "2026-10-13T00:00:00Z", None, "2026-10-13T10:00:00Z",
    )
    price_statement = statement(
        "extract-sale-price-change", ENTITIES["company-b"], "increases_sale_price",
        value_number("4", "percent"), "observed", [], ["doc-export-multi"],
        "2026-10-13T10:00:00Z", None, "2026-10-13T10:00:00Z",
    )
    extract_output = {
        "mentions": [
            {
                "mention_id": "mention-export-multi-export",
                "event_type": code_ref("export_restriction", "alfalab.event-taxonomy"),
                "actors": [ENTITIES["country-x"]],
                "objects": [ENTITIES["component-mk7"]],
                "statements": [export_statement],
                "effective_at": "2026-10-13T00:00:00Z",
                "missing_data": [missing_datum("/event/valid_to", "Срок ограничения в этой статье не указан.")],
                "provenance": provenance("synthetic", ["doc-export-multi"]),
            },
            {
                "mention_id": "mention-export-multi-price",
                "event_type": code_ref("price_change", "alfalab.event-taxonomy"),
                "actors": [ENTITIES["company-b"]],
                "objects": [ENTITIES["product-p17"]],
                "statements": [price_statement],
                "effective_at": "2026-10-13T10:00:00Z",
                "missing_data": [],
                "provenance": provenance("synthetic", ["doc-export-multi"]),
            },
        ],
        "evidence_spans": [
            {"local_id": "span-export-restriction", "material_hash": raw_hash, "locator": {**evidence_span("doc-export-multi", export_quote), "quote_hash": text_hash(export_quote)}, "claim_ids": ["extract-export-restriction"]},
            {"local_id": "span-price-change", "material_hash": raw_hash, "locator": {**evidence_span("doc-export-multi", price_quote), "quote_hash": text_hash(price_quote)}, "claim_ids": ["extract-sale-price-change"]},
        ],
        "unresolved_entities": [],
        "missing_data": [],
    }
    profile_a = PROFILE_SNAPSHOT_BY_ID["company-a"]
    event_snapshot = {
        "events": [EVENT_EXPORT, EVENT_FIRE_NORTH, EVENT_FIRE_EAST],
        "slice": {"owner": "Events", "partition_id": "t09-synthetic-events", "revision": 1, "selection_key": "synthetic-current-events"},
        "as_of": {"valid_as_of": AS_OF, "known_as_of": AS_OF},
    }
    evidence_records = [
        {key: value for key, value in item.items() if key != "test_claim"}
        for item in EVIDENCE.values()
    ]
    graph_required_slices = GRAPH_SHARED["manifest"]["input_slices"]
    graph_query_result = {
        "kind": "subgraph",
        "subgraph": {
            "snapshot": GRAPH_SHARED,
            "freshness": "current",
            "missing_slices": [],
            "traversal_truncated": False,
            "query_scope": ["company-a", "company-b", "company-c"],
        },
    }
    payloads = {
        "understanding-extract": (
            {"material": input_material, "event_schema": versioned_ref("alfalab.event-taxonomy"), "hints": [], "known_entities": [ENTITIES[key] for key in ["company-b", "country-x", "component-mk7", "product-p17"]]},
            extract_output,
            ["doc-export-multi"],
        ),
        "events-read": (
            {"query": {"kind": "events", "event_ids": [], "partition_id": "t09-synthetic-events", "as_of": {"valid_as_of": AS_OF, "known_as_of": AS_OF}, "limit": 100, "cursor": None}},
            {"kind": "events", "snapshot": event_snapshot, "next_cursor": None},
            ["doc-export-official", "doc-export-correction", "doc-export-wire-en", "doc-fire-north", "doc-fire-east"],
        ),
        "business-read": (
            {"query": {"kind": "business", "company_id": "company-a", "revision": 2, "as_of": None}},
            {"kind": "business", "snapshot": profile_a},
            ["doc-a-self"],
        ),
        "evidence-read": (
            {"query": {"kind": "evidence", "refs": [item["ref"] for item in EVIDENCE.values()], "include_source_text": False}},
            {"kind": "evidence", "records": evidence_records, "source_artifacts": [], "missing_refs": []},
            [item["document_id"] for item in DOCUMENTS if item["document_id"] in {e["source_ref"]["object_id"] for e in evidence_records}],
        ),
        "graph-query": (
            {"query": {"kind": "subgraph", "graph_id": GRAPH_SHARED["graph_id"], "revision": GRAPH_SHARED["revision"], "seed_ids": [], "relations": [], "max_depth": 5, "max_nodes": 100, "required_slices": graph_required_slices, "freshness_policy": "current_required", "as_of": GRAPH_SHARED["manifest"]["as_of"]}},
            graph_query_result,
            ["doc-b-official", "doc-b-independent", "doc-b-self-secondary", "doc-c-official", "doc-c-independent", "doc-a-self"],
        ),
    }
    results: dict[str, dict[str, Any]] = {}
    for fixture_name, (input_payload, output_payload, source_document_ids) in payloads.items():
        operation_id, description, input_refs, expected, limitations = FIXTURE_CASES[fixture_name]
        request, response = execution_envelopes(operation_id, input_payload, output_payload, source_document_ids)
        data_hash = digest({"operation_id": operation_id, "request": request, "response": response})
        results[fixture_name] = {
            "schema": "alfalab.spike.materialized-operation-fixture/v1",
            "fixture_id": "fixture-" + fixture_name + "-v1",
            "version": VERSION,
            "origin": "synthetic",
            "provenance": "Hand-authored, deterministic offline fixture builder; not generated by T08/T09-T13 or a model.",
            "description": description,
            "dataset_ref": {"dataset_id": DATASET_ID, "version": VERSION},
            "input_refs": input_refs,
            "expected_properties": expected,
            "limitations": limitations,
            "data_hash": data_hash,
            "manual_approval": "provisional",
            "operation_id": operation_id,
            "request": request,
            "response": response,
        }
    return results


def synthetic_owner_policy() -> dict[str, Any]:
    payload = data_payload()
    return {
        "schema": "alfalab.spike.synthetic-owner-policy/v1",
        "policy_id": "test-owner-policy-t09-t13-v1",
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "scope": "Named assertions in this provisional synthetic dataset only.",
        "authorized_statement_ids": payload["synthetic_confirmed_assertion_policy"]["authorized_statement_ids"],
        "rules": payload["synthetic_confirmed_assertion_policy"]["requirements"],
        "explicit_non_policy": payload["synthetic_confirmed_assertion_policy"]["explicit_non_policy"],
        "manual_approval": "provisional",
    }


def read_existing_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def output_path_set() -> list[Path]:
    contract_dir = SHARED / "contracts" / DATASET_ID
    fixture_dir = SHARED / "fixtures" / DATASET_ID
    dataset_dir = SHARED / "datasets" / DATASET_ID
    return [
        SHARED / "README.md",
        dataset_dir / "data.json",
        dataset_dir / "manifest.json",
        contract_dir / "operations-lock.json",
        contract_dir / "openapi-schema-snapshot.json",
        contract_dir / "approved-fixture-refs.json",
        contract_dir / "synthetic-owner-policy.json",
        contract_dir / "COMPATIBILITY_GAPS.md",
        *(fixture_dir / f"{name}.json" for name in FIXTURE_CASES),
    ]


def main() -> None:
    global ALLOW_REPLACE_OUTPUTS
    args = sys.argv[1:]
    supersede = args == ["--supersede", "1.0.0"]
    if args and not supersede:
        raise SystemExit("usage: python -B spike/_shared/validation/freeze_v1.py [--supersede 1.0.0]")
    outputs = output_path_set()
    existing = [str(path) for path in outputs if path.exists()]
    if existing and not supersede:
        raise FileExistsError("freeze is immutable; output already exists: " + ", ".join(existing))
    if supersede:
        previous_manifest = read_existing_json(SHARED / "datasets" / DATASET_ID / "manifest.json")
        previous_data = read_existing_json(SHARED / "datasets" / DATASET_ID / "data.json")
        if previous_manifest.get("version") != "1.0.0" or previous_data.get("version") != "1.0.0":
            raise ValueError("--supersede 1.0.0 is permitted only when the frozen predecessor is v1.0.0")
        ALLOW_REPLACE_OUTPUTS = True

    data = data_payload()
    data_hash = digest(data)
    lock, schema_snapshot = operation_lock_and_schema()
    approved = approved_fixture_refs()
    fixtures = materialized_fixture_payloads()

    sys.path.insert(0, str(ROOT / "packages/contracts/src"))
    from alfalab_contracts.registry import load_operation_registry, validate_operation_exchange

    registry, contracts = load_operation_registry(
        ROOT / "docs/specs/framework-v1/contracts/operations.json",
        ROOT / "docs/specs/framework-v1/contracts/openapi.json",
    )
    for fixture in fixtures.values():
        validate_operation_exchange(
            contracts[fixture["operation_id"]],
            canonical_bytes(fixture["request"]),
            canonical_bytes(fixture["response"]),
        )

    data_path = SHARED / "datasets" / DATASET_ID / "data.json"
    lock_path = SHARED / "contracts" / DATASET_ID / "operations-lock.json"
    schema_path = SHARED / "contracts" / DATASET_ID / "openapi-schema-snapshot.json"
    approved_path = SHARED / "contracts" / DATASET_ID / "approved-fixture-refs.json"
    policy_path = SHARED / "contracts" / DATASET_ID / "synthetic-owner-policy.json"
    write_json(data_path, data)
    write_json(lock_path, lock)
    write_json(schema_path, schema_snapshot)
    write_json(approved_path, approved)
    policy = synthetic_owner_policy()
    write_json(policy_path, policy)

    fixture_manifest_refs = []
    for fixture_name, fixture in fixtures.items():
        fixture_path = SHARED / "fixtures" / DATASET_ID / f"{fixture_name}.json"
        write_json(fixture_path, fixture)
        fixture_manifest_refs.append(
            {
                "fixture_id": fixture["fixture_id"],
                "operation_id": fixture["operation_id"],
                "path": str(fixture_path.relative_to(SHARED)).replace("\\", "/"),
                "sha256": portable_file_hash(fixture_path),
                "data_hash": fixture["data_hash"],
            }
        )

    pdf_hash = digest_bytes(PDF_PATH.read_bytes())
    source_refs_list = source_references()
    manifest = {
        "schema": "alfalab.spike.synthetic-dataset-manifest/v1",
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "origin": "synthetic",
        "provenance": {
            "creator": "hand-authored deterministic fixture builder",
            "base_commit": BASE_COMMIT,
            "pdf_source": {"path": str(PDF_PATH), "name": PDF_PATH.name, "sha256": pdf_hash, "pages_reviewed": [4, 5, 6, 7, 8, 9]},
            "framework_sources": source_refs_list,
            "approved_fixture_index": {"path": "fixtures/approved/index.json", "sha256": approved["index_sha256"]},
            "external_facts_used": False,
            "model_outputs_used_as_labels": False,
        },
        "description": "Independent provisional synthetic corpus for algorithm experiments T09-T13.",
        "supersedes": {
            "version": "1.0.0",
            "commit": "db48cd37491e8fab8a9f122ae4b100da72197a81",
            "reason": "Portable normalized-LF artifact hashes and executable grounded/inferred, hypothetical, and explicit-negative T12 inputs.",
        },
        "created_at": AS_OF,
        "as_of": data["as_of"],
        "inputs": [
            "Hand-authored synthetic company, event, source, evidence, and graph records in data.json.",
            "Read-only contract and approved-fixture references recorded under contracts/.",
        ],
        "expected_properties": [
            "Unknowns are explicit and absence of a graph edge is not a negative assertion.",
            "The named T09/T10/T11/T12/T13 cases are property expectations, not model-derived labels.",
            "False event merges, invented business facts, anchor/truth confusion, invented graph edges, and unsupported impact are critical failure cases.",
        ],
        "limitations": [
            "Synthetic scenarios do not establish real-world algorithm quality.",
            "The confirmed status examples use only the explicitly described local synthetic test-owner policy.",
            "Publisher-root/syndication grouping and owner-policy linkage are local experimental metadata because the normative DTOs do not carry those fields.",
            "The shared graph is partial; its missing edges cannot be interpreted as non-dependencies.",
        ],
        "files": {
            "data.json": {"canonical_sha256": data_hash, "file_sha256": portable_file_hash(data_path)},
            "operations-lock.json": portable_file_hash(lock_path),
            "openapi-schema-snapshot.json": portable_file_hash(schema_path),
            "approved-fixture-refs.json": portable_file_hash(approved_path),
            "synthetic-owner-policy.json": portable_file_hash(policy_path),
        },
        "contracts": {
            "operation_ids": OPERATION_IDS,
            "lock_path": f"contracts/{DATASET_ID}/operations-lock.json",
            "schema_snapshot_path": f"contracts/{DATASET_ID}/openapi-schema-snapshot.json",
        },
        "approved_fixture_refs": f"contracts/{DATASET_ID}/approved-fixture-refs.json",
        "fixtures": fixture_manifest_refs,
        "data_hash": data_hash,
        "manual_approval": "provisional",
        "status": "provisional_not_gold_not_approved",
    }
    write_json(SHARED / "datasets" / DATASET_ID / "manifest.json", manifest)

    gaps = """# Compatibility gaps (recorded, not patched)\n\nThis version keeps all source grouping and test owner policy local to `spike/_shared`. No normative DTO or OpenAPI file was changed.\n\n- `#/components/schemas/RawMaterial/properties` and `#/components/schemas/Provenance/properties` have no `publisher_root_id` or `syndication_group_id` fields. The corpus stores `publisher_root_id` and `syndication_group_id` in local synthetic source metadata.\n- `#/components/schemas/Provenance/properties` has no trusted-owner-policy reference. The fixture corpus stores a local named test policy and authorized statement IDs; this is not a production authorization or threshold.\n- `#/components/schemas/EvidenceRecord/properties` stores anchor verification and a source-reliability label, but does not express independent-source grouping or a claim-truth decision. T11 must not treat `verified_anchor` as confirmation of the claim.\n- `#/components/schemas/GraphEdge/properties` has no explicit negative-polarity field. The T12 negative declaration is preserved as a sourced experimental Statement input and must not be encoded as a positive edge or inferred from a missing edge.\n- `#/components/schemas/Statement/properties/predicate` accepts a versioned code reference, but the frozen schema checks only the code-reference shape and contains no owner-approved semantic mapping for experimental predicate codes `sources_from_country`, `does_not_source_from_country`, or `depends_on_country`. Their graph interpretation requires ontology/contract-owner review.\n\nThese are explicit constraints for the spike; resolving them would require a separately approved contract decision.\n"""
    gaps_path = SHARED / "contracts" / DATASET_ID / "COMPATIBILITY_GAPS.md"
    gaps_path.parent.mkdir(parents=True, exist_ok=True)
    if gaps_path.exists() and not ALLOW_REPLACE_OUTPUTS:
        raise FileExistsError(gaps_path)
    gaps_path.write_text(gaps, encoding="utf-8", newline="\n")

    readme = f"""# Shared T09–T13 provisional fixtures\n\nDataset: `{DATASET_ID}` version `{VERSION}`.\n\nThe dataset is synthetic and provisional; it is not an approved or gold dataset. It is independent of T08 and of T09–T13 implementations. All five materialized operation fixtures are prepared offline, validated strictly with the repository's pinned Pydantic v2 contracts, and do not call a model, network service, database, or module implementation.\n\n## Contents\n\n- `datasets/{DATASET_ID}/data.json` — companies, documents, evidence, profiles, event catalog, graph, and 100+ hand-authored property cases.\n- `datasets/{DATASET_ID}/manifest.json` — version, source refs, hashes, status, inputs, expectations, and limitations.\n- `fixtures/{DATASET_ID}/` — prepared request/response payloads for `Understanding.extract`, `Events.read`, `Business.read`, `Evidence.read`, and `Graph.query`.\n- `contracts/{DATASET_ID}/` — frozen operation closures, OpenAPI component snapshot, immutable approved-fixture pointers, synthetic test-owner policy, and gap report.\n- `validation/validate.py` — offline checks using standard-library hashes, source refs, provenance, and the existing pinned Pydantic package.\n\n## Offline validation\n\nRun from repository root with the existing pinned Python environment (Python 3.12 and the workspace's Pydantic v2 installation):\n\n```powershell\n& 'C:\\Users\\Артём\\Documents\\ChatGPT\\Хакатон Альфабанк\\.venv\\Scripts\\python.exe' -B spike/_shared/validation/validate.py\n```\n\nThe validator reads the contract package and approved fixtures from this checkout. It does not access a database or network. No environment file, `.venv`, or global contract is changed. Generated text/JSON artifact hashes use LF-normalized bytes; the dataset also has a separate canonical JSON hash. The read-only approved index hashes are retained verbatim alongside portable local content hashes.\n\n## Freeze protocol\n\nVersion `1.0.1` is the active frozen provisional corpus. It supersedes the historically preserved `1.0.0` snapshot from commit `db48cd37491e8fab8a9f122ae4b100da72197a81`, whose artifact SHA checks depended on Windows checkout line endings and whose T12 inferred case did not resolve to an executable graph input. The physical dataset ID path is retained to avoid duplicating the large corpus; Git history preserves the previous files. Future changes require a new semantic version and a separately reviewed freeze. The builder refuses to overwrite by default; its only correction mode is `--supersede 1.0.0`, which first verifies that exact predecessor version.\n\nThe dataset's canonical SHA-256 is `{data_hash}`. Base commit: `{BASE_COMMIT}`. The source PDF was reviewed at pages 4–9 and is pinned by SHA-256 in the dataset manifest.\n\n## Scope and limitations\n\nThe corpus tests false merges, sparse profiles, source conflicts, exact-anchor integrity, time-bounded facts, open-world graph paths, stale/partial knowledge, and impact questions with unknowns. It contains no real company data and no model output is used to make labels. The property expectations are provisional and require independent content review before any gold use.\n\nPublisher-root/syndication groups, the explicit test-only confirmed policy, and the T12 negative-edge semantics live only in local experimental metadata because normative DTOs do not carry those semantics; see `contracts/{DATASET_ID}/COMPATIBILITY_GAPS.md`. Confirmed synthetic examples do not imply a universal reliability score or production trusted-owner policy.\n"""
    readme_path = SHARED / "README.md"
    if readme_path.exists() and not ALLOW_REPLACE_OUTPUTS:
        raise FileExistsError(readme_path)
    readme_path.write_text(readme, encoding="utf-8", newline="\n")

    print(json.dumps({"dataset_id": DATASET_ID, "canonical_data_hash": data_hash, "operation_fixtures": len(fixtures), "strict_validated": list(fixtures), "registry_operations_locked": len(lock["operations"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
