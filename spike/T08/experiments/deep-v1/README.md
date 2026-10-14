# T08 deep synthetic evaluation set v1.0.0

This directory is an isolated research artifact for the T08 Jev classification spike. It does not change the v0.3.0-spike taxonomy, original `synthetic-ru-news-50` corpus, runner, production runtime, or public contracts. Every news item, company, and fictional country in these files is invented. No real article, Jev answer, model-generated label, network response, or production dataset was used to write the gold labels.

## Files and splits

- `corpus_a_benchmark.json` — 76 fixed benchmark cases (75 non-empty, 1 empty): broad positive coverage for all 15 event codes, topic controls, clear out-of-topic material, clear unlisted business events, and one conflicting claim.
- `corpus_b_boundaries.json` — 36 boundary cases: four examples for each of the six requested category pairs, plus rumor, denial, proposal, cancellation, allegation, conflict, and misleading-headline examples.
- `corpus_c_robustness.json` — 24 planned metamorphic cases. Groups `m01`–`m06` and `m12` expect invariant labels under a non-semantic change; `m07`–`m11` are five pairs where changing the asserted event state should change the gold. These are stimuli and expected relations; they have not been run against Jev.
- `holdout_d_control.json` — 24 separate control cases. It is not included in A/B/C and must not be used for prompt wording, threshold selection, or taxonomy revision. It has one positive example per event plus nine controls/challenges; this size is not enough for reliable category estimates. Its labels are visible in this repository and were seen by the corpus author, so it is **not a blind holdout**. Use a separately held, independently authored control set after the protocol is frozen if blinded evaluation is required.
- `RUBRIC.md` — annotation procedure and field semantics.
- `manifest.json` — file hashes, split counts, and the exact v0.3 taxonomy/original corpus hashes used as references.

Do not concatenate or glob all JSON files for tuning: the D file is deliberately separate. The manifest records its digest so later evaluation can verify that it remained unchanged. The current offline validator checks only D's file hash, split name, and declared row count; it does not score D or pass it to threshold tuning.

## Gold-label status

Gold labels are a single-annotator draft created independently of Jev responses. They require a blind second independent human pass and adjudication before they can support a model-quality claim. The rationale states the intended boundary for each row. Any unresolved judgment must be marked as an annotation issue, not “fixed” using model output.

`expected_uncertainty_signal` and `expected_review_route` answer different questions. The first describes uncertainty in the article’s evidence. The second describes the operational destination. A clear, confirmed event outside the allowed list can have `expected_unlisted_event=true`, `expected_uncertainty_signal=false`, and `expected_review_route="review"`: the facts are clear, but the event cannot be represented by one of the listed event codes. This is also why `expected_status="uncertain"` can mean “needs review” in the existing spike evaluator; it does not always mean the facts are uncertain.

No Jev/API quality, live behavior, latency, or model stability result is implied by these hand-authored cases. Use them only after the official API works and a permitted live budget is established. Keep a copy of the exact manifest and evaluator settings with any later pilot.
