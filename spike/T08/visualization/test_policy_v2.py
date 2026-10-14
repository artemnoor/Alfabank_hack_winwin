from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SPIKE))

from build import build_payload  # noqa: E402
from policy_v2 import PolicyV2InputError, evaluate_result, tri_state  # noqa: E402


class PolicyV2UnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build_payload()
        cls.taxonomy = cls.payload["taxonomy"]
        cls.by_id = {case["id"]: case for case in cls.payload["cases"]}

    def test_threshold_boundaries_are_explicit(self) -> None:
        self.assertEqual(
            tri_state(0.2, negative=0.2, positive=0.8, name="test"), "negative"
        )
        self.assertEqual(
            tri_state(0.20001, negative=0.2, positive=0.8, name="test"), "abstain"
        )
        self.assertEqual(
            tri_state(0.8, negative=0.2, positive=0.8, name="test"), "positive"
        )

    def test_abstain_unlisted_and_choice_review_do_not_hide_clear_event_candidate(
        self,
    ) -> None:
        case = self.by_id["e01-supply-rail"]
        result = evaluate_result(case["result"], self.taxonomy)
        self.assertEqual(result["event_states"]["supply_chain_disruption"], "positive")
        self.assertIn("production_operational_disruption", result["event_review_codes"])
        self.assertEqual(result["unlisted_event_state"], "abstain")
        self.assertIn("supply_chain_disruption", result["candidate_codes"])
        self.assertTrue(result["needs_any_review"])

    def test_low_choice_confidence_does_not_block_clear_event_candidate(self) -> None:
        case = self.by_id["e06-production-fire"]
        result = evaluate_result(case["result"], self.taxonomy)
        self.assertTrue(result["choice_review"])
        self.assertIn("production_operational_disruption", result["candidate_codes"])

    def test_insufficient_evidence_blocks_candidates_without_erasing_scores(
        self,
    ) -> None:
        case = self.by_id["e04-shortage-ports"]
        result = evaluate_result(case["result"], self.taxonomy)
        self.assertEqual(result["insufficient_evidence_state"], "abstain")
        self.assertTrue(result["candidate_blocked_by_evidence"])
        self.assertIn("shortage_capacity_constraint", result["positive_event_codes"])
        self.assertIn("shortage_capacity_constraint", result["candidate_blocked_codes"])
        self.assertEqual(result["candidate_codes"], [])

    def test_policy_v2_comparison_reproduces_pinned_output_counts(self) -> None:
        metrics = self.payload["meta"]["policyV2"]
        self.assertEqual(metrics["denominator"], 45)
        self.assertEqual(metrics["expected_event_total"], 41)
        self.assertEqual(metrics["legacy"]["full_story_auto_count"], 3)
        self.assertEqual(metrics["legacy"]["full_story_review_count"], 42)
        self.assertEqual(metrics["legacy"]["event_output_metrics"]["tp"], 2)
        self.assertEqual(metrics["legacy"]["event_output_metrics"]["fp"], 1)
        self.assertEqual(metrics["legacy"]["event_output_metrics"]["fn"], 39)

        v2 = metrics["policy_v2"]
        self.assertEqual(v2["stories_with_candidates"], 23)
        self.assertEqual(v2["candidate_event_count"], 26)
        self.assertEqual(v2["stories_with_any_review"], 42)
        self.assertEqual(v2["event_abstain_cells"], 43)
        event = v2["event_output_metrics"]
        self.assertEqual((event["tp"], event["fp"], event["fn"]), (22, 4, 19))
        self.assertAlmostEqual(event["precision"], 22 / 26)
        self.assertAlmostEqual(event["recall"], 22 / 41)
        self.assertAlmostEqual(event["f1"], 44 / 67)
        self.assertEqual(event["provisional_high_consequence_fp_count"], 2)
        self.assertEqual(
            {
                (row["case_id"], row["code"])
                for row in event["provisional_high_consequence_fp"]
            },
            {
                ("e03-shortage-cells", "production_operational_disruption"),
                ("e25-legal-fine", "sanctions"),
            },
        )

    def test_missing_jev_result_is_not_fabricated_as_event_false_negative(self) -> None:
        result = self.payload["meta"]["policyV2"]["policy_v2"]["cases"]
        self.assertNotIn("e23-recall-battery", result)

    def test_invalid_scores_and_inverted_thresholds_fail_closed(self) -> None:
        case = self.by_id["e01-supply-rail"]
        malformed = dict(case["result"])
        malformed["event_scores"] = dict(malformed["event_scores"])
        malformed["event_scores"]["supply_chain_disruption"] = float("nan")
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(malformed, self.taxonomy)
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(
                case["result"], self.taxonomy, negative_cutoff=0.8, positive_cutoff=0.8
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
