from __future__ import annotations

import json
import unittest

from build_future_blind_candidate import DATA_DIR, MANIFEST, NEWS, build_manifest
from stable_hash import sha256_text_file


class FutureBlindCandidateTests(unittest.TestCase):
    def test_candidate_inputs_are_new_unlabelled_and_not_used_for_current_scoring(
        self,
    ) -> None:
        document = json.loads(NEWS.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(len(document["cases"]), 40)
        self.assertFalse(manifest["derived_from_jev_outputs"])
        self.assertFalse(manifest["selected_from_current_error_cases"])
        self.assertFalse(manifest["gold_labels_present"])
        self.assertFalse(manifest["model_outputs_present"])
        self.assertFalse(manifest["eligible_for_current_scoring"])
        self.assertFalse(manifest["genuinely_blind_now"])
        self.assertEqual(manifest["new_jev_requests"], 0)
        self.assertEqual(sha256_text_file(NEWS), manifest["news_sha256"])
        self.assertEqual(build_manifest(), manifest)

    def test_candidate_set_is_novel_against_existing_t08_corpora(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertLess(manifest["maximum_similarity_to_existing_t08_texts"], 0.72)

    def test_annotation_guide_keeps_human_labels_and_holdout_separate(self) -> None:
        guide = (DATA_DIR / "ANNOTATION_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("Two people", guide)
        self.assertIn("third person", guide)
        self.assertIn("custodian", guide)
        self.assertIn("not yet a blind benchmark", guide)


if __name__ == "__main__":
    unittest.main()
