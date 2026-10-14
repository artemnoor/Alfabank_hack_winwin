from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import (
    AGGREGATE_PATH,
    CORPUS_PATH,
    OUTPUT_PATH,
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
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(OUTPUT_PATH.resolve().as_uri(), wait_until="load")

            self.assertEqual(page.title(), "Лаборатория Jev · T08")
            self.assertEqual(page.locator("#caseList .case-card").count(), 50)
            self.assertEqual(page.locator("#detailBody .event-item").count(), 15)
            self.assertIn("31/45", page.locator("#topMetrics").inner_text())
            self.assertIn("84.0%", page.locator("#topMetrics").inner_text())
            self.assertIn("3/45", page.locator("#topMetrics").inner_text())
            page.screenshot(path=str(screenshots / "lab-desktop.png"), full_page=True)

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
                "Пользовательские пороги", page.locator("#policyName").inner_text()
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
