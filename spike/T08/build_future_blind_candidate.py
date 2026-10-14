"""Validate new unlabelled inputs intended for future prospective evaluation."""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "experiments" / "future-blind-candidate-v1"
NEWS = DATA_DIR / "news.json"
MANIFEST = DATA_DIR / "manifest.json"
BASELINE_TAXONOMY_SHA256 = (
    "855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d"
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _all_existing_texts() -> list[str]:
    documents = [json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))]
    deep_root = ROOT / "experiments" / "deep-v1"
    deep_manifest = json.loads(
        (deep_root / "manifest.json").read_text(encoding="utf-8")
    )
    for split in deep_manifest["splits"].values():
        documents.append(
            json.loads((deep_root / split["path"]).read_text(encoding="utf-8"))
        )
    visible = ROOT / "experiments" / "visible-validation-v1" / "news.json"
    documents.append(json.loads(visible.read_text(encoding="utf-8")))
    return [
        " ".join(case["text"].casefold().split())
        for document in documents
        for case in document["cases"]
        if case.get("text", "").strip()
    ]


def build_manifest() -> dict[str, Any]:
    raw = NEWS.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    cases = document.get("cases")
    if document.get("dataset_id") != "t08-future-blind-candidate-inputs":
        raise ValueError("unexpected candidate dataset id")
    if document.get("version") != "1.0.0" or not isinstance(cases, list):
        raise ValueError("candidate corpus version or shape is invalid")
    if len(cases) != 40:
        raise ValueError("future candidate corpus must contain exactly 40 cases")
    ids = [case.get("id") for case in cases]
    texts = [" ".join(case.get("text", "").casefold().split()) for case in cases]
    if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
        raise ValueError("candidate IDs and normalized texts must be unique")
    if any(set(case) != {"id", "title", "text"} for case in cases):
        raise ValueError("candidate input must not contain gold/model-output fields")
    if any(
        not all(case[key].strip() for key in ("id", "title", "text")) for case in cases
    ):
        raise ValueError("candidate IDs, titles, and texts must be non-empty")

    existing_texts = _all_existing_texts()
    maximum_similarity = max(
        SequenceMatcher(None, text, old).ratio()
        for text in texts
        for old in existing_texts
    )
    if maximum_similarity >= 0.72:
        raise ValueError("candidate text is too similar to an existing T08 corpus")
    return {
        "dataset_id": document["dataset_id"],
        "version": document["version"],
        "status": "awaiting_independent_human_annotation",
        "cases": len(cases),
        "language": "ru_with_one_mixed_language_case",
        "content_origin": "new synthetic input authored offline; no real news",
        "derived_from_jev_outputs": False,
        "selected_from_current_error_cases": False,
        "gold_labels_present": False,
        "model_outputs_present": False,
        "human_annotators": 0,
        "eligible_for_current_scoring": False,
        "genuinely_blind_now": False,
        "blindness_limit": (
            "Inputs are visible in the repository. Prospective label-blind use "
            "requires frozen taxonomy/prompt/policy, two independent human labels, "
            "third-person adjudication, and an external custodian holding labels "
            "until Jev output hashes are fixed."
        ),
        "baseline_taxonomy_version": "0.3.0-spike",
        "baseline_taxonomy_sha256": BASELINE_TAXONOMY_SHA256,
        "news_path": "spike/T08/experiments/future-blind-candidate-v1/news.json",
        "news_sha256": _sha256(raw),
        "maximum_similarity_to_existing_t08_texts": round(maximum_similarity, 6),
        "new_jev_requests": 0,
    }


def write_manifest() -> dict[str, Any]:
    result = build_manifest()
    MANIFEST.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    manifest = write_manifest()
    print(f"CANDIDATE_CASES={manifest['cases']}")
    print(f"INPUT_SHA256={manifest['news_sha256']}")
    print(
        f"MAX_EXISTING_SIMILARITY={manifest['maximum_similarity_to_existing_t08_texts']}"
    )
