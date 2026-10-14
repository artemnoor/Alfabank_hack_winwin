from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import (  # noqa: E402
    AGGREGATE_PATH,
    CORPUS_PATH,
    OUTPUT_PATH,
    POLICY_REPORT_PATH,
    TAXONOMY_PATH,
    build_payload,
    render_html,
)


class VisualizationDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build_payload()

    def test_all_corpus_rows_are_present_with_only_saved_results(self) -> None:
        self.assertEqual(len(self.payload["cases"]), 50)
        self.assertEqual(
            sum(bool(row["text"].strip()) for row in self.payload["cases"]), 49
        )
        observed = [row for row in self.payload["cases"] if row["result"]]
        self.assertEqual(len(observed), 45)
        self.assertEqual(
            self.payload["meta"]["missingIds"],
            [
                "e23-recall-battery",
                "e35-multi-labor-investment",
                "e41-uncertain-sanctions-talk",
                "e43-uncertain-vague-delivery",
            ],
        )
        self.assertEqual(
            sum(not row["text"].strip() for row in self.payload["cases"]), 1
        )

    def test_reference_hashes_match_the_unchanged_source_files(self) -> None:
        self.assertEqual(
            self.payload["meta"]["corpusHash"],
            "592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d7",
        )
        self.assertEqual(
            self.payload["meta"]["taxonomyHash"],
            "855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d",
        )
        self.assertEqual(
            self.payload["meta"]["aggregateHash"],
            "a5e95d2367cbe81fa62665e7ef42b201316136c6c08dbac23c35798996e82286",
        )
        self.assertTrue(
            CORPUS_PATH.is_file()
            and TAXONOMY_PATH.is_file()
            and AGGREGATE_PATH.is_file()
        )

    def test_historical_regression_values_are_reproduced_by_python_reference(
        self,
    ) -> None:
        reference = self.payload["meta"]["legacyMetrics"]
        self.assertEqual(reference["topic_correct"], 31)
        self.assertEqual(reference["topic_total"], 45)
        self.assertEqual(reference["event_exact_match_count"], 34)
        self.assertEqual(reference["review_count"], 42)
        self.assertAlmostEqual(reference["event_micro_f1"], 0.8395, places=4)
        policies = {row["policy_id"]: row for row in self.payload["meta"]["policies"]}
        self.assertEqual(policies["current_strict"]["accepted_case_count"], 3)
        self.assertEqual(policies["choice_only"]["accepted_case_count"], 40)

    def test_html_is_standalone_and_escapes_script_terminators(self) -> None:
        html = render_html(self.payload)
        low = html.lower()
        self.assertNotIn("<script src=", low)
        self.assertNotIn('<link rel="stylesheet"', low)
        self.assertIn("connect-src 'none'", html)
        self.assertNotIn(
            "</script>",
            html.split('id="visual-data" type="application/json">', 1)[1]
            .split("</script>", 1)[0]
            .lower(),
        )
        self.assertNotIn("innerHTML", (HERE / "app.js").read_text(encoding="utf-8"))
        self.assertNotIn("fetch(", (HERE / "app.js").read_text(encoding="utf-8"))
        self.assertIn('type="application/json"', html)

    def test_untrusted_news_text_cannot_break_the_embedded_data_block(self) -> None:
        modified = copy.deepcopy(self.payload)
        modified["cases"][0]["text"] = '</script><img src=x onerror="alert(1)">'
        html = render_html(modified)
        data_block = html.split('id="visual-data" type="application/json">', 1)[
            1
        ].split("</script>", 1)[0]
        self.assertIn("\\u003c/script>", data_block)
        self.assertNotIn("<img src=x", html)

    def test_generated_page_matches_current_source(self) -> None:
        self.assertTrue(
            OUTPUT_PATH.exists(), "run build.py before this regression test"
        )
        self.assertEqual(
            OUTPUT_PATH.read_text(encoding="utf-8"), render_html(self.payload)
        )

    def test_policy_v2_report_is_generated_from_the_same_pinned_sources(self) -> None:
        self.assertTrue(
            POLICY_REPORT_PATH.is_file(), "run build.py before this regression test"
        )
        report = json.loads(POLICY_REPORT_PATH.read_text(encoding="utf-8"))
        self.assertTrue(report["generated_from_saved_outputs_only"])
        self.assertEqual(report["new_jev_api_requests"], 0)
        self.assertEqual(
            report["source_hashes"]["corpus"], self.payload["meta"]["corpusHash"]
        )
        self.assertEqual(
            report["source_hashes"]["taxonomy"], self.payload["meta"]["taxonomyHash"]
        )
        self.assertEqual(
            report["source_hashes"]["aggregate"], self.payload["meta"]["aggregateHash"]
        )
        self.assertEqual(report["policy_comparison"], self.payload["meta"]["policyV2"])


class BrowserAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - optional test environment
            raise unittest.SkipTest(f"Playwright not installed: {exc}") from exc
        cls.sync_playwright = staticmethod(sync_playwright)
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google/Chrome/Application/chrome.exe",
        ]
        cls.chrome = next((path for path in candidates if path.exists()), None)
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome executable is not installed")

    def test_policy_v2_statistics_charts_follow_candidates_thresholds_and_gold_edits(
        self,
    ) -> None:
        from policy_v2 import evaluate_case

        payload = build_payload()
        observed = [row for row in payload["cases"] if row["result"]]
        events = payload["taxonomy"]["events"]
        event_order = [event["code"] for event in events]
        event_labels = {event["code"]: event["label"] for event in events}
        recorded = payload["meta"]["policyV2"]["policy_v2"]["cases"]

        def expected_chart_rows(decisions, gold_overrides=None):
            overrides = gold_overrides or {}
            predictions = {
                row["id"]: set(decisions[row["id"]]["candidate_codes"])
                for row in observed
            }
            distribution = Counter(
                code
                for candidate_codes in predictions.values()
                for code in candidate_codes
            )
            errors = {code: [0, 0] for code in event_order}
            for row in observed:
                gold = set(overrides.get(row["id"], row["expected_events"]))
                predicted = predictions[row["id"]]
                for code in predicted - gold:
                    errors[code][0] += 1
                for code in gold - predicted:
                    errors[code][1] += 1
            distribution_rows = sorted(
                (
                    (event_labels[code], distribution[code])
                    for code in event_order
                    if distribution[code]
                ),
                key=lambda item: -item[1],
            )
            error_rows = sorted(
                (
                    (event_labels[code], fp, fn)
                    for code, (fp, fn) in errors.items()
                    if fp + fn
                ),
                key=lambda item: -(item[1] + item[2]),
            )[:10]
            return distribution_rows, error_rows

        expected_distribution, expected_errors = expected_chart_rows(recorded)
        external_requests: list[str] = []
        page_errors: list[str] = []
        with self.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(self.chrome),
                args=["--no-sandbox"],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on(
                "request",
                lambda request: external_requests.append(request.url)
                if request.url.startswith(("http:", "https:"))
                else None,
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(OUTPUT_PATH.resolve().as_uri(), wait_until="load")
            page.locator('[data-policy-mode="policy_v2"]').click()
            page.locator("#statsTab").click()
            self.assertIn(
                "Новости с кандидатами",
                page.locator("#topMetrics .metric-label").all_inner_texts(),
            )

            charts = page.locator("#chartsGrid .chart-card")
            candidate_chart = charts.nth(1)
            error_chart = charts.nth(2)
            self.assertIn(
                "События-кандидаты для передачи · Policy v2.1",
                candidate_chart.inner_text(),
            )
            self.assertIn("Кандидат не подтверждает факт", candidate_chart.inner_text())
            self.assertIn(
                "Лишние и пропущенные события · Policy v2.1", error_chart.inner_text()
            )
            metric_labels = page.locator(
                "#statsMetrics .metric-label"
            ).all_inner_texts()
            self.assertIn("Точность событий-кандидатов", metric_labels)
            self.assertIn("Ожидаемые события переданы дальше", metric_labels)
            self.assertIn("Лишние события-кандидаты", metric_labels)
            self.assertIn("Поводы для проверки", metric_labels)
            comparison_headers = page.locator(
                "#policyComparison thead th"
            ).all_inner_texts()
            self.assertIn("Совпало / лишнее / не передано", comparison_headers)
            self.assertNotIn("Stories с review", comparison_headers)
            self.assertIn(
                "Точность: какая доля переданных событий совпала",
                page.locator("#policyComparison").inner_text(),
            )
            self.assertIn(
                "удержанные правилами события сюда не входят",
                page.locator("#policyComparison").inner_text(),
            )
            self.assertEqual(
                list(
                    zip(
                        candidate_chart.locator(
                            ".chart-row .bar-label"
                        ).all_inner_texts(),
                        [
                            int(value)
                            for value in candidate_chart.locator(
                                ".chart-row .chart-num"
                            ).all_inner_texts()
                        ],
                    )
                ),
                expected_distribution,
            )
            self.assertEqual(
                [
                    (label, *map(int, value.split("/")))
                    for label, value in zip(
                        error_chart.locator(".chart-row .bar-label").all_inner_texts(),
                        error_chart.locator(".chart-row .chart-num").all_inner_texts(),
                    )
                ],
                expected_errors,
            )

            # A proposed label edit must immediately alter the active v2 FP/FN chart.
            page.locator("#labTab").click()
            page.locator("#filterSearch").fill("e01-supply-rail")
            page.locator("#caseList .case-card").click()
            page.locator("#comparisonBody details.edit-gold summary").click()
            page.locator(
                '#comparisonBody .event-check input[value="supply_chain_disruption"]'
            ).uncheck(force=True)
            page.locator("#statsTab").click()
            supply_row = (
                page.locator("#chartsGrid .chart-card")
                .nth(2)
                .locator(".chart-row")
                .filter(has_text=event_labels["supply_chain_disruption"])
            )
            self.assertEqual(supply_row.locator(".chart-num").inner_text(), "1/0")

            # The slider changes the chart locally; compare it with an independent Python
            # evaluation over the same saved Jev scores at the selected cutoff.
            page.locator("#labTab").click()
            page.locator("#comparisonBody button.secondary-button").filter(
                has_text="Отменить"
            ).click()
            page.locator("#threshold-positive").evaluate(
                "el => { el.value = '0.95'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            page.locator("#statsTab").click()
            adjusted = {
                row["id"]: evaluate_case(row, payload["taxonomy"], positive_cutoff=0.95)
                for row in observed
            }
            adjusted_distribution, _ = expected_chart_rows(adjusted)
            actual_adjusted = list(
                zip(
                    page.locator("#chartsGrid .chart-card")
                    .nth(1)
                    .locator(".chart-row .bar-label")
                    .all_inner_texts(),
                    [
                        int(value)
                        for value in page.locator("#chartsGrid .chart-card")
                        .nth(1)
                        .locator(".chart-row .chart-num")
                        .all_inner_texts()
                    ],
                )
            )
            self.assertEqual(actual_adjusted, adjusted_distribution)
            self.assertEqual(
                sum(value for _, value in actual_adjusted),
                sum(len(row["candidate_codes"]) for row in adjusted.values()),
            )
            browser.close()
        self.assertEqual(external_requests, [])
        self.assertEqual(page_errors, [])

    def test_browser_scenarios_and_responsive_screenshots(self) -> None:
        screenshots = HERE / "screenshots"
        screenshots.mkdir(exist_ok=True)
        external_requests: list[str] = []
        page_errors: list[str] = []
        with self.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(self.chrome),
                args=["--no-sandbox"],
            )
            page = browser.new_page(
                viewport={"width": 1440, "height": 1050}, device_scale_factor=1
            )
            page.on(
                "request",
                lambda request: (
                    external_requests.append(request.url)
                    if request.url.startswith(("http:", "https:"))
                    else None
                ),
            )
            page.on(
                "pageerror", lambda error: page_errors.append(f"{error}\n{error.stack}")
            )
            page.goto(OUTPUT_PATH.resolve().as_uri(), wait_until="load")

            self.assertEqual(page.title(), "Лаборатория Jev · T08")
            self.assertEqual(page.locator("#caseList .case-card").count(), 50)
            self.assertEqual(page.locator("#detailBody .event-item").count(), 15)
            self.assertIn("31/45", page.locator("#topMetrics").inner_text())
            self.assertIn("84.0%", page.locator("#topMetrics").inner_text())
            self.assertIn("3/45", page.locator("#topMetrics").inner_text())
            page.screenshot(path=str(screenshots / "lab-desktop.png"), full_page=True)

            # Legacy score cards use raw Noul threshold labels, while the
            # comparison row measures only outputs that passed whole-story review.
            page.locator("#statsTab").click()
            raw_score_card = page.locator("#statsMetrics .metric").filter(
                has_text="Баланс по оценкам Noul"
            )
            self.assertIn("84.0%", raw_score_card.inner_text())
            strict_delivery_row = page.locator(
                "#policyComparison .policy-v2-table tbody tr"
            ).first
            self.assertIn("9.1%", strict_delivery_row.inner_text())
            self.assertIn(
                "до блокировки новости", page.locator("#statsFootnote").inner_text()
            )
            page.locator("#labTab").click()

            # The comparison table is pinned to Legacy Current Strict even if
            # the user last selected a relaxed Legacy preset before v2.
            page.locator('[data-preset="ignore_unlisted_gate"]').click()

            # Policy v2.1 is a browser-only alternate policy over the exact same
            # 45 saved results. Event abstain is retained without review; the
            # evidence and unlisted gates have independent 0.8 cutoffs.
            page.locator('[data-policy-mode="policy_v2"]').click()
            self.assertIn("Policy v2.1", page.locator("#policyName").inner_text())
            self.assertIn(
                "Policy v2.1",
                page.locator('[data-policy-mode="policy_v2"]').inner_text(),
            )
            self.assertTrue(page.locator("#presetButtons").is_hidden())
            page.locator(".threshold-details summary").click()
            page.locator("#filterSearch").fill("e01-supply-rail")
            page.locator("#caseList .case-card").click()
            supply_event = page.locator("#detailBody .event-item").filter(
                has_text="Сбой поставок"
            )
            supply_event.locator("summary").click()
            self.assertIn("Кандидат для следующего этапа", supply_event.inner_text())
            production_event = page.locator("#detailBody .event-item").filter(
                has_text="Операционный сбой производства"
            )
            production_event.locator("summary").click()
            self.assertIn(
                "не блокирует другие категории", production_event.inner_text()
            )
            self.assertIn(
                "событие вне списка", page.locator("#detailBody").inner_text().lower()
            )
            self.assertIn(
                "1 event-кандидат(а) доступны для передачи",
                page.locator("#detailBody").inner_text(),
            )
            self.assertIn("Оценка сохранена как abstain", production_event.inner_text())
            self.assertIn("не создаёт проверку", production_event.inner_text())
            self.assertIn(
                "не блокируют передачу event-кандидатов",
                page.locator("#detailBody").inner_text(),
            )
            self.assertTrue(page.locator("#threshold-negative").is_visible())
            self.assertTrue(page.locator("#threshold-choice").is_hidden())

            # Unlisted score reaching 0.53 creates a separate task while the
            # known supply-chain candidate remains available.
            page.locator("#threshold-unlisted").evaluate(
                "el => { el.value = '0.53'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            self.assertIn(
                "отдельная задача проверки", page.locator("#detailBody").inner_text()
            )
            self.assertEqual(
                page.locator("#detailBody .event-item")
                .filter(has_text="Сбой поставок")
                .locator(".candidate-routing.candidate")
                .count(),
                1,
            )
            page.locator("#resetThresholds").click()
            page.screenshot(path=str(screenshots / "policy-v2-e01.png"), full_page=True)

            # An actual saved answer with Choice confidence below the Legacy
            # cutoff still passes its independent positive event candidate.
            page.locator("#filterSearch").fill("e06-production-fire")
            page.locator("#caseList .case-card").click()
            self.assertIn("confidence 0.47", page.locator("#detailBody").inner_text())
            low_choice_candidate = page.locator("#detailBody .event-item").filter(
                has_text="Операционный сбой производства"
            )
            low_choice_candidate.locator("summary").click()
            self.assertEqual(
                low_choice_candidate.locator(".candidate-routing.candidate").count(),
                1,
            )

            page.locator("#filterSearch").fill("e04-shortage-ports")
            page.locator("#caseList .case-card").click()
            positive_score = page.locator(
                "#detailBody .event-item .state-chip.positive"
            ).first
            candidate_event = positive_score.locator("xpath=../..")
            candidate_event.locator("summary").click()
            self.assertEqual(
                candidate_event.locator(".candidate-routing.candidate").count(), 1
            )
            self.assertIn("Кандидат для следующего этапа", candidate_event.inner_text())
            page.locator("#threshold-uncertainty").evaluate(
                "el => { el.value = '0.26'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            self.assertEqual(
                page.locator(
                    "#detailBody .event-item .candidate-routing.blocked"
                ).count(),
                1,
            )
            self.assertIn(
                "удержаны для проверки", page.locator("#detailBody").inner_text()
            )
            page.locator("#resetThresholds").click()

            page.locator("#statsTab").click()
            comparison = page.locator("#policyComparison")
            self.assertIn("Policy v2.1", comparison.inner_text())
            legacy_row = comparison.locator(".policy-v2-table tbody tr").first
            self.assertIn("Старые правила · строгий режим", legacy_row.inner_text())
            self.assertIn("2 / 1 / 39", legacy_row.inner_text())
            self.assertIn("32/45 новостей", comparison.inner_text())
            self.assertIn("34 / 6 / 7", comparison.inner_text())
            self.assertIn("e03-shortage-cells", comparison.inner_text())
            self.assertIn("e25-legal-fine", comparison.inner_text())
            self.assertIn("e27-disaster-flood", comparison.inner_text())
            self.assertIn("42/45", comparison.inner_text())
            self.assertIn("0/45", comparison.inner_text())
            page.screenshot(
                path=str(screenshots / "policy-v2-comparison.png"), full_page=True
            )
            previous_candidate_metrics = page.locator("#topMetrics").inner_text()
            page.locator("#threshold-positive").evaluate(
                "el => { el.value = '0.95'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            self.assertNotEqual(
                page.locator("#topMetrics").inner_text(), previous_candidate_metrics
            )
            self.assertEqual(
                page.locator("#threshold-uncertainty").get_attribute("max"), "1"
            )
            page.locator("#threshold-uncertainty").evaluate(
                "el => { el.value = '1'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            self.assertEqual(page.locator("#threshold-uncertainty").input_value(), "1")
            page.locator("#resetThresholds").click()
            page.locator("[data-policy-mode='legacy']").click()
            self.assertIn("42/45", page.locator("#policyComparison").inner_text())
            page.locator("#labTab").click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "() => [...document.querySelector('#labGrid').children].map(el => el.id).join(',') === 'caseSidebar,goldPanel,detailPanel'"
            )
            page.locator('[data-policy-mode="policy_v2"]').click()
            mobile_overflow = page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            self.assertLessEqual(mobile_overflow, 1)
            mobile_layout = page.evaluate(
                """() => ({
                  comparisonTop: document.querySelector('.gold-panel').getBoundingClientRect().top + window.scrollY,
                  detailTop: document.querySelector('.detail-panel').getBoundingClientRect().top + window.scrollY,
                  readingOrder: [...document.querySelector('#labGrid').children].map(el => el.id),
                  inputFontSize: getComputedStyle(document.querySelector('#filterSearch')).fontSize,
                  searchHeight: document.querySelector('#filterSearch').getBoundingClientRect().height
                })"""
            )
            self.assertLess(mobile_layout["comparisonTop"], mobile_layout["detailTop"])
            self.assertEqual(
                mobile_layout["readingOrder"],
                ["caseSidebar", "goldPanel", "detailPanel"],
            )
            self.assertEqual(mobile_layout["inputFontSize"], "16px")
            self.assertGreaterEqual(mobile_layout["searchHeight"], 44)
            page.screenshot(
                path=str(screenshots / "policy-v2-mobile.png"), full_page=True
            )
            page.set_viewport_size({"width": 320, "height": 800})
            self.assertLessEqual(
                page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                ),
                1,
            )
            page.set_viewport_size({"width": 1440, "height": 1050})
            page.wait_for_function(
                "() => [...document.querySelector('#labGrid').children].map(el => el.id).join(',') === 'caseSidebar,detailPanel,goldPanel'"
            )
            page.locator('[data-policy-mode="legacy"]').click()
            page.locator("#resetThresholds").click()
            page.locator("#filterSearch").fill("")

            # The browser's default historical policy matches the frozen Python policy table.
            page.locator("#statsTab").click()
            self.assertIn("42/45", page.locator("#statsMetrics").inner_text())
            policy_cells = [
                row.locator("td").all_inner_texts()
                for row in page.locator("#chartsGrid .policy-table tbody tr").all()
            ]
            self.assertEqual(
                policy_cells[0][1:], ["3/45", "6.7%", "66.7%", "80.0%", "66.7%", "1/3"]
            )
            self.assertEqual(
                policy_cells[1][1:],
                ["11/45", "24.4%", "72.7%", "88.9%", "81.8%", "4/11"],
            )
            self.assertEqual(
                policy_cells[2][1:], ["8/45", "17.8%", "87.5%", "80.0%", "87.5%", "1/8"]
            )
            self.assertEqual(
                policy_cells[3][1:],
                ["18/45", "40.0%", "83.3%", "90.0%", "88.9%", "4/18"],
            )
            self.assertEqual(
                policy_cells[4][1:],
                ["40/45", "88.9%", "75.0%", "82.7%", "72.5%", "16/40"],
            )
            trigger_rows = (
                page.locator("#chartsGrid .chart-card")
                .filter(has_text="Причины ручной проверки")
                .locator(".chart-num")
                .all_inner_texts()
            )
            self.assertEqual(trigger_rows, ["5", "24", "17", "32"])
            page.locator("#labTab").click()

            # `other_uncertain` masks event-band and unlisted triggers; disabling evidence yields `other`.
            page.locator('.preset[data-preset="ignore_uncertainty_gate"]').click()
            page.locator("#filterSearch").fill("e46-other-topic")
            page.locator("#caseList .case-card").click()
            self.assertIn(
                "Другая тема", page.locator("#detailBody .decision-title").inner_text()
            )
            page.locator("#resetThresholds").click()

            # Four missing results remain visible with no invented score rows.
            page.locator("#filterSearch").fill("e23-recall-battery")
            self.assertEqual(page.locator("#caseList .case-card").count(), 1)
            page.locator("#caseList .case-card").click()
            self.assertIn(
                "Ответ Jev отсутствует",
                page.locator("#detailBody .missing-box").inner_text(),
            )
            self.assertEqual(page.locator("#detailBody .event-item").count(), 0)
            self.assertIn(
                "не учитывается как ошибка", page.locator("#detailBody").inner_text()
            )

            # e35 is flagged for label review while still correctly marked as no Jev response.
            page.locator("#filterSearch").fill("e35-multi-labor-investment")
            page.locator("#caseList .case-card").click()
            self.assertIn(
                "нужна проверка gold", page.locator("#detailBody").inner_text()
            )
            self.assertIn(
                "Ответ Jev отсутствует", page.locator("#comparisonBody").inner_text()
            )
            page.locator("#filterSearch").fill("")
            page.locator("#filterState").select_option("missing")
            self.assertEqual(page.locator("#caseList .case-card").count(), 4)
            self.assertNotIn("e48-empty", page.locator("#caseList").inner_text())
            page.locator("#filterState").select_option("all")

            # Preset E confirms local counterfactual coverage; reset restores the historical baseline.
            page.locator('.preset[data-preset="choice_only"]').click()
            self.assertIn("40/45", page.locator("#topMetrics").inner_text())
            page.locator("#statsTab").click()
            self.assertFalse(page.locator("#statsScreen").is_hidden())
            self.assertEqual(page.locator("#statsMetrics .metric").count(), 10)
            legacy_metric_labels = page.locator(
                "#statsMetrics .metric-label"
            ).all_inner_texts()
            self.assertIn("Принято без проверки", legacy_metric_labels)
            self.assertIn("Ожидаемые метки выше порога", legacy_metric_labels)
            self.assertIn("Ожидаемые метки ниже порога", legacy_metric_labels)
            self.assertIn(
                "до блокировки новости", page.locator("#statsFootnote").inner_text()
            )
            self.assertNotIn("Topic Accuracy", legacy_metric_labels)
            self.assertEqual(
                page.locator("#chartsGrid .policy-table tbody tr").count(), 5
            )
            self.assertIn("88.9%", page.locator("#statsMetrics").inner_text())
            page.screenshot(
                path=str(screenshots / "statistics-desktop.png"), full_page=True
            )
            page.locator("#labTab").click()
            page.locator("#resetThresholds").click()

            # Equality at saved Noul values obeys the inclusive positive/negative boundaries.
            page.locator("#filterSearch").fill("e01-supply-rail")
            page.locator("#caseList .case-card").click()
            page.locator("#threshold-positive").evaluate(
                "el => { el.value = '0.9'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            supply_row = page.locator("#detailBody .event-item").filter(
                has_text="Сбой поставок"
            )
            self.assertIn("positive", supply_row.locator(".state-chip").inner_text())
            page.locator("#filterSearch").fill("e19-insolvency-court")
            page.locator("#caseList .case-card").click()
            restructuring = page.locator("#detailBody .event-item").filter(
                has_text="Сделка или реструктуризация компании"
            )
            self.assertIn("negative", restructuring.locator(".state-chip").inner_text())
            page.locator("#resetThresholds").click()
            self.assertIn("3/45", page.locator("#topMetrics").inner_text())

            # A custom cutoff updates the dashboard synchronously and remains local.
            page.locator("#threshold-positive").evaluate(
                "el => { el.value = '0.90'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            self.assertEqual(page.locator("#threshold-positive").input_value(), "0.9")
            self.assertIn(
                "Legacy · пользовательские пороги",
                page.locator("#policyName").inner_text(),
            )
            page.locator("#resetThresholds").click()

            # Proposed labels are editable, recalculated locally, and exported separately.
            page.locator("#filterSearch").fill("e33-multi-price-shortage")
            page.locator("#caseList .case-card").click()
            self.assertIn("ошибка темы", page.locator("#comparisonBody").inner_text())
            page.locator("#comparisonBody details.edit-gold summary").click()
            changed_check = page.locator(
                '#comparisonBody .event-check input[value="sanctions"]'
            )
            changed_check.check(force=True)
            self.assertIn("есть ваша правка", page.locator("#detailBody").inner_text())
            with page.expect_download() as download_info:
                page.locator("#comparisonBody button.primary-button").click()
            download = download_info.value
            with tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir) / download.suggested_filename
                download.save_as(str(output))
                exported = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(exported["status"], "user_proposal_not_approved_gold")
            self.assertEqual(
                exported["changes"][0]["case_id"], "e33-multi-price-shortage"
            )
            self.assertIn("sanctions", exported["changes"][0]["proposed"]["events"])
            page.locator("#comparisonBody button.secondary-button").filter(
                has_text="Отменить"
            ).click()
            self.assertNotIn(
                "есть ваша правка", page.locator("#detailBody").inner_text()
            )

            # Mobile layout fits the viewport without horizontal scrolling.
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#filterSearch").fill("")
            page.locator("#caseList .case-card").first.click()
            page.screenshot(path=str(screenshots / "lab-mobile.png"), full_page=True)
            overflow = page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            self.assertLessEqual(overflow, 1)
            page.set_viewport_size({"width": 320, "height": 800})
            overflow = page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            offenders = page.evaluate(
                """() => [...document.querySelectorAll('*')].map(el => ({tag: el.tagName, cls: typeof el.className === 'string' ? el.className : '', text: (el.textContent || '').slice(0, 40), parent: el.parentElement?.className || '', parentRight: Math.round(el.parentElement?.getBoundingClientRect().right || 0), left: Math.round(el.getBoundingClientRect().left), right: Math.round(el.getBoundingClientRect().right)})).filter(x => x.right > innerWidth + 1 || x.left < -1).slice(0, 12)"""
            )
            self.assertLessEqual(
                overflow,
                1,
                f"320px horizontal overflow={overflow}; elements={offenders}",
            )
            self.assertEqual(
                external_requests,
                [],
                f"unexpected network requests: {external_requests}",
            )
            self.assertEqual(page_errors, [], f"browser errors: {page_errors}")
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
