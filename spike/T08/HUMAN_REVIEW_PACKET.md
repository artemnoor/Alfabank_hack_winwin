# Human review packet — draft gold adjudication

**Purpose:** ask a human reviewer to decide whether the source labels match the article text and the intended taxonomy. Do not treat an AI reviewer or Jev output as gold. The original `corpus.json` remains unchanged; any accepted label change requires a new dataset version and manifest.

## Review procedure and limits

- For e33/e34/e35, an AI subagent first read the three synthetic texts without the Jev answers or current expected labels, wrote its proposed labels and evidence, then saw the taxonomy and original labels. This provides a blind-to-model preliminary opinion, not independent human annotation.
- The same AI reviewer was not a real second annotator. The rest of the audit is not claimed to be blind human gold.
- Please make the final decisions below from the text and definitions. If more than one label is valid, cite a separate evidence span for each.
- Proposed labels for a future corpus must remain **pending** until a human approves them. Do not overwrite v0.3 labels in place.

## Priority cases

### e33 — price and rubber shortage

- **Current draft topic:** `economy_finance`.
- **Current draft events:** `price_cost_change`, `shortage_capacity_constraint`.
- **AI reviewer, before seeing Jev/gold:** topic `industry_trade_supply`; both events are supported.
- **Evidence noted by reviewer:** “фактической нехватке каучука”; “повысил действующую закупочную цену на 9 процентов”.
- **Disagreement:** topic is plausibly physical supply vs economic price framing. The shortage criterion says explicit insufficiency; this text appears to state it directly, but needs human confirmation against the actual wording.
- **Jev comparison, shown only after the blinded opinion:** topic `industry_trade_supply`; Jev omitted `shortage_capacity_constraint` and retained `price_cost_change`.
- **Human decision needed:** choose topic; confirm whether both events are directly supported; identify evidence span for each; state whether the price increase is already effective.

### e34 — missed debt payment and creditor filing

- **Current draft topic:** `law_regulation`.
- **Current draft events:** `insolvency_default`, `legal_enforcement`.
- **AI reviewer, before seeing Jev/gold:** same topic and both events.
- **Evidence noted by reviewer:** “пропустила платеж по долгу”; “кредитор подал в суд заявление…; судебная процедура начата”.
- **Reasoning:** a missed payment supports default; the separate court filing/proceeding can support legal enforcement. A court outcome or finding of wrongdoing is not required if the taxonomy is about formal action.
- **Jev comparison, shown only after the blinded opinion:** Jev retained `insolvency_default` but omitted `legal_enforcement`.
- **Human decision needed:** confirm each event independently and mark two non-overlapping evidence spans.

### e35 — investment and planned hiring

- **Current draft topic:** `business_companies`.
- **Current draft events:** `investment_capacity_change`, `labor_workforce_event`.
- **AI reviewer, before seeing Jev/gold:** investment is supported; labor label is debatable because a plan to hire 400 people may or may not count as a material workforce event under the current definition. Topic `industry_trade_supply` or `business_companies` both plausible.
- **Evidence quote:** “Компания сообщила, что после открытия наймёт 400 работников.”
- **Evidence/status:** this is a future hiring plan, not completed hiring. There is no current Jev response: its request failed, so no model comparison exists.
- **Human decision needed:** choose topic; decide whether approved future hiring qualifies as labor event, and what level of commitment is required; distinguish plan, approved plan, and actual hiring.

## Additional topic adjudication

These cases were identified as plausible gold/taxonomy disagreements. The Jev outputs are deliberately omitted from the decision prompts below; inspect the source news and choose a topic based on the main subject, not the model answer.

| Case | Current draft topic | Question for human reviewer |
|---|---|---|
| e10 `trade-import` | `law_regulation` | Is the main subject an import duty/legal rule or a restriction on cross-border trade? Could the two categories be separated by the article’s framing? |
| e14 `regulation-tax` | `economy_finance` | Is the article chiefly about an economic effect or the legal/tax rule itself? |
| e18 `labor-layoffs` | `business_companies` | Is workforce reduction the main subject, making `labor_employment` a better topic? Are both labor and corporate restructuring independently supported? |
| e28 `disaster-drought` | `energy_resources` | Does the article chiefly concern drought/environment, resource limits, or factory operations? Is the water restriction an environmental event, a regulatory event, or both? |
| e45 `injection-rumor` | `industry_trade_supply` | Does the article’s main subject concern the industry, technology product, or company? The instruction-like text inside the synthetic article is untrusted article content, not taxonomy control. |
| e47 `unlisted-contract-award` | `business_companies` | Is a public contract award a company/commercial topic, government/politics topic, or a new event outside the current event list? The text is clear; “out of list” should not automatically mean “insufficient evidence.” |

Other possible pairs for a later review: e09/e10, e13/e14, e18, e28, e30, e45. The exact cases and draft labels are in the pinned corpus; do not use the output of the current threshold sweep to change their labels.

## Resolution form

For each case, fill in:

1. **Topic code:** one allowed code, or “cannot decide” with reason.
2. **Event codes:** zero or more allowed codes, each supported by its own span.
3. **Evidence state:** confirmed / announced / speculative / unconfirmed / contradicted / no content (use the project’s agreed vocabulary).
4. **Out-of-list event:** yes/no; if yes, name the missing event in free text without creating a production code.
5. **Insufficient evidence:** yes/no, independent of whether the event is out of list.
6. **Evidence spans:** exact substring and offsets or sentence identifier; one span per claim.
7. **Rationale and confidence:** explain any overlap or uncertainty.

If reviewers disagree, preserve both annotations, ask a designated adjudicator, and record the final decision plus rationale in a new versioned corpus. If a category definition must change, freeze the current gold first and create a new annotation version tied to the new taxonomy hash.
