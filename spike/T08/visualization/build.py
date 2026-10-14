"""Build the standalone, offline T08 Jev exploration page from pinned sources."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPIKE_DIR = HERE.parent
sys.path.insert(0, str(SPIKE_DIR))

from jev_spike import load_verified_inputs  # noqa: E402
from policy_v2 import compare_policies  # noqa: E402
from quality_analysis import build_quality_analysis  # noqa: E402
from quality_policy import historical_review_reasons  # noqa: E402

CORPUS_PATH = SPIKE_DIR / "corpus.json"
TAXONOMY_PATH = SPIKE_DIR / "taxonomy.json"
AGGREGATE_PATH = SPIKE_DIR / "results" / "jev-live-aggregate-20261014-v4.json"
HUMAN_PACKET_PATH = SPIKE_DIR / "HUMAN_REVIEW_PACKET.md"
CSS_PATH = HERE / "style.css"
JS_PATH = HERE / "app.js"
OUTPUT_PATH = HERE / "index.html"
POLICY_REPORT_PATH = HERE / "policy-v2-results.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_result(row: dict[str, Any]) -> dict[str, Any]:
    """Embed only result fields actually needed by this local UI."""
    required = (
        "case_id",
        "topic",
        "topic_confidence",
        "topic_probabilities",
        "event_scores",
        "unlisted_event_score",
        "uncertainty_score",
        "predicted_events",
        "classification_status",
        "model_version",
    )
    result = {key: row[key] for key in required}
    if "elapsed_ms" in row:
        result["elapsed_ms"] = row["elapsed_ms"]
    return result


def disputed_ids(cases: list[dict[str, Any]]) -> list[str]:
    text = HUMAN_PACKET_PATH.read_text(encoding="utf-8")
    short_ids = set(re.findall(r"\be\d{2}\b", text))
    return sorted(
        case["id"]
        for case in cases
        if any(
            case["id"] == short_id or case["id"].startswith(f"{short_id}-")
            for short_id in short_ids
        )
    )


def build_payload() -> dict[str, Any]:
    taxonomy, corpus, validated_cases = load_verified_inputs()
    # This routine independently reproduces the pinned pilot aggregate and
    # raises if the saved corpus, taxonomy, or recorded metrics drift.
    quality = build_quality_analysis()
    aggregate = json.loads(AGGREGATE_PATH.read_text(encoding="utf-8"))
    raw_cases = corpus["cases"]
    results = aggregate.get("results")
    if not isinstance(results, list):
        raise TypeError("Pinned Jev aggregate is missing its results list")
    by_id = {row.get("case_id"): row for row in results}
    if len(by_id) != len(results) or len(results) != 45:
        raise ValueError("Expected 45 unique saved Jev results")
    if (
        len(raw_cases) != 50
        or sum(bool(row.get("text", "").strip()) for row in validated_cases) != 49
    ):
        raise ValueError(
            "Pinned corpus no longer has 50 cases and 49 non-empty examples"
        )
    unknown = set(by_id) - {row["id"] for row in raw_cases}
    if unknown:
        raise ValueError(f"Aggregate contains unknown case ids: {sorted(unknown)}")
    missing = [
        row["id"]
        for row in raw_cases
        if row.get("text", "").strip() and row["id"] not in by_id
    ]
    if missing != aggregate.get("missing_result_case_ids") or len(missing) != 4:
        raise ValueError(
            "Saved result omissions do not match the pinned aggregate manifest"
        )

    rows = []
    for case in raw_cases:
        row = dict(case)
        saved = by_id.get(case["id"])
        row["result"] = compact_result(saved) if saved else None
        rows.append(row)

    # Policy v2.1 is an additional interpretation of the pinned responses. The
    # Legacy output below is limited to cases that pass its historical gates;
    # it is intentionally different from the historical all-score metrics.
    legacy_predictions: dict[str, set[str]] = {}
    legacy_review_ids: set[str] = set()
    event_codes = [event["code"] for event in taxonomy["events"]]
    positive_cutoff = taxonomy["thresholds"]["noul_positive_at_or_above"]
    for case in rows:
        saved = case["result"]
        if saved is None:
            continue
        legacy_decision = historical_review_reasons(saved, taxonomy)
        if any(legacy_decision["active"].values()):
            legacy_review_ids.add(case["id"])
            continue
        legacy_predictions[case["id"]] = {
            code
            for code in event_codes
            if saved["event_scores"][code] >= positive_cutoff
        }
    policy_v2 = compare_policies(
        rows,
        taxonomy,
        legacy_predictions=legacy_predictions,
        legacy_review_ids=legacy_review_ids,
    )

    legacy = quality["reproduction"]["legacy_metrics"]
    if legacy["case_count"] != 50 or legacy["non_empty_case_total"] != 49:
        raise ValueError("Reproduced legacy metrics do not describe the pinned corpus")
    if legacy["topic_correct"] != 31 or legacy["topic_total"] != 45:
        raise ValueError("Reproduced topic regression reference changed")
    if not (
        round(legacy["event_micro_precision"], 4) == round(34 / 40, 4)
        and round(legacy["event_micro_recall"], 4) == round(34 / 41, 4)
        and round(legacy["event_micro_f1"], 4) == round(68 / 81, 4)
    ):
        raise ValueError("Reproduced event regression reference changed")
    if legacy["event_exact_match_count"] != 34 or legacy["review_count"] != 42:
        raise ValueError("Reproduced regression counts changed")

    return {
        "meta": {
            "corpusId": corpus["corpus_id"],
            "corpusVersion": corpus["version"],
            "corpusHash": sha256(CORPUS_PATH),
            "taxonomyHash": sha256(TAXONOMY_PATH),
            "aggregateFile": AGGREGATE_PATH.name,
            "aggregateHash": sha256(AGGREGATE_PATH),
            "aggregateTimestamp": aggregate["timestamp_utc"],
            "taxonomyVersion": taxonomy["version"],
            "modelVersion": aggregate["model_version"],
            "resultCount": len(results),
            "nonEmptyCount": sum(
                bool(row.get("text", "").strip()) for row in validated_cases
            ),
            "missingIds": missing,
            "legacyMetrics": legacy,
            "policies": quality["policies"],
            "noNewApiCalls": True,
            "policyV2": policy_v2,
        },
        "taxonomy": {
            "id": taxonomy["id"],
            "version": taxonomy["version"],
            "other_code": taxonomy["other_code"],
            "topics": taxonomy["topics"],
            "events": taxonomy["events"],
            "thresholds": taxonomy["thresholds"],
        },
        "disputedCaseIds": disputed_ids(raw_cases),
        "cases": rows,
    }


def render_html(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # JSON is embedded in a script data block. Escaping '<' prevents a news
    # string containing a closing script token from ending that block.
    encoded = (
        encoded.replace("<", "\\u003c")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    css = CSS_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
  <meta name="color-scheme" content="dark">
  <title>Лаборатория Jev · T08</title>
  <style>
{css}
  </style>
</head>
<body>
  <a class="skip-link" href="#mainContent">Перейти к содержанию</a>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><div class="brand-mark" aria-hidden="true">A</div><div><div class="eyebrow">ALFA FUTURE HACK · T08</div><div class="brand-name">Jev Classification Lab</div></div></div>
      <div class="topbar-note"><span class="live-dot" aria-hidden="true"></span><span>Локальная песочница · без сети</span><span id="resultCountBadge" class="pill"></span></div>
    </header>
    <main id="mainContent" tabindex="-1">
    <section class="hero">
      <div><div class="eyebrow">Экспериментальная аналитика</div><h1>Как Jev читает новости</h1><p>Изучайте сохранённые ответы, сравнивайте их с предварительной разметкой и меняйте пороги. Все пересчёты происходят локально и не запускают модель повторно.</p></div>
      <div class="hero-stamp"><span class="pill red">НЕ PRODUCTION</span><span id="versionBadge" class="pill">tax. 0.3.0-spike</span></div>
    </section>
    <div id="topMetrics" class="metric-strip" aria-label="Краткие метрики"></div>
    <div class="notice"><span class="notice-icon" aria-hidden="true">!</span><div><strong>Предварительная оценка.</strong> Использованы только 45 сохранённых ответов Jev на синтетические новости. Gold-метки — черновые; оценки Jev не являются калиброванными вероятностями. Песочница не отправляет запросы и не делает выводов о реальном новостном потоке.</div></div>
    <div class="section-nav" role="group" aria-label="Экран"><button id="labTab" class="tab" type="button" data-tab="lab" aria-controls="labScreen" aria-pressed="true">Разбор новостей</button><button id="statsTab" class="tab" type="button" data-tab="stats" aria-controls="statsScreen" aria-pressed="false">Общая статистика</button></div>
    <section class="policy-bar" aria-label="Экспериментальные пороги">
      <div class="policy-top"><div><div id="policyName" class="policy-title">A · Current Strict</div><div id="policyCaption" class="policy-caption"></div></div><button id="resetThresholds" class="reset-button" type="button">Вернуть исходные пороги</button></div>
      <div class="mode-row"><div><div class="mode-label">Способ обработки результата</div><div class="mode-help">Переключает только локальные правила; Jev не запускается повторно.</div></div><div class="mode-switch" role="group" aria-label="Режим политики"><button type="button" class="mode-button active" data-policy-mode="legacy" aria-pressed="true">Legacy · всё вместе</button><button type="button" class="mode-button" data-policy-mode="policy_v2" aria-pressed="false">Policy v2.1 · отдельно по сигналам</button></div></div>
      <div id="legacyPresetNote" class="preset-note" hidden>Режимы A–E применяются только к Legacy. В Policy v2.1 используются общие числовые пороги выше.</div>
      <div id="presetButtons" class="preset-row" aria-label="Готовые диагностические режимы"></div>
      <details class="threshold-details"><summary>Настроить пороги вручную</summary>
        <div class="threshold-grid">
          <div class="threshold-control"><label for="threshold-choice">Минимум Choice <output id="value-choice">0.50</output></label><input id="threshold-choice" type="range" min="0" max="1" step="0.01" value="0.50"></div>
          <div class="threshold-control"><label for="threshold-negative">Noul: отрицательный до <output id="value-negative">0.20</output></label><input id="threshold-negative" type="range" min="0" max="0.79" step="0.01" value="0.20"></div>
          <div class="threshold-control"><label for="threshold-positive">Noul: положительный от <output id="value-positive">0.80</output></label><input id="threshold-positive" type="range" min="0.21" max="1" step="0.01" value="0.80"></div>
          <div class="threshold-control"><label for="threshold-uncertainty">Review: мало доказательств <output id="value-uncertainty">0.20</output></label><input id="threshold-uncertainty" type="range" min="0" max="1" step="0.01" value="0.20"></div>
          <div class="threshold-control"><label for="threshold-unlisted">Review: событие вне списка <output id="value-unlisted">0.20</output></label><input id="threshold-unlisted" type="range" min="0" max="1" step="0.01" value="0.20"></div>
        </div>
        <div id="thresholdHelp" class="threshold-help">Noul: score ≤ отрицательного порога → negative; score ≥ положительного → positive; между ними → abstain. Порог Choice принимает значение на границе. Сигналы review срабатывают только при score строго выше порога.</div>
      </details>
    </section>
    <section id="labScreen" class="lab-screen" aria-labelledby="labScreenTitle">
      <h2 id="labScreenTitle" class="sr-only">Разбор новостей</h2>
      <div id="labGrid" class="lab-grid">
        <aside id="caseSidebar" class="panel case-sidebar" aria-label="Список новостей">
          <div class="panel-head"><div><h3 class="panel-title">Новости корпуса</h3><div class="panel-subtitle">Выберите пример для разбора</div></div><span id="visibleCaseCount" class="case-count" role="status" aria-live="polite" aria-atomic="true"></span></div>
          <div class="sidebar-tools">
            <input id="filterSearch" class="field" type="search" placeholder="Поиск по тексту или ID" aria-label="Поиск по новостям">
            <div class="filter-grid"><select id="filterTopic" class="field" aria-label="Фильтр по теме"></select><select id="filterEvent" class="field" aria-label="Фильтр по событию"></select></div>
            <div class="filter-grid"><select id="filterState" class="field" aria-label="Фильтр по состоянию"><option value="all">Все новости</option><option value="review">Нужна проверка</option><option value="auto">Приняты порогами</option><option value="error">Есть расхождения</option><option value="clean">Без расхождений</option><option value="missing">Нет ответа Jev</option><option value="disputed">Gold на ревью</option><option value="unlisted">Сигнал вне списка</option><option value="evidence">Недостаточно доказательств</option><option value="empty">Пустой текст</option></select><select id="filterSort" class="field" aria-label="Сортировка"><option value="source">Исходный порядок</option><option value="confidence_low">Сначала низкий Choice</option><option value="events_high">Больше сохранённых событий</option><option value="review_first">Сначала ручная проверка</option><option value="errors_first">Сначала расхождения</option></select></div>
          </div>
          <div id="caseList" class="case-list"></div>
        </aside>
        <section id="detailPanel" class="panel detail-panel" aria-labelledby="detailPanelTitle"><div class="panel-head"><div><h3 id="detailPanelTitle" class="panel-title">Разбор выбранной новости</h3><div class="panel-subtitle">Ответ модели отдельно от правил приложения</div></div></div><div id="detailBody" class="panel-body"></div></section>
        <aside id="goldPanel" class="panel gold-panel" aria-labelledby="goldPanelTitle"><div class="panel-head"><div><h3 id="goldPanelTitle" class="panel-title">Сверка с разметкой</h3><div class="panel-subtitle">Метки — предварительные, не утверждены человеком</div></div></div><div id="comparisonBody" class="panel-body"></div></aside>
      </div>
    </section>
    <section id="statsScreen" class="stats-screen" aria-labelledby="statsScreenTitle" hidden>
      <h2 id="statsScreenTitle" class="sr-only">Общая статистика</h2>
      <div id="statsMetrics" class="metric-strip" aria-label="Интерактивные метрики"></div>
      <div id="policyComparison"></div>
      <div class="charts-grid" id="chartsGrid"></div>
      <div id="statsFootnote" class="warning-foot"></div>
    </section>
    </main>
  </div>
  <script id="visual-data" type="application/json">{encoded}</script>
  <script>
{js}
  </script>
</body>
</html>
"""


def main() -> int:
    payload = build_payload()
    OUTPUT_PATH.write_text(render_html(payload), encoding="utf-8", newline="\n")
    report = {
        "schema_version": "t08-policy-v2-offline-report-v1",
        "policy_version": payload["meta"]["policyV2"]["policy_version"],
        "generated_from_saved_outputs_only": True,
        "new_jev_api_requests": 0,
        "source_hashes": {
            "corpus": payload["meta"]["corpusHash"],
            "taxonomy": payload["meta"]["taxonomyHash"],
            "aggregate": payload["meta"]["aggregateHash"],
        },
        "preliminary_gold_is_not_human_approved": True,
        "policy_comparison": payload["meta"]["policyV2"],
    }
    POLICY_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"HTML={OUTPUT_PATH}")
    print(
        f"CASES={len(payload['cases'])} RESULTS={payload['meta']['resultCount']} MISSING={len(payload['meta']['missingIds'])}"
    )
    print(f"CORPUS_SHA256={payload['meta']['corpusHash']}")
    print(f"TAXONOMY_SHA256={payload['meta']['taxonomyHash']}")
    print(f"AGGREGATE_SHA256={payload['meta']['aggregateHash']}")
    print(f"POLICY_V2_REPORT={POLICY_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
