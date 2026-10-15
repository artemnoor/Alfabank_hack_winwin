from __future__ import annotations

import json
import unittest

from build_taxonomy_v042_proposal import (
    BASELINE_SHA256,
    MANIFEST,
    PARENT,
    PARENT_MANIFEST,
    PARENT_MANIFEST_SHA256,
    PARENT_SHA256,
    TARGET,
    write,
)
from stable_hash import sha256_text_file

ROOT = TARGET.parents[2]


class TaxonomyV042ProposalTests(unittest.TestCase):
    def test_proposal_is_hash_pinned_to_v041_and_preserves_baseline_contract_shape(
        self,
    ) -> None:
        manifest = write()
        proposed = json.loads(TARGET.read_text(encoding="utf-8"))
        parent = json.loads(PARENT.read_text(encoding="utf-8"))
        baseline = json.loads((ROOT / "taxonomy.json").read_text(encoding="utf-8"))
        saved_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(proposed["version"], "0.4.2-spike")
        self.assertEqual(manifest, saved_manifest)
        self.assertEqual(sha256_text_file(PARENT), PARENT_SHA256)
        self.assertEqual(
            sha256_text_file(PARENT_MANIFEST),
            PARENT_MANIFEST_SHA256,
        )
        self.assertEqual(
            sha256_text_file(ROOT / "taxonomy.json"),
            BASELINE_SHA256,
        )
        self.assertEqual(
            [row["code"] for row in proposed["topics"]],
            [row["code"] for row in baseline["topics"]],
        )
        self.assertEqual(
            [row["code"] for row in proposed["events"]],
            [row["code"] for row in baseline["events"]],
        )
        self.assertEqual(proposed["thresholds"], parent["thresholds"])
        self.assertEqual(proposed["topic_choice_id"], parent["topic_choice_id"])
        self.assertEqual(manifest["new_jev_requests"], 0)
        self.assertTrue(manifest["requires_new_live_pilot_before_scoring"])
        self.assertFalse(manifest["contract_or_production_changes"])

    def test_minimal_boundaries_and_uncertainty_dimension_are_explicit(self) -> None:
        write()
        proposed = json.loads(TARGET.read_text(encoding="utf-8"))
        events = {row["code"]: row for row in proposed["events"]}
        self.assertIn(
            "недоступность площадки",
            events["production_operational_disruption"]["exclude"].lower(),
        )
        self.assertIn(
            "таможенная пошлина", events["trade_restriction"]["include"].lower()
        )
        self.assertIn("штраф", events["sanctions"]["exclude"].lower())
        self.assertIn(
            "официально начатое расследование",
            events["legal_enforcement"]["include"].lower(),
        )
        self.assertIn(
            "локальный пожар", events["environment_disaster_impact"]["exclude"].lower()
        )
        self.assertIn(
            "отдельной фразой",
            events["shortage_capacity_constraint"]["include"].lower(),
        )
        self.assertIn("основной темы", proposed["uncertainty_question"])
        self.assertTrue(
            any(
                "события вне списка" in rule.lower()
                for rule in proposed["annotation_rules"]
            )
        )

    def test_gold_review_is_advisory_and_quotes_match_source_text(self) -> None:
        report_path = ROOT / "GOLD_LABEL_REVIEW_V2.1.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        corpus = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))
        cases = {row["id"]: row for row in corpus["cases"]}
        self.assertEqual(report["reviewer_type"], "AI read-only reviewer")
        self.assertFalse(report["jeV_outputs_used_for_first_pass"])
        self.assertFalse(report["human_gold_approved"])
        self.assertFalse(report["source_labels_modified"])
        for review in report["cases"]:
            source = cases[review["case_id"]]["text"]
            for quote in review["evidence"]:
                self.assertIn(quote, source)

    def test_error_audit_uses_abstain_for_e34_score_029(self) -> None:
        report = json.loads(
            (ROOT / "ERROR_ANALYSIS_V2.1.json").read_text(encoding="utf-8")
        )
        row = next(
            row
            for row in report["false_negatives"]
            if row["case_id"] == "e34-multi-insolvency-legal"
        )
        self.assertEqual(row["event_score"], 0.29)
        self.assertEqual(row["event_state"], "abstain")
        self.assertIn("abstain band", row["observed_issue"])
        self.assertNotIn("0.29 отрицательный", row["observed_issue"])


if __name__ == "__main__":
    unittest.main()
