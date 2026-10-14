from __future__ import annotations

import hashlib
import json
import unittest

from build_taxonomy_proposal import MANIFEST, SOURCE, TARGET, build


class TaxonomyProposalTests(unittest.TestCase):
    def test_proposal_is_separate_unvalidated_and_keeps_registry_codes(self) -> None:
        proposed, manifest = build()
        baseline = json.loads(SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(baseline["version"], "0.3.0-spike")
        self.assertEqual(proposed["version"], "0.4.0-spike")
        self.assertEqual(proposed["status"], "unvalidated-experimental-proposal")
        self.assertEqual(
            [row["code"] for row in proposed["topics"]],
            [row["code"] for row in baseline["topics"]],
        )
        self.assertEqual(
            [row["code"] for row in proposed["events"]],
            [row["code"] for row in baseline["events"]],
        )
        self.assertEqual(manifest["approval"], "awaiting_user_review")
        self.assertEqual(manifest["live_requests"], 0)
        self.assertEqual(
            hashlib.sha256(TARGET.read_bytes()).hexdigest(), manifest["proposal_sha256"]
        )
        self.assertEqual(json.loads(MANIFEST.read_text(encoding="utf-8")), manifest)


if __name__ == "__main__":
    unittest.main()
