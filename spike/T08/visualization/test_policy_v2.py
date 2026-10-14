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

    def test_choice_and_event_abstain_are_saved_but_do_not_create_review(self) -> None:
        case = self.by_id["e01-supply-rail"]
        result_input = dict(case["result"])
        topic_codes = list(result_input["topic_probabilities"])
        selected_topic = result_input["topic"]
        low_choice_probability = 0.32
        result_input["topic_probabilities"] = {
            code: (low_choice_probability if code == selected_topic else 0.068)
            for code in topic_codes
        }
        result_input["topic_confidence"] = (
            low_choice_probability - 1 / len(topic_codes)
        ) / (1 - 1 / len(topic_codes))
        result = evaluate_result(result_input, self.taxonomy)
        self.assertEqual(result["event_states"]["supply_chain_disruption"], "positive")
        self.assertIn(
            "production_operational_disruption", result["event_abstain_codes"]
        )
        self.assertEqual(result["topic_state"], "saved")
        self.assertEqual(result["topic_code"], case["result"]["topic"])
        self.assertEqual(
            result["topic_probabilities"], result_input["topic_probabilities"]
        )
        self.assertEqual(result["event_scores"], case["result"]["event_scores"])
        self.assertIn("supply_chain_disruption", result["candidate_codes"])
        self.assertFalse(result["needs_any_review"])

    def test_event_candidate_threshold_is_inclusive_at_point_eight(self) -> None:
        case = self.by_id["e04-shortage-ports"]
        result = evaluate_result(case["result"], self.taxonomy)
        self.assertIn("shortage_capacity_constraint", result["candidate_codes"])
        self.assertFalse(result["candidate_blocked_by_evidence"])

    def test_evidence_at_point_eight_holds_candidates_but_preserves_scores(
        self,
    ) -> None:
        case = self.by_id["e04-shortage-ports"]
        result_input = dict(case["result"])
        result_input["uncertainty_score"] = 0.8
        result = evaluate_result(result_input, self.taxonomy)
        self.assertTrue(result["candidate_blocked_by_evidence"])
        self.assertIn("shortage_capacity_constraint", result["positive_event_codes"])
        self.assertIn("shortage_capacity_constraint", result["candidate_blocked_codes"])
        self.assertEqual(result["candidate_codes"], [])
        self.assertTrue(result["evidence_review"])

    def test_high_evidence_without_event_candidate_does_not_create_hold_task(
        self,
    ) -> None:
        case = self.by_id["e40-uncertain-strike-forecast"]
        result = evaluate_result(case["result"], self.taxonomy)
        self.assertGreaterEqual(result["insufficient_evidence_score"], 0.8)
        self.assertEqual(result["candidate_codes"], [])
        self.assertFalse(result["evidence_review"])
        self.assertFalse(result["needs_any_review"])

    def test_unlisted_threshold_is_inclusive_and_independent(self) -> None:
        case = self.by_id["e01-supply-rail"]
        result_input = dict(case["result"])
        result_input["unlisted_event_score"] = 0.8
        result = evaluate_result(result_input, self.taxonomy)
        self.assertTrue(result["unlisted_review"])
        self.assertIn("supply_chain_disruption", result["candidate_codes"])
        self.assertTrue(result["needs_any_review"])

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
        self.assertEqual(v2["stories_with_candidates"], 32)
        self.assertEqual(v2["candidate_event_count"], 40)
        self.assertEqual(v2["stories_with_any_review"], 0)
        self.assertEqual(v2["insufficient_evidence_review_stories"], 0)
        self.assertEqual(v2["unlisted_event_review_stories"], 0)
        event = v2["event_output_metrics"]
        self.assertEqual((event["tp"], event["fp"], event["fn"]), (34, 6, 7))
        self.assertAlmostEqual(event["precision"], 34 / 40)
        self.assertAlmostEqual(event["recall"], 34 / 41)
        self.assertAlmostEqual(event["f1"], 68 / 81)
        self.assertEqual(event["exact_count"], 34)
        self.assertEqual(event["provisional_high_consequence_fp_count"], 3)
        self.assertEqual(
            {
                (row["case_id"], row["code"])
                for row in event["provisional_high_consequence_fp"]
            },
            {
                ("e03-shortage-cells", "production_operational_disruption"),
                ("e25-legal-fine", "sanctions"),
                ("e27-disaster-flood", "production_operational_disruption"),
            },
        )

    def test_unlisted_review_is_separate_and_does_not_hold_candidates(self) -> None:
        case = self.by_id["e01-supply-rail"]
        result = evaluate_result(case["result"], self.taxonomy, unlisted_cutoff=0.53)
        self.assertTrue(result["unlisted_review"])
        self.assertFalse(result["evidence_review"])
        self.assertIn("supply_chain_disruption", result["candidate_codes"])
        self.assertEqual(len(result["review_tasks"]), 1)

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
        malformed = dict(case["result"])
        malformed["topic_probabilities"] = dict(malformed["topic_probabilities"])
        malformed["topic_probabilities"].pop(
            next(iter(malformed["topic_probabilities"]))
        )
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(malformed, self.taxonomy)

    def test_choice_probabilities_and_confidence_must_be_consistent(self) -> None:
        original = self.by_id["e01-supply-rail"]["result"]

        wrong_confidence = dict(original)
        wrong_confidence["topic_confidence"] = 0.5
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(wrong_confidence, self.taxonomy)

        wrong_winner = dict(original)
        wrong_winner["topic_probabilities"] = dict(original["topic_probabilities"])
        selected = wrong_winner["topic"]
        other = next(
            code for code in wrong_winner["topic_probabilities"] if code != selected
        )
        wrong_winner["topic_probabilities"][selected] = 0.0
        wrong_winner["topic_probabilities"][other] = 1.0
        wrong_winner["topic_confidence"] = 1.0
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(wrong_winner, self.taxonomy)

        wrong_sum = dict(original)
        wrong_sum["topic_probabilities"] = dict(original["topic_probabilities"])
        wrong_sum["topic_probabilities"][selected] -= 0.1
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(wrong_sum, self.taxonomy)

    def test_unknown_topic_and_missing_or_extra_event_scores_fail_closed(self) -> None:
        result = self.by_id["e01-supply-rail"]["result"]
        malformed = dict(result)
        malformed["topic"] = "unapproved_topic"
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(malformed, self.taxonomy)

        malformed = dict(result)
        malformed["event_scores"] = dict(result["event_scores"])
        malformed["event_scores"].pop(next(iter(malformed["event_scores"])))
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(malformed, self.taxonomy)

        malformed = dict(result)
        malformed["event_scores"] = dict(result["event_scores"])
        malformed["event_scores"]["unapproved_event"] = 0.99
        with self.assertRaises(PolicyV2InputError):
            evaluate_result(malformed, self.taxonomy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
