from __future__ import annotations

import unittest

from jev_spike import SPIKE_DIR, load_verified_inputs
from quality_analysis import build_quality_analysis
from render_review_tables import render_error_analysis, render_uncertainty


class QualityArtifactTests(unittest.TestCase):
    def test_error_and_uncertainty_reports_match_pinned_machine_analysis(self) -> None:
        report = build_quality_analysis()
        self.assertEqual(
            (SPIKE_DIR / "ERROR_ANALYSIS.md").read_text(encoding="utf-8"),
            render_error_analysis(report),
        )
        self.assertEqual(
            (SPIKE_DIR / "UNCERTAINTY_ANALYSIS.md").read_text(encoding="utf-8"),
            render_uncertainty(report),
        )

    def test_reports_include_full_review_matrix_and_draft_gold_warning(self) -> None:
        uncertainty = (SPIKE_DIR / "UNCERTAINTY_ANALYSIS.md").read_text(
            encoding="utf-8"
        )
        errors = (SPIKE_DIR / "ERROR_ANALYSIS.md").read_text(encoding="utf-8")
        self.assertEqual(
            sum(line.startswith("| `e") for line in uncertainty.splitlines()), 45
        )
        self.assertIn("предварительные метки одного автора", errors)
        self.assertIn("неуспешных", errors)
        self.assertIn("не являются", errors)

    def test_blind_gold_packet_quotes_the_disputed_e35_source(self) -> None:
        _taxonomy, _corpus, cases = load_verified_inputs()
        case = next(row for row in cases if row["id"] == "e35-multi-labor-investment")
        quote = next(part.strip() for part in case["text"].split(".") if "400" in part)
        packet = (SPIKE_DIR / "HUMAN_REVIEW_PACKET.md").read_text(encoding="utf-8")
        self.assertIn(quote, packet)

    def test_review_gate_tables_match_machine_sweeps(self) -> None:
        report = build_quality_analysis()
        markdown = (SPIKE_DIR / "THRESHOLD_COMPARISON.md").read_text(encoding="utf-8")

        def table_rows(section_heading: str) -> list[list[str]]:
            section = markdown.split(section_heading, 1)[1]
            rows = []
            for line in section.splitlines():
                if not line.startswith("|"):
                    if rows:
                        break
                    continue
                columns = [column.strip() for column in line.strip("|").split("|")]
                if columns and set(columns[0]) <= {"-", ":"}:
                    continue
                rows.append(columns)
            return rows[1:]

        def pct(value: float) -> str:
            return f"{value * 100:.1f}%"

        comparisons = (
            (
                "### Insufficient-evidence review gate",
                report["review_gate_sweeps"]["uncertainty_gate_threshold_sweep"],
                lambda row: [
                    f">{row['trigger_when_score_above']:.2f}",
                    str(row["accepted_case_count"]),
                    pct(row["coverage"]),
                    pct(row["topic_accuracy"]),
                    pct(row["event_metrics"]["f1"]),
                    pct(row["event_metrics"]["exact_rate"]),
                    pct(row["case_error_rate"]),
                    ", ".join(
                        f"{item['case_id'].split('-', 1)[0]} (`{item['expected_status']}`)"
                        for item in row["nonclassified_gold_cases_accepted"]
                    )
                    or "none",
                ],
            ),
            (
                "### Out-of-list review gate",
                report["review_gate_sweeps"]["unlisted_gate_threshold_sweep"],
                lambda row: [
                    f">{row['trigger_when_score_above']:.2f}",
                    str(row["accepted_case_count"]),
                    pct(row["coverage"]),
                    pct(row["topic_accuracy"]),
                    pct(row["event_metrics"]["f1"]),
                    pct(row["event_metrics"]["exact_rate"]),
                    pct(row["case_error_rate"]),
                    "yes" if row["unlisted_gold_cases_accepted"] else "no",
                ],
            ),
        )
        for heading, expected_rows, render in comparisons:
            with self.subTest(section=heading):
                self.assertEqual(
                    table_rows(heading), [render(row) for row in expected_rows]
                )


if __name__ == "__main__":
    unittest.main()
