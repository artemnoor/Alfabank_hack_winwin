from __future__ import annotations

import json
import unittest

from build_t08_report import (
    REPORT_JSON_PATH,
    REPORT_MD_PATH,
    build_report,
    render_markdown,
)


class T08FinalReportTests(unittest.TestCase):
    def test_checked_in_report_reproduces_current_evidence_and_verdicts(self) -> None:
        report = build_report(
            unit_tests_passed=132,
            browser_tests_passed=27,
            check_statuses={
                "ruff_check": "PASS",
                "ruff_format_check": "PASS",
                "offline_runner": "PASS",
                "quality_analysis_reproducibility": "PASS",
                "deep_corpus_audit_reproducibility": "PASS",
                "validation_asset_builder": "PASS",
                "javascript_syntax": "PASS",
                "git_diff_checks": "PASS",
            },
        )
        unverified_report = build_report(
            unit_tests_passed=0,
            browser_tests_passed=0,
        )
        for key in (
            "ruff_check",
            "ruff_format_check",
            "offline_runner_status",
            "quality_analysis_reproducibility",
            "deep_corpus_audit_reproducibility",
            "validation_asset_builder",
            "javascript_syntax",
            "git_diff_checks",
        ):
            self.assertEqual(unverified_report["verification"][key], "NOT_RUN")
        self.assertEqual(
            unverified_report["verdicts"]["engineering_quality"]["status"],
            "INCOMPLETE",
        )
        self.assertEqual(
            unverified_report["verdicts"]["integration_readiness"]["status"],
            "INCOMPLETE_VERIFICATION",
        )
        unverified_markdown = render_markdown(unverified_report)
        self.assertIn("NOT READY — INCOMPLETE_VERIFICATION", unverified_markdown)
        self.assertNotIn(
            "READY — только экспериментальная передача", unverified_markdown
        )
        self.assertEqual(
            unverified_report["verification"]["unit_tests"]["status"],
            "NOT_RUN",
        )
        self.assertEqual(
            unverified_report["verification"]["policy_and_browser_tests"]["status"],
            "NOT_RUN",
        )
        self.assertEqual(
            json.loads(REPORT_JSON_PATH.read_text(encoding="utf-8")), report
        )
        self.assertEqual(
            REPORT_MD_PATH.read_text(encoding="utf-8"), render_markdown(report)
        )
        self.assertEqual(report["verdicts"]["api_compatibility"]["status"], "BLOCKED")
        self.assertEqual(report["verdicts"]["engineering_quality"]["status"], "PASS")
        self.assertEqual(
            report["verdicts"]["integration_readiness"]["status"],
            "READY_FOR_EXPERIMENTAL_T09_HANDOFF_ONLY",
        )
        self.assertIn(
            "READY — только экспериментальная передача кандидатов",
            render_markdown(report),
        )
        self.assertEqual(
            report["verdicts"]["model_quality"]["status"],
            "NOT_MEASURED_FOR_DECISION",
        )
        self.assertTrue(report["visible_validation_set"]["is_genuinely_blind"] is False)
        self.assertEqual(report["policy_v2_1"]["candidate_bearing_stories"], 32)
        self.assertEqual(report["policy_v2_1"]["candidate_event_count"], 40)
        self.assertEqual(
            report["error_disagreements"]["counts"],
            {"false_positives": 6, "false_negatives": 7},
        )


if __name__ == "__main__":
    unittest.main()
