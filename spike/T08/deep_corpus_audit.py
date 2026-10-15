"""Offline structural audit for the frozen synthetic deep-v1 corpus."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from stable_hash import sha256_text_file

from jev_spike import SPIKE_DIR

DEEP_DIR = SPIKE_DIR / "experiments" / "deep-v1"
MANIFEST_PATH = DEEP_DIR / "manifest.json"
OUTPUT_PATH = SPIKE_DIR / "DEEP_CORPUS_AUDIT.json"
NEAR_DUPLICATE_THRESHOLD = 0.92


def _sha256(path: Path) -> str:
    return sha256_text_file(path)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must be a JSON object")
    return value


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE))


def build_audit() -> dict[str, Any]:
    manifest = _load_object(MANIFEST_PATH)
    taxonomy_path = SPIKE_DIR / "taxonomy.json"
    corpus_path = SPIKE_DIR / "corpus.json"
    expected_topics = {item["code"] for item in _load_object(taxonomy_path)["topics"]}
    expected_events = {item["code"] for item in _load_object(taxonomy_path)["events"]}
    split_results: dict[str, Any] = {}
    all_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for split, spec in manifest["splits"].items():
        path = DEEP_DIR / spec["path"]
        if _sha256(path) != spec["sha256"]:
            raise ValueError(f"pinned {split} split hash does not match")
        document = _load_object(path)
        if document.get("split") != split:
            raise ValueError(f"{split} split marker does not match its manifest")
        cases = document.get("cases")
        if not isinstance(cases, list) or len(cases) != spec["cases"]:
            raise ValueError(f"{split} case count does not match its manifest")
        ids = [case.get("id") for case in cases]
        if any(not isinstance(case_id, str) or not case_id for case_id in ids):
            raise ValueError(f"{split} has an invalid case id")
        if len(set(ids)) != len(ids) or seen_ids.intersection(ids):
            raise ValueError("duplicate case id across deep-v1 splits")
        seen_ids.update(ids)
        for case in cases:
            if not all(
                key in case
                for key in (
                    "title",
                    "text",
                    "expected_topic",
                    "expected_events",
                    "expected_status",
                    "evidence_state",
                )
            ):
                raise ValueError(f"{case['id']} is missing a required annotation field")
            if (
                case["expected_topic"] is not None
                and case["expected_topic"] not in expected_topics
            ):
                raise ValueError(f"{case['id']} has an unknown topic label")
            if not set(case["expected_events"]).issubset(expected_events):
                raise ValueError(f"{case['id']} has an unknown event label")
            case["_split"] = split
            all_cases.append(case)
        if (
            "nonempty_cases" in spec
            and sum(bool(case["text"].strip()) for case in cases)
            != spec["nonempty_cases"]
        ):
            raise ValueError(f"{split} nonempty count does not match manifest")
        split_results[split] = {
            "case_count": len(cases),
            "nonempty_count": sum(bool(case["text"].strip()) for case in cases),
            "sha256_verified": True,
            "blind": bool(spec.get("blind", False)),
            "holdout": bool(spec.get("holdout", False)),
            "scored_or_used_for_thresholds": False,
        }

    near_pairs: list[dict[str, Any]] = []
    normalized_by_id: dict[str, str] = {}
    exact_by_text: dict[str, list[str]] = {}
    for case in all_cases:
        normalized = _normalise(f"{case['title']} {case['text']}")
        normalized_by_id[case["id"]] = normalized
        exact_by_text.setdefault(normalized, []).append(case["id"])
    exact_duplicates = [ids for ids in exact_by_text.values() if len(ids) > 1]
    ids = list(normalized_by_id)
    for index, first_id in enumerate(ids):
        first = normalized_by_id[first_id]
        if not first:
            continue
        for second_id in ids[index + 1 :]:
            second = normalized_by_id[second_id]
            if not second:
                continue
            similarity = SequenceMatcher(None, first, second, autojunk=False).ratio()
            if similarity >= NEAR_DUPLICATE_THRESHOLD:
                near_pairs.append(
                    {
                        "case_ids": [first_id, second_id],
                        "similarity": round(similarity, 4),
                    }
                )

    topic_coverage = Counter(
        case["expected_topic"]
        for case in all_cases
        if case["expected_topic"] is not None
    )
    event_coverage = Counter(
        code for case in all_cases for code in set(case["expected_events"])
    )
    split_case_counts = Counter(case["_split"] for case in all_cases)
    evidence_states = Counter(case["evidence_state"] for case in all_cases)
    statuses = Counter(case["expected_status"] for case in all_cases)
    empty_ids = [case["id"] for case in all_cases if not case["text"].strip()]
    source_corpus = _load_object(corpus_path)
    return {
        "audit_version": "1.0.0-spike",
        "manifest_sha256": _sha256(MANIFEST_PATH),
        "source_corpus_sha256": _sha256(corpus_path),
        "taxonomy_sha256": _sha256(taxonomy_path),
        "corpus_id": manifest["corpus_id"],
        "version": manifest["version"],
        "total_cases": len(all_cases),
        "nonempty_cases": sum(bool(case["text"].strip()) for case in all_cases),
        "empty_case_ids": empty_ids,
        "split_counts": dict(sorted(split_case_counts.items())),
        "split_audit": split_results,
        "topic_label_counts": {
            code: topic_coverage.get(code, 0) for code in sorted(expected_topics)
        },
        "event_label_counts": {
            code: event_coverage.get(code, 0) for code in sorted(expected_events)
        },
        "uncovered_topic_codes": sorted(expected_topics - topic_coverage.keys()),
        "uncovered_event_codes": sorted(expected_events - event_coverage.keys()),
        "expected_status_counts": dict(sorted(statuses.items())),
        "evidence_state_counts": dict(sorted(evidence_states.items())),
        "exact_duplicate_text_groups": exact_duplicates,
        "near_duplicate_pairs_at_or_above_threshold": near_pairs,
        "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
        "near_duplicate_method": "SequenceMatcher over casefolded Unicode word tokens from title+text; heuristic flags require human review.",
        "known_annotation_ambiguities": manifest.get(
            "known_annotation_ambiguities", []
        ),
        "original_baseline_unchanged": _sha256(corpus_path)
        == manifest["baseline_preservation_reference"]["sha256"],
        "jev_calls": 0,
        "gold_status": manifest["status"],
        "d_split_status": "visible_nonblind_control; excluded from tuning and scoring",
        "not_a_blind_holdout": manifest["splits"]["D"].get("blind") is False,
        "source_baseline_metadata": {
            "corpus_id": source_corpus.get("corpus_id"),
            "version": source_corpus.get("version"),
        },
        "limitations": [
            "All labels are single-author drafts; no independent human adjudication is present.",
            "Deep split D is visible in the repository and has been seen by its author; it is not a blind test set.",
            "Near-duplicate flags are lexical heuristics, not semantic duplicate judgments.",
            "Coverage counts describe annotations only and are not classifier scores.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        target = args.output.resolve()
        root = SPIKE_DIR.resolve()
        if target != root and root not in target.parents:
            raise ValueError("output must remain inside spike/T08")
        encoded = (
            json.dumps(build_audit(), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        if args.check:
            if not target.is_file() or target.read_bytes() != encoded:
                raise ValueError(
                    "deep corpus audit output is missing or not reproducible"
                )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encoded)
        print(f"DEEP_CORPUS_AUDIT={target.relative_to(root)}")
        return 0
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
