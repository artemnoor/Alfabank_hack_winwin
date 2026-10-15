"""Render one saved Jev case through the extraction adapter without network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
T08_DIR = ROOT / "spike" / "T08"
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(T08_DIR))
sys.path.insert(0, str(T08_DIR / "visualization"))

from alfalab_contracts import PreparedMaterial, Provenance, RawMaterial, SpanMap  # noqa: E402
from fact_extraction import (  # noqa: E402
    ExtractedMention,
    ExtractionContext,
    run_t08_to_t09,
)
from fact_extraction.binding import load_experiment_binding  # noqa: E402


PILOT_DIR = T08_DIR / "experiments" / "jev-expanded-pilot-v1"
FIXTURE_PATH = Path(__file__).with_name("fixtures") / "nb-003-extraction-fixture.json"
CASE_ID = "nb-003"
RECORDED_AT = "2026-10-15T10:00:00Z"


class OfflineFixtureExtractor:
    """Deterministic hand-authored response; this class makes no model calls."""

    def __init__(self, mentions: list[ExtractedMention]):
        self.mentions = mentions

    def extract_candidate(
        self, *, case_id: str, article_text: str, classification: dict, candidate
    ) -> list[ExtractedMention]:
        del case_id, article_text, classification, candidate
        return self.mentions


def sha256_text(value: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    news = json.loads((PILOT_DIR / "news.json").read_text(encoding="utf-8"))
    saved_jev = json.loads(
        (PILOT_DIR / "live-results.json").read_text(encoding="utf-8")
    )
    taxonomy = json.loads((T08_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if (
        fixture.get("not_provider_output") is not True
        or fixture.get("case_id") != CASE_ID
    ):
        raise SystemExit("offline fixture marker or case id is invalid")
    article = next(row for row in news["cases"] if row["id"] == CASE_ID)
    classification = next(
        row for row in saved_jev["results"] if row["case_id"] == CASE_ID
    )
    text = article["text"]
    digest = sha256_text(text)
    provenance = Provenance(
        origin="synthetic",
        source_refs=[],
        input_statement_refs=[],
        producer_run_id=None,
        derivation_method=None,
        evidence_refs=[],
        origin_verified=True,
    )
    raw = RawMaterial(
        material_id=CASE_ID,
        source_id=None,
        source_url=None,
        title=article["title"],
        text=text,
        published_at=None,
        collected_at=RECORDED_AT,
        content_hash=digest,
        language="ru",
        provenance=provenance,
    )
    prepared = PreparedMaterial(
        material=raw,
        raw_hash=digest,
        prepared_hash=digest,
        quality="valid",
        span_map=[
            SpanMap(
                prepared_start=0, prepared_end=len(text), raw_start=0, raw_end=len(text)
            )
        ],
        warnings=[],
    )
    mentions = [
        ExtractedMention.model_validate(row, strict=True) for row in fixture["mentions"]
    ]
    result = run_t08_to_t09(
        prepared=prepared,
        classification=classification,
        taxonomy=taxonomy,
        extractor=OfflineFixtureExtractor(mentions),
        binding=load_experiment_binding(),
        context=ExtractionContext(
            case_id=CASE_ID,
            recorded_at=RECORDED_AT,
            origin="synthetic",
            origin_verified=True,
            source_refs=[],
            producer_run_id=None,
        ),
    )
    print(
        "OFFLINE ONLY: extractor fixture, not DeepSeek output; no network requests made."
    )
    print(f"Saved Jev candidate(s): {', '.join(result.candidate_codes) or '(none)'}")
    print(f"Pipeline status: {result.status}")
    print(
        json.dumps(result.output.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
