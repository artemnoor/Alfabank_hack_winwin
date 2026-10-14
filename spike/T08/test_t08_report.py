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
        report = build_report(unit_tests_passed=118, browser_tests_passed=23)
        self.assertEqual(
            json.loads(REPORT_JSON_PATH.read_text(encoding="utf-8")), report
        )
        self.assertEqual(
            REPORT_MD_PATH.read_text(encoding="utf-8"), render_markdown(report)
        )
        self.assertEqual(report["verdicts"]["api_compatibility"]["status"], "BLOCKED")
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
