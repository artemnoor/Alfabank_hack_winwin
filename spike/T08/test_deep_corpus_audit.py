from __future__ import annotations

import json
import unittest

from deep_corpus_audit import DEEP_DIR, OUTPUT_PATH, build_audit
from jev_spike import SPIKE_DIR


class DeepCorpusAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = build_audit()

    def test_hashes_and_split_sizes_match_frozen_manifest(self) -> None:
        self.assertEqual(self.audit["total_cases"], 160)
        self.assertEqual(self.audit["nonempty_cases"], 158)
        self.assertEqual(
            self.audit["split_counts"], {"A": 76, "B": 36, "C": 24, "D": 24}
        )
        self.assertTrue(
            all(row["sha256_verified"] for row in self.audit["split_audit"].values())
        )
        self.assertTrue(self.audit["original_baseline_unchanged"])

    def test_d_is_visible_nonblind_and_never_a_scoring_split(self) -> None:
        self.assertTrue(self.audit["not_a_blind_holdout"])
        self.assertEqual(
            self.audit["d_split_status"],
            "visible_nonblind_control; excluded from tuning and scoring",
        )
        self.assertFalse(self.audit["split_audit"]["D"]["blind"])
        self.assertFalse(
            self.audit["split_audit"]["D"]["scored_or_used_for_thresholds"]
        )
        self.assertEqual(self.audit["jev_calls"], 0)

    def test_category_coverage_and_duplicate_audit_are_reported(self) -> None:
        self.assertEqual(self.audit["uncovered_topic_codes"], [])
        self.assertEqual(self.audit["uncovered_event_codes"], [])
        self.assertIsInstance(self.audit["exact_duplicate_text_groups"], list)
        self.assertIsInstance(
            self.audit["near_duplicate_pairs_at_or_above_threshold"], list
        )
        self.assertGreater(self.audit["near_duplicate_threshold"], 0.9)

    def test_machine_report_is_reproducible_and_unchanged(self) -> None:
        saved = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved, self.audit)
        self.assertEqual(
            self.audit["source_corpus_sha256"],
            "592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d7",
        )
        self.assertTrue(DEEP_DIR.is_dir())
        self.assertTrue(SPIKE_DIR.is_dir())


if __name__ == "__main__":
    unittest.main()
