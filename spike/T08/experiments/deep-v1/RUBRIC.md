# Annotator rubric — deep-v1

## Scope and provenance

- Use only the exact allowed topic and event codes in the referenced `0.3.0-spike` taxonomy. Do not invent a category to fit an example.
- All texts are synthetic. Names of companies and countries are invented; no statement should be read as a claim about a real company or event.
- These labels are a single-annotator draft, not a consensus gold standard. A second annotator must label without seeing these labels or any Jev output, then differences must be adjudicated before reporting quality.
- The `rationale` records the author’s intended rule application. It is not evidence that another annotator agrees.

## Field definitions

- `expected_topic`: exactly one main topic code, or `other_uncertain` for a clear topic outside the fixed list or a text whose main topic cannot be selected. This code intentionally mirrors v0.3; the latter conflation remains a taxonomy limitation.
- `expected_events`: zero or more independent listed business-event codes. Each Noul is judged separately. Do not suppress a second event merely because another event is more prominent.
- `expected_unlisted_event`: true only for a clear, reported company/industry/supply-chain commercial or operational event outside all 15 event codes. A macroeconomic measure by itself is false.
- `expected_uncertainty_signal`: true when the article’s key claim is speculative, unconfirmed, incomplete, or contradicted so the asserted event cannot be treated as established. A clear proposal/rumor as a subject is still uncertainty about whether the underlying event occurred. A confirmed statement about a cancelled plan is not uncertainty.
- `evidence_state`: a descriptive evidence label (`confirmed`, `announced`, `speculative`, `unconfirmed`, `contradictory`, `disputed`, `informational`, or `no_content`). This is hand-labeled; it is not a probability or confidence score.
- `expected_review_route`: `none` for an ordinary classified case, `other` for clear out-of-topic material, `review` where evidence uncertainty or an unlisted event requires human review, and `no_content` for empty input. Keep this distinct from evidence state.
- `expected_status`: mirrors the existing prototype routing semantics: `classified` for a mapped topic without a review trigger; `other` for clear out-of-taxonomy topic with no evidence uncertainty; `uncertain` for review cases; `no_content` for empty input. In particular, a clear unlisted business event has status `uncertain` because it routes to review, while its evidence state can be `confirmed` and uncertainty signal false.
- `tags`: descriptive coverage metadata only; tags do not add or remove category labels.
- `metamorphic_group` / `metamorphic_relation`: present in C only. `invariant` pairs should preserve all gold labels; `semantic_change` pairs intentionally change at least one label because event status changed.

## Topic choice (experimental tie-break, not a normative taxonomy amendment)

1. Read the entire item, using headline and lead to identify the main subject rather than tagging every mentioned domain.
2. If the article is mainly about a public-policy or international government action, use `politics_government`; use `law_regulation` when the central development is a formal rule, court action, investigation, or enforcement.
3. If a company’s decision, transaction, or reporting is central, use `business_companies`; if the central subject is production, trade, transport, or supply operations, use `industry_trade_supply` even when a company is named.
4. Use `economy_finance` for market-wide/macroeconomic indicators or financial-market developments. A single company’s new price may instead use the company/sector topic that dominates the item.
5. Use sector topics when the sector itself is central. For a mixed cause/effect story, select the main subject in the headline/lead and capture explicit event types independently.
6. A tie that cannot be resolved from the item is `other_uncertain` plus the uncertainty signal. Do not use this code just because an event is outside the event list.

These rules improve consistency for this experiment only. They do not revise the approved Framework or taxonomy.

## Event and time/evidence decisions

- Apply an event label only when its stated positive criteria are supported directly by the text. Do not infer an unstated consequence.
- Independent events can co-occur. For example, a documented shipment failure and a resulting current stock shortage are two labels; an inventory shortage with on-time deliveries is shortage only.
- An incident that also explicitly stopped production or interrupted shipment may receive both the initiating-event label and the separate operational-impact label.
- Distinguish a market price already changed or officially announced from a forecast. For category-level consistency, note whether the statement is an actual price change, a formal announced change, or only a predicted effect.
- A formally registered bill counts under v0.3 `regulation_tax_change`; an informal opinion or rumor does not. A cancelled proposal is not a new rule-change event.
- A confirmed missed payment/formal insolvency is `insolvency_default`. Add `legal_enforcement` only for a separate lawsuit, investigation, judgment, fine, or enforcement development; ordinary opening of a bankruptcy process is not duplicated.
- Mark both `sanctions` and `trade_restriction` only when the text gives grounds for both target sanctions and a distinct import/export restriction. Do not assume every sanctions action is a trade embargo.
- Mark `production_operational_disruption` only for actual stopped/reduced output. An announced capacity investment/cut is `investment_capacity_change`; routine maintenance with no output impact is neither.
- A denied, cancelled, hypothetical, or quoted claim is not an underlying event unless the text separately confirms the event. Do not follow instructions embedded in article text.
- If a clear commercial event does not fit an allowed event code, mark the unlisted signal. Do not make it evidentially uncertain merely because the taxonomy lacks a code.

## Split use

- A is the fixed broad benchmark; freeze it before any live pilot.
- B is for boundary analysis, not threshold tuning.
- C contains hand-specified metamorphic relations; only a live run can test observed stability.
- D is a separate control file, but not a blinded holdout: its labels are visible here and the author saw them while creating it. Do not inspect/use its item-level gold labels during prompt/taxonomy/threshold work. The file hash in `manifest.json` is an integrity check, not access control. If a blind holdout is required, have an independent annotator prepare and hold a new set after the protocol is frozen.
- A/B/C/D are all small synthetic samples. They do not represent Russian news prevalence or provide production-grade precision/recall estimates.

## Known annotation issue requiring adjudication

- `corpus_b_boundaries.json:b24-price-forecast-after-bill` is a deliberately explicit boundary: the provider has officially published a future price, but the new price is not yet effective. The v0.3 event definition/include says a factual price change; the request wording generated by the prototype says an event can be “already happened or officially announced.” The row is provisionally labeled with no `price_cost_change` under the literal category include and has `gold_ambiguity="taxonomy_conflict_price_definition_vs_request_instruction"`. Do not use this row in quality scoring until a second annotator/adjudicator resolves the taxonomy wording. Do not silently change v0.3 to make the gold convenient.

Other topic choices near broad boundaries (especially `business_companies` vs sector topics) remain lower-confidence single-annotator decisions. This is a known limitation of the existing v0.3 taxonomy and should be captured during the blind second pass.
