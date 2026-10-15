from __future__ import annotations

import json
import socket
import unittest
from unittest.mock import patch

from jev_spike import SPIKE_DIR, load_verified_inputs
from quality_analysis import TRUSTED_AGGREGATE_SHA256, build_quality_analysis
from quality_policy import (
    PolicyInputError,
    decision_states,
    historical_review_reasons,
    noul_state,
)


class QualityPolicyTests(unittest.TestCase):
    def test_noul_boundaries_preserve_abstain_band(self) -> None:
        self.assertEqual(
            noul_state(0.2, negative_cutoff=0.2, positive_cutoff=0.8), "negative"
        )
        self.assertEqual(
            noul_state(0.20001, negative_cutoff=0.2, positive_cutoff=0.8), "abstain"
        )
        self.assertEqual(
            noul_state(0.79999, negative_cutoff=0.2, positive_cutoff=0.8), "abstain"
        )
        self.assertEqual(
            noul_state(0.8, negative_cutoff=0.2, positive_cutoff=0.8), "positive"
        )

    def test_rejects_nonfinite_out_of_range_and_boolean_scores(self) -> None:
        for score in (True, float("nan"), float("inf"), -0.01, 1.01, "0.5"):
            with self.subTest(score=score), self.assertRaises(PolicyInputError):
                noul_state(score, negative_cutoff=0.2, positive_cutoff=0.8)

    def test_rejects_invalid_or_overlapping_thresholds(self) -> None:
        for low, high in ((0.8, 0.2), (0.2, 0.2), (float("nan"), 0.8), (-1, 0.8)):
            with self.subTest(low=low, high=high), self.assertRaises(PolicyInputError):
                noul_state(0.5, negative_cutoff=low, positive_cutoff=high)

    def test_missing_or_extra_event_scores_are_rejected(self) -> None:
        taxonomy, _corpus, cases = load_verified_inputs()
        report = build_quality_analysis()
        stored = report["cases"][0]["jev"]
        base = {
            "topic": stored["topic"],
            "topic_confidence": stored["choice_confidence"],
            "event_scores": stored["event_scores"],
            "unlisted_event_score": stored["unlisted_score"],
            "uncertainty_score": stored["uncertainty_score"],
        }
        del base["event_scores"][next(iter(base["event_scores"]))]
        with self.assertRaises(PolicyInputError):
            decision_states(base, taxonomy)
        self.assertEqual(cases[0]["id"], "e01-supply-rail")

    def test_unknown_topic_code_is_rejected(self) -> None:
        taxonomy, _corpus, _cases = load_verified_inputs()
        report = build_quality_analysis()
        stored = report["cases"][0]["jev"]
        result = {
            "topic": "made_up_topic",
            "topic_confidence": stored["choice_confidence"],
            "event_scores": stored["event_scores"],
            "unlisted_event_score": stored["unlisted_score"],
            "uncertainty_score": stored["uncertainty_score"],
        }
        with self.assertRaisesRegex(PolicyInputError, "outside the pinned taxonomy"):
            decision_states(result, taxonomy)

    def test_historical_other_topic_exception_exposes_raw_and_active(self) -> None:
        report = build_quality_analysis()
        row = next(
            case for case in report["cases"] if case["case_id"] == "e46-other-topic"
        )
        reasons = historical_review_reasons(
            {
                "topic": row["jev"]["topic"],
                "topic_confidence": row["jev"]["choice_confidence"],
                "event_scores": row["jev"]["event_scores"],
                "unlisted_event_score": row["jev"]["unlisted_score"],
                "uncertainty_score": row["jev"]["uncertainty_score"],
            },
            load_verified_inputs()[0],
        )
        self.assertTrue(reasons["raw"]["unlisted"])
        self.assertFalse(reasons["active"]["unlisted"])
        self.assertFalse(reasons["active"]["event_scores"])

    def test_other_topic_without_active_trigger_keeps_historical_other_status(
        self,
    ) -> None:
        taxonomy, _corpus, _cases = load_verified_inputs()
        report = build_quality_analysis()
        row = next(
            case for case in report["cases"] if case["case_id"] == "e46-other-topic"
        )
        reasons = historical_review_reasons(
            {
                "topic": taxonomy["other_code"],
                "topic_confidence": max(
                    taxonomy["thresholds"]["choice_review_below"],
                    row["jev"]["choice_confidence"],
                ),
                "event_scores": {code: 0.2 for code in row["jev"]["event_scores"]},
                "unlisted_event_score": 0.9,
                "uncertainty_score": 0.2,
            },
            taxonomy,
        )
        self.assertFalse(any(reasons["active"].values()))
        self.assertEqual(reasons["expected_status_from_active_gate"], "other")


class QualityAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_quality_analysis()

    def test_reproduces_pinned_v4_and_counts_partial_results(self) -> None:
        source = self.report["generated_from"]
        self.assertTrue(
            self.report["reproduction"]["legacy_metrics_exactly_reproduced"]
        )
        self.assertEqual(source["result_count"], 45)
        self.assertEqual(source["expected_nonempty_count"], 49)
        self.assertEqual(
            source["missing_case_ids"],
            [
                "e23-recall-battery",
                "e35-multi-labor-investment",
                "e41-uncertain-sanctions-talk",
                "e43-uncertain-vague-delivery",
            ],
        )
        self.assertAlmostEqual(
            self.report["reproduction"]["legacy_metrics"]["topic_accuracy"],
            31 / 45,
            places=4,
        )
        self.assertAlmostEqual(
            self.report["reproduction"]["legacy_metrics"]["event_micro_f1"],
            2 * 34 / (2 * 34 + 6 + 7),
            places=4,
        )

    def test_review_reason_counts_and_combinations_are_reproducible(self) -> None:
        summary = self.report["review_summary"]
        self.assertEqual(
            (summary["review_count"], summary["automatic_status_count"]), (42, 3)
        )
        self.assertEqual(
            summary["active_trigger_case_counts_overlapping"],
            {
                "choice": 5,
                "event_scores": 24,
                "uncertainty": 17,
                "unlisted": 32,
            },
        )
        self.assertEqual(
            summary["raw_trigger_case_counts_before_other_topic_exception"],
            {
                "choice": 5,
                "event_scores": 25,
                "uncertainty": 17,
                "unlisted": 33,
            },
        )
        self.assertEqual(summary["review_cases_with_multiple_reasons"], 28)
        self.assertEqual(summary["review_cases_with_exactly_one_reason"], 14)
        self.assertEqual(summary["borderline_event_score_cells"], 43)
        self.assertEqual(summary["total_event_score_cells"], 675)
        self.assertTrue(
            all(
                row["review"]["expected_status_from_active_gate"]
                == row["jev"]["status"]
                for row in self.report["cases"]
            )
        )

    def test_policy_sweeps_have_expected_coverage_and_are_not_recommendations(
        self,
    ) -> None:
        policies = {row["policy_id"]: row for row in self.report["policies"]}
        self.assertEqual(policies["current_strict"]["accepted_case_count"], 3)
        self.assertEqual(policies["ignore_unlisted_gate"]["accepted_case_count"], 11)
        self.assertEqual(policies["ignore_uncertainty_gate"]["accepted_case_count"], 8)
        self.assertEqual(
            policies["ignore_both_signal_gates"]["accepted_case_count"], 18
        )
        self.assertEqual(policies["choice_only"]["accepted_case_count"], 40)
        self.assertEqual(
            policies["choice_only"][
                "high_consequence_false_positive_count_provisional"
            ],
            3,
        )
        self.assertEqual(
            policies["choice_only"]["unlisted_gold_cases_accepted"],
            ["e47-unlisted-contract-award"],
        )
        self.assertIn("Do not select", self.report["threshold_sweeps"]["warning"])

    def test_uncertainty_and_unlisted_gate_sweeps_hold_other_gates_fixed(self) -> None:
        sweeps = self.report["review_gate_sweeps"]
        uncertainty = sweeps["uncertainty_gate_threshold_sweep"]
        unlisted = sweeps["unlisted_gate_threshold_sweep"]
        self.assertEqual(uncertainty[0]["accepted_case_count"], 3)
        self.assertEqual(uncertainty[1]["accepted_case_count"], 6)
        self.assertEqual(
            uncertainty[1]["nonclassified_gold_cases_accepted"],
            [{"case_id": "e46-other-topic", "expected_status": "other"}],
        )
        self.assertEqual(unlisted[0]["accepted_case_count"], 3)
        self.assertEqual(unlisted[3]["accepted_case_count"], 8)
        self.assertEqual(unlisted[4]["accepted_case_count"], 11)
        self.assertEqual(unlisted[5]["accepted_case_count"], 11)
        self.assertEqual(unlisted[4]["unlisted_gold_cases_accepted"], [])
        self.assertEqual(unlisted[5]["unlisted_gold_cases_accepted"], [])
        e47 = next(
            case
            for case in self.report["cases"]
            if case["case_id"] == "e47-unlisted-contract-award"
        )
        self.assertGreater(e47["jev"]["unlisted_score"], 0.5)
        self.assertLessEqual(e47["jev"]["unlisted_score"], 0.6)
        self.assertIn(
            "corporate_transaction_restructuring",
            e47["review"]["borderline_event_codes"],
        )

    def test_no_network_is_possible_during_analysis(self) -> None:
        with patch.object(
            socket, "socket", side_effect=AssertionError("network access attempted")
        ):
            self.assertEqual(
                build_quality_analysis()["review_summary"]["review_count"], 42
            )

    def test_saved_output_is_deterministic_and_original_hashes_are_pinned(self) -> None:
        saved = json.loads(
            (SPIKE_DIR / "QUALITY_ANALYSIS.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved, self.report)
        self.assertEqual(
            self.report["generated_from"]["corpus_sha256"],
            "592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d7",
        )
        self.assertEqual(
            self.report["generated_from"]["aggregate_sha256"],
            TRUSTED_AGGREGATE_SHA256,
        )
        self.assertEqual(
            self.report["generated_from"]["taxonomy_sha256"],
            "855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d",
        )

    def test_absent_api_rows_are_not_invented_as_false_negatives(self) -> None:
        observed = {row["case_id"] for row in self.report["cases"]}
        for missing in self.report["generated_from"]["missing_case_ids"]:
            self.assertNotIn(missing, observed)
        self.assertEqual(len(self.report["cases"]), 45)


if __name__ == "__main__":
    unittest.main()
