from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import analyze_pilot  # noqa: E402


class ExpandedPilotAnalysisTests(unittest.TestCase):
    def test_recomputed_metrics_match_live_result_and_expected_counts(self) -> None:
        analysis = analyze_pilot.analyze()
        core = analysis["core_metrics_at_event_threshold_0_8"]
        self.assertEqual(analysis["sample"]["successful_responses"], 50)
        self.assertEqual(analysis["sample"]["failed_attempts"], 0)
        self.assertEqual(core["topic_correct"], 33)
        self.assertAlmostEqual(core["topic_accuracy"], 0.66)
        self.assertEqual((core["tp"], core["fp"], core["fn"]), (31, 3, 7))
        self.assertAlmostEqual(core["f1"], 0.8611111111)
        self.assertEqual(core["event_exact_set_count"], 40)
        self.assertAlmostEqual(core["event_exact_set_accuracy"], 0.8)

    def test_policy_comparison_shows_review_reduction_and_signal_misses(self) -> None:
        analysis = analyze_pilot.analyze()
        comparison = analysis["policy_comparison"]
        self.assertEqual(comparison["legacy_full_story_manual_review_or_other"], 49)
        self.assertEqual(comparison["policy_v2_1_cases_with_any_review_task"], 0)
        self.assertEqual(comparison["policy_v2_1_candidate_stories"], 26)
        self.assertEqual(comparison["policy_v2_1_candidate_events"], 34)
        self.assertEqual(comparison["uncertainty_gold_count"], 7)
        self.assertEqual(comparison["uncertainty_signal_at_0_8"]["tp"], 3)
        self.assertEqual(comparison["unlisted_gold_count"], 2)
        self.assertEqual(comparison["unlisted_signal_at_0_8"]["tp"], 0)
        self.assertEqual(
            comparison["event_score_cells_at_0_2_and_0_8"],
            {
                "positive": 34,
                "negative": 679,
                "abstain": 37,
                "abstain_stories": 25,
            },
        )

    def test_report_warns_about_draft_labels_and_non_blind_corpus(self) -> None:
        analysis = analyze_pilot.analyze()
        self.assertEqual(
            analysis["data_status"],
            "synthetic_only_preliminary_single_curator_not_blind",
        )
        self.assertFalse(analysis["methodology"]["labels_sent_to_jev"])
        self.assertFalse(analysis["methodology"]["thresholds_tuned_on_this_set"])
        report = analyze_pilot.REPORT_PATH.read_text(encoding="utf-8")
        self.assertIn("не утверждены", report)
        self.assertIn("не слепая", report)
        self.assertIn("не доказывает", report)

    def test_machine_report_has_source_hashes_and_safe_sanitized_data_only(
        self,
    ) -> None:
        analyze_pilot.analyze()
        data = json.loads(analyze_pilot.ANALYSIS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            set(data["source_sha256"]),
            {"news", "annotations", "taxonomy", "live_results"},
        )
        live = json.loads(analyze_pilot.RESULTS_PATH.read_text(encoding="utf-8"))
        expected_result_keys = {
            "case_id",
            "taxonomy_id",
            "taxonomy_version",
            "taxonomy_hash",
            "model_version",
            "topic",
            "topic_confidence",
            "topic_probabilities",
            "event_scores",
            "unlisted_event_score",
            "uncertainty_score",
            "predicted_events",
            "classification_status",
            "usage",
            "elapsed_ms",
            "request_sha256",
        }
        for row in live["results"]:
            self.assertEqual(set(row), expected_result_keys)
            self.assertNotIn("text", row)
            self.assertNotIn("title", row)
            self.assertNotIn("answers", row)
            self.assertNotIn("prompt", row)


if __name__ == "__main__":
    unittest.main()
