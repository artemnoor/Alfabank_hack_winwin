"""Integrity checks for the separately versioned synthetic deep-v1 corpus.

These tests validate labels and metamorphic relations in A/B/C. The D holdout is
only checked against its manifest digest and declared case count; its labels are
never fed to an evaluator or threshold sweep.
"""

from __future__ import annotations

import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jev_spike import (
    TRUSTED_CORPUS_SHA256,
    TRUSTED_TAXONOMY_SHA256,
    load_pinned_json,
    validate_taxonomy,
)
from stable_hash import sha256_text_file

DEEP_DIR = Path(__file__).resolve().parent / "experiments" / "deep-v1"
MANIFEST_PATH = DEEP_DIR / "manifest.json"
BASE_DIR = Path(__file__).resolve().parent
TRUSTED_DEEP_MANIFEST_SHA256 = (
    "eb746655045ccb9ec6baabbc34cd3d396d13755c5b6548bfe8228349ea3fb0d0"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object in {path.name}")
    return value


def _label_signature(case: dict[str, Any]) -> tuple[Any, ...]:
    return (
        case["expected_topic"],
        tuple(sorted(case["expected_events"])),
        case["expected_unlisted_event"],
        case["expected_uncertainty_signal"],
        case["expected_review_route"],
        case["expected_status"],
    )


class DeepCorpusIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = _read_json(MANIFEST_PATH)
        cls.taxonomy = load_pinned_json(
            BASE_DIR / "taxonomy.json", TRUSTED_TAXONOMY_SHA256
        )
        cls.baseline = load_pinned_json(BASE_DIR / "corpus.json", TRUSTED_CORPUS_SHA256)
        validate_taxonomy(cls.taxonomy)

    def _load_split(self, key: str) -> list[dict[str, Any]]:
        entry = self.manifest["splits"][key]
        path = DEEP_DIR / entry["path"]
        raw = path.read_bytes()
        self.assertEqual(sha256_text_file(path), entry["sha256"])
        document = json.loads(raw.decode("utf-8"))
        self.assertEqual(document["split"], key)
        self.assertEqual(document["taxonomy_version"], self.taxonomy["version"])
        self.assertEqual(document["taxonomy_sha256"], TRUSTED_TAXONOMY_SHA256)
        self.assertEqual(document["status"], "hand-labeled-synthetic-evaluation")
        cases = document["cases"]
        self.assertEqual(len(cases), entry["cases"])
        return cases

    def test_deep_corpus_has_160_cases_and_pins_unchanged_baseline(self) -> None:
        self.assertEqual(
            sha256_text_file(MANIFEST_PATH),
            TRUSTED_DEEP_MANIFEST_SHA256,
        )
        self.assertEqual(self.manifest["total_cases"], 160)
        self.assertEqual(self.manifest["nonempty_cases"], 158)
        self.assertEqual(
            self.manifest["baseline_preservation_reference"]["sha256"],
            TRUSTED_CORPUS_SHA256,
        )
        self.assertEqual(len(self.baseline["cases"]), 50)
        self.assertEqual(sum(key in self.manifest["splits"] for key in "ABCD"), 4)
        self.assertTrue(self.manifest["splits"]["D"]["holdout"])
        self.assertFalse(self.manifest["splits"]["D"]["blind"])
        self.assertIn("not a blind holdout", self.manifest["splits"]["D"]["purpose"])
        self.assertTrue(
            all(not self.manifest["splits"][key]["holdout"] for key in "ABC")
        )
        self.assertEqual(
            {key: self.manifest["splits"][key]["cases"] for key in "ABCD"},
            {"A": 76, "B": 36, "C": 24, "D": 24},
        )

    def test_splits_a_b_c_have_valid_codes_labels_and_unique_ids(self) -> None:
        topic_codes = {row["code"] for row in self.taxonomy["topics"]}
        event_codes = {row["code"] for row in self.taxonomy["events"]}
        ids: set[str] = set()
        for split in "ABC":
            cases = self._load_split(split)
            self.assertTrue(cases)
            for case in cases:
                with self.subTest(case_id=case.get("id")):
                    self.assertTrue(case["id"] not in ids)
                    ids.add(case["id"])
                    self.assertIsInstance(case["title"], str)
                    self.assertIsInstance(case["text"], str)
                    if case["expected_status"] == "no_content":
                        self.assertIsNone(case["expected_topic"])
                        self.assertEqual(case["expected_review_route"], "no_content")
                        self.assertFalse(case["title"].strip() or case["text"].strip())
                    else:
                        self.assertIn(case["expected_topic"], topic_codes)
                    self.assertTrue(set(case["expected_events"]).issubset(event_codes))
                    self.assertEqual(
                        len(case["expected_events"]), len(set(case["expected_events"]))
                    )
                    self.assertIsInstance(case["expected_unlisted_event"], bool)
                    self.assertIsInstance(case["expected_uncertainty_signal"], bool)
                    self.assertIn(
                        case["expected_review_route"],
                        {"none", "other", "review", "no_content"},
                    )
                    status_route = {
                        "classified": "none",
                        "uncertain": "review",
                        "other": "other",
                        "no_content": "no_content",
                    }
                    self.assertEqual(
                        case["expected_review_route"],
                        status_route[case["expected_status"]],
                    )
                    self.assertIsInstance(case["rationale"], str)
                    self.assertTrue(case["rationale"].strip())
                    self.assertIn("synthetic", case["tags"])
                    self.assertIn(f"split:{split.lower()}", case["tags"])
        self.assertEqual(len(ids), 136)

    def test_holdout_d_is_digest_checked_but_never_loaded_for_scoring(self) -> None:
        entry = self.manifest["splits"]["D"]
        raw = (DEEP_DIR / entry["path"]).read_bytes()
        self.assertEqual(sha256_text_file(DEEP_DIR / entry["path"]), entry["sha256"])
        declared = json.loads(raw.decode("utf-8"))
        self.assertEqual(declared["split"], "D")
        self.assertEqual(len(declared["cases"]), entry["cases"])
        self.assertTrue(entry["holdout"])
        # Deliberately do not read per-case labels into the evaluation helpers.

    def test_every_event_has_four_gold_positives_in_benchmark_split(self) -> None:
        cases = self._load_split("A")
        counts = Counter(code for case in cases for code in case["expected_events"])
        expected = {row["code"] for row in self.taxonomy["events"]}
        self.assertEqual(set(counts), expected)
        self.assertTrue(all(count >= 4 for count in counts.values()))

    def test_boundary_pairs_have_four_explicit_cases_each(self) -> None:
        cases = self._load_split("B")
        pair_tags = [
            "boundary:sanctions_trade",
            "boundary:insolvency_legal",
            "boundary:supply_shortage",
            "boundary:production_investment",
            "boundary:regulation_legal",
            "boundary:price_regulation",
        ]
        tags = Counter(tag for case in cases for tag in case["tags"])
        for tag in pair_tags:
            with self.subTest(boundary=tag):
                self.assertEqual(tags[tag], 4)

    def test_metamorphic_pairs_preserve_or_change_gold_as_declared(self) -> None:
        cases = self._load_split("C")
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in cases:
            self.assertIn(
                case["metamorphic_relation"], {"invariant", "semantic_change"}
            )
            grouped[case["metamorphic_group"]].append(case)
        self.assertEqual(set(grouped), {f"m{index:02d}" for index in range(1, 13)})
        for group, pair in grouped.items():
            with self.subTest(group=group):
                self.assertEqual(len(pair), 2)
                relations = {case["metamorphic_relation"] for case in pair}
                self.assertEqual(len(relations), 1)
                signatures = {_label_signature(case) for case in pair}
                if relations == {"invariant"}:
                    self.assertEqual(len(signatures), 1)
                else:
                    self.assertEqual(len(signatures), 2)


if __name__ == "__main__":
    unittest.main()
