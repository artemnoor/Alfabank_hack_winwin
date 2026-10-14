from __future__ import annotations

import json
import unittest

from build_policy_v21_manifest import OUTPUT, build_manifest
from visualization.policy_v2 import POLICY_VERSION, evaluate_result


class PolicyV21HandoffTests(unittest.TestCase):
    def test_frozen_manifest_matches_saved_policy_and_implementations(self) -> None:
        manifest = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build_manifest())
        self.assertEqual(POLICY_VERSION, "2.1.0-spike")
        self.assertEqual(manifest["policy_version"], POLICY_VERSION)
        self.assertFalse(manifest["runtime_integration"])
        self.assertFalse(manifest["public_contract_changed"])
        self.assertEqual(manifest["new_jev_api_requests"], 0)
        self.assertEqual(manifest["observed_saved_run"]["missing_answer_count"], 4)

    def test_candidates_remain_unconfirmed_and_routes_are_independent(self) -> None:
        result = json.loads(
            (OUTPUT.parent / "visualization/policy-v2-results.json").read_text(
                encoding="utf-8"
            )
        )
        decisions = result["policy_comparison"]["policy_v2"]["cases"]
        for decision in decisions.values():
            if decision["missing_result"]:
                self.assertEqual(decision["candidate_codes"], [])
                self.assertEqual(decision["candidate_blocked_codes"], [])
                continue
            positive = decision["positive_event_codes"]
            if decision["insufficient_evidence_threshold_reached"] and positive:
                self.assertEqual(decision["candidate_codes"], [])
                self.assertEqual(decision["candidate_blocked_codes"], positive)
            else:
                self.assertEqual(decision["candidate_codes"], positive)
                self.assertEqual(decision["candidate_blocked_codes"], [])
            self.assertEqual(
                decision["needs_any_review"],
                decision["evidence_review"] or decision["unlisted_review"],
            )
            if decision["unlisted_review"]:
                self.assertIsInstance(decision["review_tasks"], list)

    def test_handoff_does_not_promote_candidates_to_fact_or_public_fields(self) -> None:
        spec = (OUTPUT.parent / "POLICY_V2.1.md").read_text(encoding="utf-8")
        handoff = (OUTPUT.parent / "T09_HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("не production policy", spec)
        self.assertIn("кандидат", spec.lower())
        self.assertIn("не подтверждённый факт", spec.lower())
        self.assertIn("OpenAPI", spec)
        self.assertIn("не является фактом", handoff.lower())
        self.assertIn("evidence spans", handoff)
        self.assertIn("topic-only", spec.lower())

    def test_counterfactual_evidence_hold_requires_positive_candidates(self) -> None:
        taxonomy = json.loads(
            (OUTPUT.parent / "taxonomy.json").read_text(encoding="utf-8")
        )
        policy = json.loads(
            (OUTPUT.parent / "visualization/policy-v2-results.json").read_text(
                encoding="utf-8"
            )
        )["policy_comparison"]["policy_v2"]
        case = policy["cases"]["e01-supply-rail"]
        saved = {
            "topic": case["topic_code"],
            "topic_confidence": case["topic_confidence"],
            "topic_probabilities": case["topic_probabilities"],
            "event_scores": case["event_scores"],
            "unlisted_event_score": 0.1,
            "uncertainty_score": 0.9,
        }
        held = evaluate_result(saved, taxonomy)
        self.assertEqual(held["candidate_codes"], [])
        self.assertEqual(held["candidate_blocked_codes"], ["supply_chain_disruption"])
        no_candidate = dict(
            saved, event_scores={key: 0.1 for key in saved["event_scores"]}
        )
        no_candidate["uncertainty_score"] = 0.9
        unheld = evaluate_result(no_candidate, taxonomy)
        self.assertFalse(unheld["evidence_review"])
        self.assertEqual(unheld["candidate_codes"], [])


if __name__ == "__main__":
    unittest.main()
