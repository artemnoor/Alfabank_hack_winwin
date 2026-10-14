"""Offline Business profile and question-selection prototype.

This module intentionally implements conservative, deterministic rules. It is
an experiment behind the Framework v1 operation DTOs, not an owner service or
an NLP model. Absence of a statement is treated as unknown, never as a
negative assertion.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from alfalab_contracts.models import (
    ApplyBusinessInput,
    ApplyBusinessOutput,
    BusinessResult,
    BusinessSnapshot,
    CodeRef,
    CommandReceipt,
    Contradiction,
    EntityRef,
    MissingDatum,
    ObjectRef,
    ProfileChangeProposal,
    ProfileInput,
    ProfileOutput,
    Provenance,
    QuestionAnswer,
    QuestionProposal,
    QuestionsInput,
    QuestionsOutput,
    ReadBusinessInput,
    ReceiptQuery,
    ReceiptResult,
    Statement,
    StatementRef,
    TextValue,
    TimeSlice,
    Validity,
)
from alfalab_contracts.semantics import validate_dto

logger = logging.getLogger(__name__)

METHOD_REF = {
    "id": "t10.conservative-rule-profile",
    "version": "0.1.0",
    "hash": "sha256:" + hashlib.sha256(b"t10-conservative-rule-profile-v0.1.0").hexdigest(),
}
QUESTION_METHOD = {
    "id": "t10.decision-impact-question-ranker",
    "version": "0.1.0",
    "hash": "sha256:" + hashlib.sha256(b"t10-decision-impact-question-ranker-v0.1.0").hexdigest(),
}
ONTOLOGY = "alfalab.business"
ONTOLOGY_VERSION = "1.0.0"


class RevisionConflict(ValueError):
    """The explicitly supplied state does not match the expected revision."""


class ConfirmationNotAuthorized(ValueError):
    """A proposed confirmed fact lacks an explicit matching owner policy."""


@dataclass(frozen=True, slots=True)
class Claim:
    predicate: str
    text: str
    epistemic_status: str = "user_declared"
    typed_value: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class FieldQuestion:
    code: str
    path: str
    predicates: frozenset[str]
    text: str
    why: str
    base_score: int
    event_scores: tuple[tuple[str, int], ...]

    def score_for(self, event_code: str | None) -> int:
        return dict(self.event_scores).get(event_code or "", self.base_score)


@dataclass(frozen=True, slots=True)
class TrustedOwnerPolicy:
    """Test-only allowlist; the operation DTO does not carry this policy ref."""

    policy_id: str
    policy_hash: str
    confirmed_statement_ids: frozenset[str]
    evidence_refs: frozenset[tuple[str, int, str]]


@dataclass(frozen=True, slots=True)
class ApplyContext:
    as_of: TimeSlice
    idempotency_key: str
    run_id: str = "t10-offline-run"
    owner_policy: TrustedOwnerPolicy | None = None


_FIELD_QUESTIONS: tuple[FieldQuestion, ...] = (
    FieldQuestion(
        "supplier_names", "/dependencies/suppliers", frozenset({"purchases_from", "supplier"}),
        "Кто сейчас поставляет компании затронутые товары или компоненты?",
        "Без текущего имени поставщика нельзя проверить прямую зависимость.", 8,
        (("export_restriction", 9), ("sanctions", 9), ("supplier_default", 10), ("tax_change", 6)),
    ),
    FieldQuestion(
        "supplier_countries", "/sourcing/countries", frozenset({"sourcing_country", "procurement_country"}),
        "Из каких стран фактически закупаются затронутые товары или компоненты?",
        "Страна закупки может изменить применимость экспортного или налогового ограничения.", 7,
        (("export_restriction", 10), ("sanctions", 8), ("tax_change", 8)),
    ),
    FieldQuestion(
        "component_identity", "/products/components", frozenset({"uses_component", "uses_material", "component"}),
        "Какие именно компоненты или материалы используются в затронутом продукте?",
        "Точное наименование компонента позволяет проверить совпадение с событием.", 7,
        (("export_restriction", 8), ("sanctions", 8), ("raw_material_price_increase", 9), ("price_forecast", 9)),
    ),
    FieldQuestion(
        "procurement_volume", "/procurement/volume", frozenset({"procurement_volume", "purchase_volume"}),
        "Каков объём закупок этого товара за указанный период и в каких единицах?",
        "Без объёма нельзя оценить материальность воздействия количественно.", 6,
        (("export_restriction", 7), ("sanctions", 7), ("raw_material_price_increase", 8)),
    ),
    FieldQuestion(
        "import_share", "/procurement/import_share", frozenset({"import_share"}),
        "Какова доля импорта в закупках этого товара?",
        "Доля импорта помогает понять возможную экспозицию, но не выводится из отрасли.", 5,
        (("export_restriction", 8), ("sanctions", 7), ("tax_change", 7)),
    ),
    FieldQuestion(
        "alternative_supplier", "/dependencies/alternative_suppliers", frozenset({"alternative_supplier", "qualified_alternative"}),
        "Есть ли квалифицированный альтернативный поставщик именно этого компонента?",
        "Поставщик другого компонента не подтверждает взаимозаменяемость.", 6,
        (("export_restriction", 8), ("sanctions", 8), ("supplier_default", 9)),
    ),
    FieldQuestion(
        "route", "/logistics/routes", frozenset({"ships_via", "passes_through", "route"}),
        "Каким маршрутом доставляется затронутый товар и через какие узлы?",
        "Маршрут нужен для проверки связи с транспортным событием.", 6,
        (("port_closure", 10), ("historical_port_closure", 8), ("facility_fire", 5)),
    ),
    FieldQuestion(
        "warehouse", "/logistics/warehouses", frozenset({"stores_at", "uses_warehouse", "warehouse_location"}),
        "На каких складах хранится затронутый товар или сырьё и к какой дате относятся сведения?",
        "Без явно названного склада нельзя проверить локальный инцидент или доступность запаса.", 6,
        (("port_closure", 8), ("historical_port_closure", 7), ("facility_fire", 9), ("production_line_stop", 7), ("supplier_default", 6)),
    ),
    FieldQuestion(
        "alternative_route", "/logistics/alternative_routes", frozenset({"alternative_route", "alternate_route"}),
        "Есть ли проверенный альтернативный маршрут для этой поставки?",
        "Известный основной маршрут не доказывает ни наличие, ни отсутствие альтернативы.", 6,
        (("port_closure", 10), ("historical_port_closure", 8)),
    ),
    FieldQuestion(
        "inventory_cover", "/inventory/cover_days", frozenset({"inventory_cover", "inventory_days", "stock_cover"}),
        "Какой актуальный запас затронутого сырья или компонента и на какую дату он рассчитан?",
        "Запас может изменить срочность, но противоречивые значения нужно сверить.", 7,
        (("port_closure", 9), ("supplier_default", 8), ("raw_material_price_increase", 7), ("price_forecast", 7)),
    ),
    FieldQuestion(
        "inventory_reconciliation", "/inventory/cover_days", frozenset({"inventory_cover", "inventory_days", "stock_cover"}),
        "Какое значение складского запаса актуально и к какой дате относится каждый показатель?",
        "В профиле есть противоречащие записи; их нельзя свести к одному числу без сверки.", 10,
        (("port_closure", 10), ("supplier_default", 9), ("raw_material_price_increase", 9)),
    ),
    FieldQuestion(
        "delivery_lead_time", "/logistics/lead_time", frozenset({"lead_time", "delivery_time"}),
        "Каков обычный и текущий срок доставки по затронутому маршруту?",
        "Срок доставки помогает оценить временной горизонт возможного перебоя.", 5,
        (("port_closure", 8), ("historical_port_closure", 6)),
    ),
    FieldQuestion(
        "procurement_quantity", "/procurement/quantity", frozenset({"procurement_quantity", "material_quantity"}),
        "Какое количество этого сырья закупается за период и в каких единицах?",
        "Без количества и периода нельзя рассчитать денежный эффект изменения цены.", 7,
        (("raw_material_price_increase", 10), ("price_forecast", 9)),
    ),
    FieldQuestion(
        "price_basis", "/procurement/price_basis", frozenset({"price_basis", "contract_price"}),
        "Как определяется закупочная цена: фиксированная, индексная или по иной формуле?",
        "Условия цены могут влиять на передачу рыночного изменения в закупки.", 6,
        (("raw_material_price_increase", 9), ("price_forecast", 8)),
    ),
    FieldQuestion(
        "substitution_flexibility", "/production/substitution", frozenset({"substitution_flexibility", "substitutes_material"}),
        "Можно ли заменить этот материал или компонент без повторной квалификации и с какими ограничениями?",
        "Заменяемость влияет на возможный механизм риска, но не следует из отрасли.", 5,
        (("raw_material_price_increase", 8), ("price_forecast", 8), ("export_restriction", 6)),
    ),
    FieldQuestion(
        "transaction_scope", "/trade/transaction_scope", frozenset({"transaction_scope", "sanction_scope"}),
        "Какие юридическое лицо, товарный код и сторона сделки относятся к затронутой поставке?",
        "Упоминание поставщика само по себе не доказывает применимость меры к сделке.", 8,
        (("sanctions", 10), ("export_restriction", 9), ("tax_change", 8)),
    ),
    FieldQuestion(
        "tax_scope", "/trade/tax_scope", frozenset({"tax_scope", "tariff_code"}),
        "Какой код товара и страна происхождения указаны в документах по этой поставке?",
        "Налоговое уведомление не устанавливает страну импорта конкретной компании.", 7,
        (("tax_change", 10),),
    ),
    FieldQuestion(
        "facility", "/operations/facilities", frozenset({"operates_at", "facility_location", "located_at"}),
        "Какая производственная площадка участвует в затронутом процессе?",
        "Площадка связывает сообщение о локальном событии с конкретной операцией.", 5,
        (("facility_fire", 10), ("production_line_stop", 9)),
    ),
    FieldQuestion(
        "business_process", "/operations/processes", frozenset({"processes", "business_process"}),
        "Какой бизнес-процесс использует затронутую систему или компонент?",
        "Это помогает определить операционную связь; один лишь киберинцидент не доказывает остановку.", 5,
        (("cyber_incident", 10), ("production_line_stop", 7), ("facility_fire", 6)),
    ),
    FieldQuestion(
        "service_dependency", "/dependencies/services", frozenset({"uses_service", "depends_on_service", "depends_on_it", "it_provider"}),
        "Какие внешние услуги или IT-сервисы нужны затронутому процессу и кто их предоставляет?",
        "Без явно названного сервиса и его роли киберинцидент нельзя переносить на компанию.", 5,
        (("cyber_incident", 10), ("production_line_stop", 6), ("facility_fire", 4)),
    ),
    FieldQuestion(
        "production_capacity", "/production/capacity", frozenset({"production_capacity", "capacity"}),
        "Какая мощность затронутой линии и какая доля выпуска проходит через неё?",
        "Описание процесса не раскрывает мощность или долю выпуска.", 5,
        (("production_line_stop", 9), ("facility_fire", 8), ("raw_material_price_increase", 5)),
    ),
    FieldQuestion(
        "forecast_materialized", "/market/forecast_status", frozenset({"forecast_materialized"}),
        "Подтвердилось ли прогнозное изменение цены фактическими котировками или закупочными документами?",
        "Прогноз нельзя считать состоявшимся изменением без последующего подтверждения.", 6,
        (("price_forecast", 10),),
    ),
    FieldQuestion(
        "investment_amount", "/investment/amount", frozenset({"investment_amount", "capital_expenditure"}),
        "Какова объявленная сумма инвестиции и где она подтверждена?",
        "Само объявление не содержит сумму, если она прямо не указана.", 4,
        (("new_investment", 8),),
    ),
    FieldQuestion(
        "commissioning_date", "/investment/commissioning_date", frozenset({"commissioning_date", "investment_timing"}),
        "Когда планируется ввод объекта или оборудования в эксплуатацию?",
        "Без срока ввода нельзя определить, когда инвестиция может изменить мощности.", 4,
        (("new_investment", 8),),
    ),
)

_EVENT_TARGETS: dict[str, frozenset[str]] = {
    "export_restriction": frozenset({"supplier_names", "supplier_countries", "component_identity", "procurement_volume", "import_share", "alternative_supplier", "transaction_scope"}),
    "sanctions": frozenset({"supplier_names", "supplier_countries", "component_identity", "procurement_volume", "import_share", "alternative_supplier", "transaction_scope"}),
    "port_closure": frozenset({"route", "alternative_route", "warehouse", "inventory_cover", "inventory_reconciliation", "delivery_lead_time"}),
    "historical_port_closure": frozenset({"route", "alternative_route", "warehouse", "inventory_cover", "inventory_reconciliation", "delivery_lead_time"}),
    "raw_material_price_increase": frozenset({"component_identity", "procurement_volume", "procurement_quantity", "price_basis", "substitution_flexibility", "inventory_cover", "inventory_reconciliation"}),
    "price_forecast": frozenset({"component_identity", "procurement_quantity", "price_basis", "substitution_flexibility", "inventory_cover", "forecast_materialized"}),
    "supplier_default": frozenset({"supplier_names", "alternative_supplier", "inventory_cover", "inventory_reconciliation", "delivery_lead_time"}),
    "tax_change": frozenset({"supplier_countries", "transaction_scope", "tax_scope", "procurement_volume", "import_share"}),
    "cyber_incident": frozenset({"service_dependency", "business_process"}),
    "production_line_stop": frozenset({"facility", "warehouse", "business_process", "production_capacity", "inventory_cover"}),
    "facility_fire": frozenset({"facility", "warehouse", "business_process", "production_capacity", "inventory_cover"}),
    "new_investment": frozenset({"investment_amount", "commissioning_date", "production_capacity"}),
}

_MISSING: tuple[tuple[str, str, str], ...] = (
    ("/dependencies/suppliers", "not_provided", "Текущие поставщики не указаны."),
    ("/sourcing/countries", "not_provided", "Страны закупок не указаны."),
    ("/procurement/volume", "not_provided", "Объём закупок не указан."),
    ("/procurement/import_share", "not_provided", "Доля импорта не указана."),
    ("/products/components", "not_provided", "Компоненты и материалы не указаны."),
    ("/operations/facilities", "not_provided", "Производственные площадки не указаны."),
    ("/logistics/routes", "not_provided", "Маршруты доставки не указаны."),
    ("/logistics/warehouses", "not_provided", "Склады, где хранятся затронутые товары или сырьё, не указаны."),
    ("/dependencies/services", "not_provided", "Зависимости от внешних услуг и IT-сервисов не указаны."),
    ("/inventory/cover_days", "not_provided", "Запас и дата его измерения не указаны."),
    ("/production/processes", "not_provided", "Бизнес-процессы не описаны."),
    ("/production/capacity", "not_provided", "Производственная мощность не указана."),
    ("/customers", "not_provided", "Покупатели не указаны."),
)

_PATH_PREDICATES: dict[str, frozenset[str]] = {
    "/dependencies/suppliers": frozenset({"purchases_from", "supplier"}),
    "/sourcing/countries": frozenset({"sourcing_country", "procurement_country"}),
    "/procurement/volume": frozenset({"procurement_volume", "purchase_volume"}),
    "/procurement/import_share": frozenset({"import_share"}),
    "/products/components": frozenset({"uses_component", "uses_material", "component"}),
    "/operations/facilities": frozenset({"operates_at", "facility_location", "located_at"}),
    "/logistics/routes": frozenset({"ships_via", "passes_through", "route"}),
    "/logistics/warehouses": frozenset({"stores_at", "uses_warehouse", "warehouse_location"}),
    "/dependencies/services": frozenset({"uses_service", "depends_on_service", "depends_on_it", "it_provider"}),
    "/inventory/cover_days": frozenset({"inventory_cover", "inventory_days", "stock_cover"}),
    "/production/processes": frozenset({"processes", "business_process"}),
    "/production/capacity": frozenset({"production_capacity", "capacity"}),
    "/customers": frozenset({"sells_to", "customer"}),
}

_EXTRACTOR_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("trades_in", re.compile(r"(?:\bмы\s+)?(?:продаю|прода[её]м|прода[её]т|торгую|торгуем|торгует|sell|trade in|distribute)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("manufactures", re.compile(r"(?:\bмы\s+)?(?:произвожу|производим|производит|выпускаю|выпускаем|выпускает|собираю|собираем|собирает|manufacture|produce|assemble)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("uses_service", re.compile(r"(?:\bмы\s+)?(?:используем|использует|пользуемся|пользуется|depends? on|rely on|use|uses)\s+(?:(?:внешн\w*|облачн\w*|IT|ИТ)\s+)*(?:сервис(?:а|ы|ом)?|услуг(?:у|ой|ами)|services?)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("stores_at", re.compile(r"(?:храним|хранится|хранятся|хранить|stored|store)\s+(?:[^.!?;\n]+?\s+)?(?:на складе|в складе|at (?:the )?warehouse)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("uses_component", re.compile(r"(?:\bмы\s+)?(?:использую|используем|использует|использовать|применяю|применяем|применяет|применять|use|uses|using|consume)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("purchases_from", re.compile(r"(?:закупаю|закупаем|закупает|закупать|покупаю|покупаем|покупает|покупать|приобретаю|приобретаем|приобретает|приобретать|buy|buys|purchase|purchases|source)\s+(?P<item>[^.!?;\n]+?)\s+(?:у|from)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("sourcing_country", re.compile(r"(?:закупаем|закупает|покупаем|покупает|закупки\s+идут)\s+(?:[^.!?;\n]+?\s+)?(?:из\s+страны|в\s+стране|из|from)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("ships_via", re.compile(r"(?:доставляем|доставляет|поставляем|поставляет|маршрут\s+ид[её]т|ship|deliver|route)\s+(?:[^.!?;\n]+?\s+)?(?:через|via|through)\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("processes", re.compile(r"(?:процесс(?:ы)?\s+(?:включает|включают|состоит\s+из)|process(?:es)?\s+(?:includes|include|involves))\s+(?P<value>[^.!?;\n]+)", re.IGNORECASE)),
    ("sells_to", re.compile(r"(?:прода[её]м|прода[её]т|поставляем|поставляет)\s+(?:[^.!?;\n]+?\s+)?(?:клиентам|покупателям)\s+(?P<value>[^.!?;\n]+)|(?:sell|supply)\s+(?P<value_en>[^.!?;\n]+?)\s+to\s+customers\s+(?P<customer>[^.!?;\n]+)", re.IGNORECASE)),
)

_HYPOTHETICAL_MARKERS = re.compile(r"\b(?:может|можем|могут|могла|могли|возможно|планирует|рассматривает|по\s+слухам|may|might|could|possibly|plans\s+to|rumou?r)\b", re.IGNORECASE)
_NEGATIVE_MARKERS = re.compile(r"\b(?:не\s+(?:продаю|продаем|продаёт|продает|торгую|торгуем|торгует|производим|производит|использую|используем|использует|применяю|применяем|закупаю|закупаем|закупает|покупаю|покупаем|покупает|приобретаю|приобретаем|приобретает)|never\s+(?:sell|trade|manufacture|produce|use|consume|buy|purchase|source)|does\s+not\s+(?:sell|trade|manufacture|produce|use|consume|buy|purchase|source)|do\s+not\s+(?:sell|trade|manufacture|produce|use|consume|buy|purchase|source)|doesn't\s+(?:sell|trade|manufacture|produce|use|consume|buy|purchase|source)|don't\s+(?:sell|trade|manufacture|produce|use|consume|buy|purchase|source))\b", re.IGNORECASE)
_NEGATIVE_WAREHOUSE_MARKERS = re.compile(r"\bне\s+(?:храним|хранится|хранятся|хранить)|\b(?:do\s+not|does\s+not|never)\s+(?:store|stores|stored)\b", re.IGNORECASE)


def _canonical_json(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")  # type: ignore[union-attr]
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _stable_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _stable_id(prefix: str, value: object) -> str:
    suffix = hashlib.sha256(_canonical_json(value)).hexdigest()[:20]
    return f"{prefix}-{suffix}"


def _enum(value: object) -> str:
    return str(getattr(value, "value", value))


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _valid_at(statement: Statement, as_of: str | TimeSlice, known_as_of: str | None = None) -> bool:
    """Apply valid-time and, when supplied, transaction-time visibility."""
    if isinstance(as_of, TimeSlice):
        valid_point = as_of.valid_as_of
        known_point = as_of.known_as_of
    else:
        valid_point = as_of
        known_point = known_as_of
    start = statement.validity.valid_from
    end = statement.validity.valid_to
    valid = _dt(valid_point)
    recorded = _dt(statement.validity.recorded_at)
    return (
        (start is None or _dt(start) <= valid)
        and (end is None or valid < _dt(end))
        and (known_point is None or recorded <= _dt(known_point))
    )


def _current_claims(
    snapshot: BusinessSnapshot | None,
    as_of: str | TimeSlice,
    known_as_of: str | None = None,
) -> list[Statement]:
    if snapshot is None:
        return []
    return [statement for statement in snapshot.statements if _valid_at(statement, as_of, known_as_of)]


def _claim_known(statement: Statement) -> bool:
    status = _enum(statement.epistemic_status)
    kind = getattr(statement.value, "kind", None)
    kind = _enum(kind) if kind is not None else ""
    return status not in {"unknown", "hypothetical", "disputed"} and kind != "unknown"


def _claim_comparable(statement: Statement) -> bool:
    """Whether a concrete assertion can participate in a scalar conflict.

    Disputed assertions must remain comparable: filtering them as “not known”
    would erase precisely the conflict that Business is expected to preserve.
    Hypotheses and explicit unknowns do not establish a competing value.
    """
    status = _enum(statement.epistemic_status)
    kind = getattr(statement.value, "kind", None)
    kind = _enum(kind) if kind is not None else ""
    return status in {"confirmed", "observed", "user_declared", "disputed"} and kind != "unknown"


def _as_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t\n,.;:—–-")
    return value[:5000]


def _extract_claims(text: str) -> list[Claim]:
    claims: list[Claim] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+|;\s*", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        status = "hypothetical" if _HYPOTHETICAL_MARKERS.search(sentence) else "user_declared"
        matched = False
        for predicate, pattern in _EXTRACTOR_RULES:
            match = pattern.search(sentence)
            if not match:
                continue
            raw = match.groupdict()
            if predicate == "purchases_from" and raw.get("item"):
                extracted = f"supplier={_as_text(raw.get('value') or '')}; item={_as_text(raw['item'])}"
            elif predicate == "sells_to" and raw.get("customer"):
                extracted = _as_text(raw["customer"])
            else:
                extracted = _as_text(raw.get("value") or raw.get("value_en") or "")
            if not extracted:
                continue
            if _NEGATIVE_MARKERS.search(sentence) or _NEGATIVE_WAREHOUSE_MARKERS.search(sentence):
                predicate = f"does_not_{predicate}"
            claims.append(Claim(predicate, extracted, status))
            matched = True
            break
        if matched:
            continue

        inventory = re.search(
            r"(?:запас(?:\s+сырья)?|остаток|inventory|stock)\s+(?:составляет|равен|is|of)?\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>дн(?:я|ей)?|days?)",
            sentence,
            re.IGNORECASE,
        )
        if inventory:
            number = inventory.group("number").replace(",", ".")
            claims.append(Claim("inventory_cover", sentence, status, {
                "kind": "number", "value": number,
                "unit": {"namespace": "units", "version": "1.0.0", "code": "day"},
            }))
            continue

        share = re.search(r"(?:доля\s+импорта|import\s+share)\s*(?:составляет|равна|is)?\s*(?P<number>\d+(?:[.,]\d+)?)\s*%", sentence, re.IGNORECASE)
        if share:
            number = share.group("number").replace(",", ".")
            claims.append(Claim("import_share", sentence, status, {
                "kind": "number", "value": number,
                "unit": {"namespace": "units", "version": "1.0.0", "code": "percent"},
            }))
    # De-duplicate claims and sort to make sentence order irrelevant.
    unique = {(claim.predicate, claim.text, claim.epistemic_status, json.dumps(claim.typed_value, sort_keys=True) if claim.typed_value else ""): claim for claim in claims}
    return sorted(unique.values(), key=lambda item: (item.predicate, item.text.casefold(), item.epistemic_status))


def _source_ref(material: object) -> dict[str, object]:
    # RawMaterial has an explicit immutable material ID and content hash but no
    # Documents revision ref. Revision 1 is a local materialized-fixture
    # convention; production owner resolution is not simulated here.
    return {
        "owner": "Documents",
        "object_id": getattr(material, "material_id"),
        "revision": 1,
        "hash": getattr(material, "content_hash"),
    }


def _provenance(origin: str, source_refs: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "origin": origin,
        "source_refs": source_refs or [],
        "input_statement_refs": [],
        "producer_run_id": None,
        "derivation_method": METHOD_REF,
        "evidence_refs": [],
        "origin_verified": False,
    }


def _answer_predicate(question_id: str) -> str | None:
    key = question_id.casefold().replace("-", "_")
    mapping = {
        "supplier": "purchases_from", "supplier_names": "purchases_from", "supplier_countries": "sourcing_country",
        "procurement_share": "import_share", "import_share": "import_share", "procurement_volume": "procurement_volume",
        "inventory_days": "inventory_cover", "inventory_cover": "inventory_cover", "route": "ships_via",
        "alternative_route": "alternative_route", "component": "uses_component", "component_identity": "uses_component",
        "warehouse": "stores_at", "warehouse_location": "warehouse_location",
        "service_dependency": "uses_service", "it_dependency": "uses_service", "service": "uses_service",
        "price_basis": "price_basis", "procurement_quantity": "procurement_quantity", "capacity": "production_capacity",
    }
    return mapping.get(key)


def _statement_for_claim(
    company: EntityRef,
    claim: Claim,
    as_of: TimeSlice,
    origin: str,
    source_refs: list[dict[str, object]] | None = None,
) -> Statement:
    value: dict[str, object] = claim.typed_value or {"kind": "text", "value": claim.text}
    stable_basis = {
        "company": company.entity_id,
        "predicate": claim.predicate,
        "value": value,
        "source_refs": source_refs or [],
        "valid_from": as_of.valid_as_of,
    }
    status = claim.epistemic_status
    if origin == "public_source" and status == "user_declared":
        status = "observed"
    return Statement.model_validate({
        "statement_id": _stable_id("t10-statement", stable_basis),
        "revision": 1,
        "subject": company.model_dump(mode="json"),
        "predicate": {"namespace": ONTOLOGY, "version": ONTOLOGY_VERSION, "code": claim.predicate},
        "value": value,
        "epistemic_status": status,
        "validity": {
            "valid_from": as_of.valid_as_of,
            "valid_to": None,
            "recorded_at": as_of.known_as_of,
        },
        "provenance": _provenance(origin, source_refs),
    })


def _answer_statements(company: EntityRef, answers: Iterable[QuestionAnswer], as_of: TimeSlice) -> tuple[list[Statement], list[MissingDatum]]:
    statements: list[Statement] = []
    missing: list[MissingDatum] = []
    for answer in answers:
        status = _enum(answer.status)
        predicate = _answer_predicate(answer.question_id)
        if status != "answered":
            # skipped/declined/unknown preserve the answer state and never
            # synthesize a Boolean false or an empty-valued fact.
            continue
        if predicate is None or answer.value is None:
            missing.append(MissingDatum(
                path=f"/answers/{answer.question_id}", reason="unsupported",
                detail="Ответ сохранён, но его вопрос не сопоставлен с экспериментальной бизнес-онтологией.",
            ))
            continue
        value = answer.value.model_dump(mode="json") if hasattr(answer.value, "model_dump") else answer.value
        claim = Claim(predicate, "explicit answer", "user_declared", value)
        statement = _statement_for_claim(company, claim, as_of, _enum(answer.provenance.origin), answer.provenance.source_refs and [ref.model_dump(mode="json") for ref in answer.provenance.source_refs] or None)
        statement = statement.model_copy(update={"provenance": answer.provenance})
        statements.append(statement)
    return statements, missing


def _fact_paths(
    statements: Sequence[Statement], as_of: str | TimeSlice, known_as_of: str | None = None
) -> set[str]:
    predicates = {
        statement.predicate.code
        for statement in statements
        if _valid_at(statement, as_of, known_as_of) and _claim_known(statement)
    }
    paths = {path for path, codes in _PATH_PREDICATES.items() if predicates & codes}
    return paths


def _contradictions_for(
    new_statements: Sequence[Statement],
    previous: Sequence[Statement],
    as_of: TimeSlice | None = None,
) -> list[Contradiction]:
    scalar_codes = {"inventory_cover", "inventory_days", "stock_cover", "import_share", "procurement_volume", "purchase_volume", "production_capacity", "capacity"}
    out: dict[tuple[str, ...], Contradiction] = {}
    pairs = [(new, old) for new in new_statements for old in previous]
    pairs.extend(
        (new_statements[left], new_statements[right])
        for left in range(len(new_statements))
        for right in range(left + 1, len(new_statements))
    )
    seen_pairs: set[tuple[str, str]] = set()
    for new, old in pairs:
        pair_key = tuple(sorted((new.statement_id, old.statement_id)))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        if new.predicate.code not in scalar_codes or not _claim_comparable(new):
            continue
        if old.predicate.code != new.predicate.code or not _claim_comparable(old):
            continue
        if old.subject.entity_id != new.subject.entity_id:
            continue
        if old.value.model_dump(mode="json") == new.value.model_dump(mode="json"):
            continue
        if not _validity_overlaps(old.validity, new.validity):
            continue
        if as_of is not None and (not _valid_at(new, as_of) or not _valid_at(old, as_of)):
            continue
        ids = tuple(sorted({old.statement_id, new.statement_id}))
        if len(ids) == 2:
            out[ids] = Contradiction(statement_ids=list(ids), reason=f"Разные значения одного измерения {new.predicate.code} относятся к пересекающемуся периоду; оба утверждения сохранены.")
    return list(out.values())


def _validity_overlaps(left: Validity, right: Validity) -> bool:
    left_start = _dt(left.valid_from) if left.valid_from else datetime.min.replace(tzinfo=timezone.utc)
    right_start = _dt(right.valid_from) if right.valid_from else datetime.min.replace(tzinfo=timezone.utc)
    left_end = _dt(left.valid_to) if left.valid_to else datetime.max.replace(tzinfo=timezone.utc)
    right_end = _dt(right.valid_to) if right.valid_to else datetime.max.replace(tzinfo=timezone.utc)
    return max(left_start, right_start) < min(left_end, right_end)


def propose_profile(profile: ProfileInput) -> ProfileOutput:
    """Extract only explicit claims from description/documents/answered inputs."""
    company_id = profile.company.entity_id
    if profile.existing is not None and profile.existing.company.entity_id != company_id:
        raise ValueError("existing profile belongs to another company")
    existing_revision = profile.existing.ref.revision if profile.existing else 0
    existing_statements = list(profile.existing.statements) if profile.existing else []
    visible_existing = _current_claims(profile.existing, profile.as_of)
    visible_ids = {item.statement_id for item in visible_existing}
    existing_contradictions = [
        item for item in (profile.existing.contradictions if profile.existing else [])
        if set(item.statement_ids) <= visible_ids
    ]

    proposed: list[Statement] = []
    for claim in _extract_claims(profile.description):
        proposed.append(_statement_for_claim(profile.company, claim, profile.as_of, "user_declared"))
    for material in profile.documents:
        for claim in _extract_claims(material.text):
            proposed.append(_statement_for_claim(profile.company, claim, profile.as_of, "public_source", [_source_ref(material)]))
    answer_statements, answer_missing = _answer_statements(profile.company, profile.answers, profile.as_of)
    proposed.extend(answer_statements)

    # Stable proposal IDs and no duplicate facts from repeated source text.
    deduped: dict[tuple[str, int], Statement] = {}
    existing_keys = {(item.statement_id, item.revision) for item in visible_existing}
    for statement in proposed:
        key = (statement.statement_id, statement.revision)
        if key not in existing_keys:
            deduped[key] = statement
    proposed = sorted(deduped.values(), key=lambda item: (item.predicate.code, item.statement_id))

    contradictions = existing_contradictions + _contradictions_for(proposed, visible_existing, profile.as_of)
    contradiction_ids = {tuple(item.statement_ids) for item in existing_contradictions}
    contradictions = [item for item in contradictions if tuple(item.statement_ids) not in contradiction_ids]
    combined = [*existing_statements, *proposed]
    resolved_paths = _fact_paths(combined, profile.as_of)
    missing_by_path: dict[str, MissingDatum] = {}
    for path, reason, detail in _MISSING:
        if path in resolved_paths:
            continue
        if any(item.path == path for item in (profile.existing.missing_data if profile.existing else [])):
            existing_item = next(item for item in profile.existing.missing_data if item.path == path)  # type: ignore[union-attr]
            missing_by_path[path] = existing_item
        else:
            missing_by_path[path] = MissingDatum(path=path, reason=reason, detail=detail)
    for item in (profile.existing.missing_data if profile.existing else []):
        if item.path not in resolved_paths:
            missing_by_path.setdefault(item.path, item)
    for item in answer_missing:
        missing_by_path[item.path] = item

    proposal = ProfileChangeProposal.model_validate({
        "proposal_id": _stable_id("t10-profile", {
            "company_id": company_id,
            "expected_revision": existing_revision,
            "as_of": profile.as_of.model_dump(mode="json"),
            "statements": [item.model_dump(mode="json") for item in proposed],
        }),
        "company": profile.company.model_dump(mode="json"),
        "expected_revision": existing_revision,
        "add_statements": [item.model_dump(mode="json") for item in proposed],
        "supersede_refs": [],
        "contradictions": [item.model_dump(mode="json") for item in contradictions],
        "missing_data": [item.model_dump(mode="json") for item in sorted(missing_by_path.values(), key=lambda item: item.path)],
        "provenance": _provenance("derived"),
    })
    for statement in proposal.add_statements:
        validate_dto(statement)
    logger.debug("profile proposal built company_id=%s new_statements=%d gaps=%d", company_id, len(proposal.add_statements), len(proposal.missing_data))
    return ProfileOutput(proposal=proposal)


def _valid_answer_ids(profile: BusinessSnapshot, history: Sequence[QuestionAnswer]) -> set[str]:
    out: set[str] = set()
    for answer in [*profile.answers, *history]:
        out.add(answer.question_id.casefold().replace("-", "_"))
    return out


def _contradicted_question_codes(profile: BusinessSnapshot, as_of: TimeSlice | None = None) -> set[str]:
    point = as_of or profile.as_of
    by_statement = {
        statement.statement_id: statement
        for statement in profile.statements
        if _valid_at(statement, point)
    }
    codes: set[str] = set()
    for contradiction in profile.contradictions:
        # A conflict is actionable only when every side is visible in this slice.
        if not set(contradiction.statement_ids) <= set(by_statement):
            continue
        for statement_id in contradiction.statement_ids:
            statement = by_statement[statement_id]
            if statement.predicate.code in {"inventory_cover", "inventory_days", "stock_cover"}:
                codes.add("inventory_reconciliation")
            elif statement.predicate.code in {"import_share", "procurement_volume", "purchase_volume"}:
                codes.add(statement.predicate.code)
    return codes


def _field_known(field: FieldQuestion, profile: BusinessSnapshot, as_of: str | TimeSlice) -> bool:
    return any(
        statement.predicate.code in field.predicates
        and _valid_at(statement, as_of)
        and _claim_known(statement)
        for statement in profile.statements
    )


def _missing_has_field(field: FieldQuestion, profile: BusinessSnapshot) -> bool:
    return any(
        missing.path == field.path
        or any(missing.path.startswith(prefix) for prefix in (field.path.rstrip("/") + "/",))
        for missing in profile.missing_data
    )


def _priority(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def propose_questions(questions: QuestionsInput) -> QuestionsOutput:
    """Rank open questions by ordinal, event-specific decision relevance.

    Scores order choices; they are neither probabilities nor information gain.
    """
    profile = questions.profile
    event_code = questions.event.event_type.code if questions.event else None
    prefs = profile.preferences
    capacity = min(questions.budget, prefs.max_questions)
    if capacity == 0:
        return QuestionsOutput(questions=[], stop_reason="budget")
    if questions.event is not None and not prefs.allow_event_prompts:
        event_code = None
    if questions.event is not None and event_code not in _EVENT_TARGETS and prefs.allow_event_prompts:
        # A sector-only/unrecognized event supplies no company-specific question
        # basis. Do not fall back to an industry proxy.
        return QuestionsOutput(questions=[], stop_reason="no_useful_question")

    relevant_codes = _EVENT_TARGETS.get(event_code) if event_code else None
    contradicted = _contradicted_question_codes(profile, profile.as_of)
    history_ids = _valid_answer_ids(profile, questions.question_history)
    suppressed = {target.casefold().replace("-", "_") for target in prefs.suppressed_targets}

    candidates: list[tuple[int, str, FieldQuestion]] = []
    declined_candidates = 0
    for field in _FIELD_QUESTIONS:
        if relevant_codes is not None and field.code not in relevant_codes:
            continue
        known = _field_known(field, profile, profile.as_of)
        conflict_question = field.code in contradicted
        if known and not conflict_question:
            continue
        # Without an event, ask only about explicitly listed gaps/contradictions.
        if relevant_codes is None and not (_missing_has_field(field, profile) or conflict_question):
            continue
        if field.code in suppressed or field.path.casefold() in suppressed:
            continue
        if field.code in history_ids:
            declined_candidates += 1
            continue
        score = field.score_for(event_code)
        if event_code and conflict_question:
            score = max(score, 10)
        candidates.append((score, field.code, field))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected = candidates[:capacity]
    out: list[QuestionProposal] = []
    for score, _, field in selected:
        why = field.why
        if event_code:
            why = f"Событие типа {event_code}: {why} Приоритет — экспериментальная порядковая эвристика, не оценка вероятности."
        out.append(QuestionProposal(
            question_id=field.code,
            target=CodeRef(namespace="alfalab.business-question", version="1.0.0", code=field.code),
            text=field.text,
            why=why,
            options=[],
            can_skip=True,
            priority=_priority(score),
        ))

    if out:
        stop_reason = "budget" if len(candidates) > len(selected) and len(selected) == capacity else "proposed"
    elif candidates:
        stop_reason = "budget"
    elif declined_candidates and not suppressed:
        stop_reason = "declined"
    else:
        stop_reason = "no_useful_question"
    logger.debug("questions ranked company_id=%s event_type=%s candidates=%d returned=%d", profile.company.entity_id, event_code, len(candidates), len(out))
    return QuestionsOutput(questions=out, stop_reason=stop_reason)


def _statement_ref(statement: Statement, aggregate: ObjectRef) -> dict[str, object]:
    return {
        "aggregate_ref": aggregate.model_dump(mode="json"),
        "statement_id": statement.statement_id,
        "revision": statement.revision,
        "hash": _stable_hash(statement.model_dump(mode="json")),
    }


def _close_superseded(statement: Statement, as_of: TimeSlice) -> Statement:
    validity = statement.validity
    valid_at = as_of.valid_as_of
    if validity.valid_from is not None and _dt(valid_at) <= _dt(validity.valid_from):
        return statement
    closed = validity.model_copy(update={"valid_to": valid_at, "recorded_at": as_of.known_as_of})
    return statement.model_copy(update={"revision": statement.revision + 1, "validity": closed})


def _answer_snapshot(existing: Sequence[QuestionAnswer], incoming: Sequence[QuestionAnswer]) -> list[QuestionAnswer]:
    # The latest state is keyed by question ID in the new snapshot. Previous
    # snapshots remain immutable in the caller's in-memory history.
    answers = {answer.question_id: answer for answer in existing}
    for answer in incoming:
        answers[answer.question_id] = answer
    return [answers[key] for key in sorted(answers)]


def _evidence_key(ref: ObjectRef) -> tuple[str, int, str]:
    return (ref.object_id, ref.revision, ref.hash)


def _check_confirmed_policy(statement: Statement, evidence: Sequence[object], policy: TrustedOwnerPolicy | None) -> None:
    if _enum(statement.epistemic_status) != "confirmed":
        return
    if policy is None or statement.statement_id not in policy.confirmed_statement_ids:
        raise ConfirmationNotAuthorized(f"confirmed statement {statement.statement_id} lacks explicit Business owner policy authorization")
    available = {_evidence_key(record.ref) for record in evidence}  # type: ignore[attr-defined]
    referenced = {_evidence_key(ref) for ref in statement.provenance.evidence_refs}
    if not referenced or not referenced <= available or not referenced <= policy.evidence_refs:
        raise ConfirmationNotAuthorized(f"confirmed statement {statement.statement_id} evidence refs are not authorized by owner policy")
    verified_anchors = {
        _evidence_key(record.ref) for record in evidence  # type: ignore[attr-defined]
        if _enum(record.verification) == "verified_anchor"
    }
    if not referenced <= verified_anchors:
        raise ConfirmationNotAuthorized(f"confirmed statement {statement.statement_id} has no matching verified source anchor")


def apply_profile(
    apply: ApplyBusinessInput,
    current: BusinessSnapshot | None,
    context: ApplyContext,
) -> ApplyBusinessOutput:
    """Apply to an isolated snapshot and return a receipt; no DB is used."""
    proposal = apply.proposal
    if current is not None:
        if current.company.entity_id != proposal.company.entity_id:
            raise ValueError("current snapshot belongs to another company")
        if current.ref.revision != proposal.expected_revision:
            raise RevisionConflict(f"expected revision {proposal.expected_revision}, found {current.ref.revision}")
    elif proposal.expected_revision != 0:
        raise RevisionConflict("new company proposal must expect revision 0")

    for statement in proposal.add_statements:
        _check_confirmed_policy(statement, apply.evidence, context.owner_policy)
        validate_dto(statement)

    revision = proposal.expected_revision + 1
    as_of = context.as_of
    old_statements = list(current.statements) if current else []
    superseded: set[tuple[str, int]] = set()
    refs_to_close: dict[tuple[str, int], Statement] = {
        (item.statement_id, item.revision): item for item in old_statements
    }
    seen_supersede_targets: set[tuple[str, int]] = set()
    for ref in proposal.supersede_refs:
        if current is None or _canonical_json(ref.aggregate_ref) != _canonical_json(current.ref):
            raise ValueError("supersede aggregate_ref does not match the current snapshot")
        key = (ref.statement_id, ref.revision)
        if key in seen_supersede_targets:
            raise ValueError("duplicate supersede reference")
        seen_supersede_targets.add(key)
        statement = refs_to_close.get(key)
        if statement is None:
            raise ValueError("proposal supersedes a statement not present in current snapshot")
        if ref.hash != _stable_hash(statement.model_dump(mode="json")):
            raise ValueError("supersede hash does not match the current statement revision")
        if statement.subject.entity_id != proposal.company.entity_id:
            raise ValueError("supersede statement belongs to another company")
        superseded.add(key)
    next_statements = [
        _close_superseded(item, as_of) if (item.statement_id, item.revision) in superseded else item
        for item in old_statements
    ]
    additions = {(item.statement_id, item.revision): item for item in proposal.add_statements}
    answer_statements, _ = _answer_statements(proposal.company, apply.answers, as_of)
    additions.update({(item.statement_id, item.revision): item for item in answer_statements})
    incoming_statements = [*proposal.add_statements, *answer_statements]
    next_statements.extend(item for key, item in additions.items() if key not in {(s.statement_id, s.revision) for s in next_statements})
    next_statements.sort(key=lambda item: (item.statement_id, item.revision))

    answers = _answer_snapshot(current.answers if current else [], apply.answers)
    preferences = apply.preferences or (current.preferences if current else None)
    if preferences is None:
        preferences = {"max_questions": 3, "allow_event_prompts": True, "suppressed_targets": []}
    else:
        preferences = preferences.model_dump(mode="json")
    contradictions = list(current.contradictions) if current else []
    by_key = {tuple(item.statement_ids): item for item in contradictions}
    by_key.update({tuple(item.statement_ids): item for item in proposal.contradictions})
    by_key.update({
        tuple(item.statement_ids): item
        for item in _contradictions_for(incoming_statements, old_statements, as_of)
    })
    missing = {item.path: item for item in (current.missing_data if current else [])}
    for item in proposal.missing_data:
        missing[item.path] = item
    resolved_paths = _fact_paths(next_statements, as_of)
    for path, reason, detail in _MISSING:
        if path in resolved_paths:
            missing.pop(path, None)
        else:
            missing.setdefault(path, MissingDatum(path=path, reason=reason, detail=detail))

    snapshot_body: dict[str, object] = {
        "company": proposal.company.model_dump(mode="json"),
        "statements": [item.model_dump(mode="json") for item in next_statements],
        "contradictions": [item.model_dump(mode="json") for item in sorted(by_key.values(), key=lambda c: tuple(c.statement_ids))],
        "missing_data": [item.model_dump(mode="json") for item in sorted(missing.values(), key=lambda item: item.path)],
        "answers": [item.model_dump(mode="json") for item in answers],
        "preferences": preferences,
        "slice": {"owner": "Business", "partition_id": proposal.company.entity_id, "revision": revision, "selection_key": "current-profile"},
        "as_of": as_of.model_dump(mode="json"),
    }
    snapshot_hash = _stable_hash(snapshot_body)
    snapshot = BusinessSnapshot.model_validate({
        "ref": {"owner": "Business", "object_id": proposal.company.entity_id, "revision": revision, "hash": snapshot_hash},
        **snapshot_body,
    })
    for statement in snapshot.statements:
        validate_dto(statement)

    receipt = CommandReceipt(
        operation_id="Business.apply",
        idempotency_key=context.idempotency_key,
        command_hash=_stable_hash(apply.model_dump(mode="json")),
        applied=True,
        changed_refs=[snapshot.ref],
        audit_id=_stable_id("t10-audit", {"company": proposal.company.entity_id, "revision": revision, "command": context.idempotency_key}),
        committed_at=as_of.known_as_of,
        original_run_id=context.run_id,
    )
    logger.debug("isolated profile apply company_id=%s revision=%d statements=%d", proposal.company.entity_id, revision, len(snapshot.statements))
    return ApplyBusinessOutput(snapshot=snapshot, receipt=receipt)


def read_profile(query: ReadBusinessInput, snapshots: Sequence[BusinessSnapshot]) -> BusinessResult | ReceiptResult:
    """Read only explicitly passed snapshots; this function has no repository."""
    selection = query.query
    if isinstance(selection, ReceiptQuery):
        return ReceiptResult(kind="receipt", receipt=None)
    if selection.revision is not None and selection.as_of is not None:
        raise ValueError("Business.read cannot combine revision and as_of")
    candidates = [snapshot for snapshot in snapshots if snapshot.company.entity_id == selection.company_id]
    if selection.revision is not None:
        candidates = [snapshot for snapshot in candidates if snapshot.ref.revision == selection.revision]
    elif selection.as_of is not None:
        candidates = [
            snapshot for snapshot in candidates
            if _dt(snapshot.as_of.valid_as_of) <= _dt(selection.as_of.valid_as_of)
            and _dt(snapshot.as_of.known_as_of) <= _dt(selection.as_of.known_as_of)
        ]
    snapshot = max(candidates, key=lambda item: item.ref.revision) if candidates else None
    logger.debug("isolated profile read company_id=%s found=%s", selection.company_id, snapshot is not None)
    return BusinessResult(kind="business", snapshot=snapshot)


def active_supplier_ids(
    profile: BusinessSnapshot,
    as_of: str | TimeSlice,
    known_as_of: str | None = None,
) -> set[str]:
    """Return only active suppliers visible by the requested transaction time.

    The string form is retained for earlier experiments and uses the snapshot's
    known_as_of unless an explicit known_as_of is passed.
    """
    point: str | TimeSlice = as_of
    if isinstance(as_of, str):
        point = TimeSlice(valid_as_of=as_of, known_as_of=known_as_of or profile.as_of.known_as_of)
    found: set[str] = set()
    for statement in profile.statements:
        if statement.predicate.code != "purchases_from" or not _valid_at(statement, point) or not _claim_known(statement):
            continue
        value = statement.value
        if getattr(value, "kind", None) == "entity":
            found.add(value.value.entity_id)
    return found
