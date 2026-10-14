# Offline audit of T08 taxonomy v0.3.0-spike

## Scope and evidence

This review covers the 11 topic choices, 15 event questions, annotation rules, and manually assigned gold labels in **spike/T08/taxonomy.json** and **spike/T08/corpus.json** at taxonomy version **0.3.0-spike**. The corpus has 49 synthetic news items and one empty-input case.

This is a human-authored, offline review. No Jev request, classifier, model, or network was used. All example headlines below are short references to synthetic corpus cases or newly authored illustrative examples. Nothing here is evidence of Jev accuracy. Gold labels remain the current v0.3 labels; this document does not change them or the taxonomy.

The intended output shape is one main topic plus independently selected event labels. The out-of-list business-event signal and **insufficient_evidence** signal are separate questions. A clear topic can coexist with an uncertain event claim, as in e40. The status word **uncertain** needs a more exact definition: e47 has a clear, verified out-of-list business event and **expected_uncertainty_signal=false**, yet **expected_status=uncertain**; e50 is uncertain because its content is incomplete. Those two cases should not be treated as the same reason for uncertainty.

## Six business boundaries called out in the original request

| User example | Current intended distinction | Current corpus evidence | Audit note |
|---|---|---|---|
| Supply shortage | **shortage_capacity_constraint** requires an explicitly insufficient stock or capacity that constrains an operation. | e03 and e04 are positive; e01 is a shipment delay without an explicit stock shortage. | Keep a shortage separate from a late shipment. A case may receive both only when both insufficient stock/capacity and an actual supply-flow disruption are stated. |
| Fire | **production_operational_disruption** covers a fire that stops or substantially cuts production. | e06 is positive; e32 also has a fire and a delayed shipment. | A factory fire is not automatically an environmental event. Add **environment_disaster_impact** only for a stated natural hazard or ecological incident with business impact. An industrial fire with a stated spill or ecological damage could meet both rules; v0.3 has no such example. |
| Tariff | A tariff that constrains cross-border trade is **trade_restriction**; a general tax or rule change is **regulation_tax_change**. | e10 is a tariff/import restriction; e14 is a tax-law change. | The event rule excludes trade restrictions from **regulation_tax_change**. Add a boundary example for a tariff that changes costs but is not described as limiting imports, because current prose says “limits” and tariff use can vary. |
| Sanctions | **sanctions** requires a stated sanctions measure or target; **trade_restriction** requires an explicit cross-border goods restriction. | e11/e12 are sanctions; e09/e10 are trade restrictions; e31 explicitly supports both. | The two labels are compatible, not mutually exclusive. Do not infer a trade restriction from sanctions or sanctions from a trade measure. |
| Supplier bankruptcy | **insolvency_default** covers a formal bankruptcy process or an actual missed debt payment. | e19 and e20 are positive; e44 negates the rumor and is negative. | **legal_enforcement** is not a synonym for a court being mentioned. e34 deliberately adds it for a separate creditor filing after default. Preserve the explicit rule that distinguishes e19 from e34. |
| Price increase | **price_cost_change** requires an effective price/cost change; **shortage_capacity_constraint** requires a stated shortage or capacity limit. | e07/e08 are price changes; e03/e04 are shortages; e33 contains both. | A shortage does not imply a price rise, and a price rise does not prove a shortage. Apply both only when the text states both facts, without inferring causation. |

## Topic audit

For each topic, “positive” means an existing corpus item gold-labeled with that topic; “negative” means a nearby item whose topic gold is different. A negative is a useful contrast, not proof that the label is objectively settled.

### economy_finance — Экономика и финансы

- **Scope:** Macro indicators, monetary policy, markets, rates, finance, and general economic measures.
- **Positive:** e36, central bank lowers the key rate.
- **Negative:** e01, a shipment delay is about physical supply operations.
- **Hard boundary:** Company or industry price changes versus macro price/market reporting; financial distress versus a legal proceeding.
- **Likely Jev error:** Treating any number, price, bond, or tax mention as this topic, even when the article is chiefly about a company action or law.
- **v0.4 proposal:** State that the topic follows the main subject and framing, not the presence of financial vocabulary. Add matched articles where the same fact is framed as a macro trend versus a company-specific development.

### politics_government — Политика и государство

- **Scope:** Government action, state policy, and international relations when they are the article’s main subject.
- **Positive:** e11, an authority adds a company to a sanctions list.
- **Negative:** e20, a bond coupon is missed and the issuer reports default.
- **Hard boundary:** Government policy versus legal/regulatory instrument. e09 assigns an export quota to this topic, while e10 assigns an import duty to **law_regulation**; both concern official trade measures.
- **Likely Jev error:** Choosing this topic whenever a government or regulator is the grammatical actor, even if the story’s focus is a court process, a business impact, or a tax instrument.
- **v0.4 proposal:** Add a main-focus tie-break and paired government-action examples. Revisit e09/e10 together; do not silently change their current gold.

### business_companies — Компании и бизнес

- **Scope:** A specific company’s strategy, management, reporting, or commercial activity when a narrower topic/event does not dominate.
- **Positive:** e37, a company publishes quarterly revenue.
- **Negative:** e36, a central-bank rate decision is macroeconomic.
- **Hard boundary:** A company can be the actor without its topic being “business”; a labor, technology, legal, or supply story can concern a company and still have that narrower main topic.
- **Likely Jev error:** Overusing this broad topic whenever a company name appears.
- **v0.4 proposal:** Make this the residual company-centered topic only after testing whether a more specific topic captures the article’s main subject. Add examples where the company is merely affected or quoted.

### industry_trade_supply — Промышленность, торговля и поставки

- **Scope:** Production, physical trade, transport, and supply-chain activity.
- **Positive:** e01, containers of components are delayed at a rail terminal.
- **Negative:** e36, a national interest-rate decision.
- **Hard boundary:** Physical supply/production versus energy-resource subject matter; a shipping delay versus an actual shortage; a factory outage versus a supply interruption.
- **Likely Jev error:** Collapsing every industrial incident into this topic, or treating “trade” in a story as an official cross-border trade restriction.
- **v0.4 proposal:** Clarify that this is the primary topic for physical operations and flows, while event labels separately capture the specific disruption. Add paired production-only, supply-only, and energy-market cases.

### technology_telecom — Технологии и связь

- **Scope:** Technology products, software, telecom, and digital infrastructure.
- **Positive:** e15, ransomware disables a company’s internal order system.
- **Negative:** e01, a physical rail delivery is delayed.
- **Hard boundary:** A technology product defect/recall versus a technology-sector story; cyber events can be the event label while the main topic is technology, business, or another affected sector.
- **Likely Jev error:** Assigning this topic whenever a device, system, or digital service is mentioned, even when the article is chiefly about safety, regulation, or a company transaction.
- **v0.4 proposal:** Define a product/industry focus rule and include cross-sector device examples. Keep cyber incident as an event label independent of topic.

### energy_resources — Энергетика и ресурсы

- **Scope:** Electricity, fuel, extraction, and commodity resources.
- **Positive:** e04, a regional supplier lacks fuel-storage capacity.
- **Negative:** e01, a shipment of electronic components is delayed.
- **Hard boundary:** Energy/resource subject versus generic industrial input, supply-chain problem, or environment-driven operational impact. e28 is gold-labeled **energy_resources** for drought-related water restrictions at a plant, which is plausible but less direct than the stated electricity/fuel/extraction scope.
- **Likely Jev error:** Extending “resources” to every raw material, utility constraint, or environmental event.
- **v0.4 proposal:** Decide whether water/utilities and all raw materials belong here or whether the topic should stay limited to energy and extractive sectors. Add matched cases before revisiting e28.

### law_regulation — Право и регулирование

- **Scope:** Courts, rules, official investigations, and enforcement.
- **Positive:** e19, a court opens a supplier bankruptcy proceeding.
- **Negative:** e07, a supplier changes its active polymer price.
- **Hard boundary:** A legal mechanism versus the policy or economic effect it creates; official trade measures and tax-law changes also appear in this topic family.
- **Likely Jev error:** Choosing this topic for every official document, court mention, or government action, even when the story is chiefly about a business or economic outcome.
- **v0.4 proposal:** Separate “law/regulatory process is the subject” from “a policy changes business conditions”; add matched tariff, tax, sanctions, and court examples. Review e09/e10 and e13/e14 as pairs.

### labor_employment — Труд и занятость

- **Scope:** Jobs, working conditions, labor relations, strikes, and employment.
- **Positive:** e17, warehouse workers begin a strike.
- **Negative:** e01, a delivery is delayed without a labor action being stated.
- **Hard boundary:** An actual or formally announced workforce change versus a forecast, rumor, ordinary hiring, or a company closure/transaction that also affects workers.
- **Likely Jev error:** Tagging any mention of workers or headcount, or treating a possible future strike as an event.
- **v0.4 proposal:** Specify what makes a workforce change “substantial” and how a formal future announcement differs from ordinary hiring. Preserve e40 as an uncertainty example; review the positive labor label in e35 against that rule.

### environment_disasters — Экология и бедствия

- **Scope:** Environmental conditions, climate events, natural hazards, and ecological outcomes.
- **Positive:** e27, a flood closes factory access; e49, a reserve reports ecosystem recovery.
- **Negative:** e06, a factory fire stops a packaging line but no ecological harm is reported.
- **Hard boundary:** Environmental subject matter versus business impact from a hazard. Topic **environment_disasters** can be correct even when no business-event label applies, as in e49.
- **Likely Jev error:** Confusing every fire or industrial accident with an environmental event, or requiring a business impact for the broad topic.
- **v0.4 proposal:** Keep topic relevance separate from **environment_disaster_impact**; state whether a man-made pollution incident qualifies and require explicit ecological harm for that route.

### health — Здоровье

- **Scope:** Medicine, pharmaceuticals, and public health.
- **Positive:** e39, a medical association updates seasonal prevention guidance.
- **Negative:** e15, a ransomware incident affects an order system.
- **Hard boundary:** A consumer product safety issue versus a public-health or medical story. e24’s beverage recall is both a health-focused topic and a product-quality event.
- **Likely Jev error:** Assigning health to every food, medicine, or safety mention without determining whether health is the article’s main subject.
- **v0.4 proposal:** Add a rule for health consequences versus product quality, and paired medicine/recall/consumer-safety examples.

### other_uncertain — Другая тема или недостаточно данных

- **Scope:** The main topic is outside the named choices, or the text is too incomplete to choose reliably; a separate signal is intended to distinguish insufficient evidence.
- **Positive:** e46 is clearly about a theater exhibition outside the topic list; e50 contains only an unspecified decision and supports insufficient evidence.
- **Negative:** e45 has an unconfirmed recall rumor but a recognizable industry/supply topic. Its event uncertainty does not force **other_uncertain**.
- **Hard boundary:** Clear out-of-taxonomy content versus incomplete/ambiguous content. The current name and description combine these different reasons.
- **Likely Jev error:** Using **other_uncertain** as a generic low-confidence answer, or treating a clear but unlisted business event as insufficient evidence.
- **v0.4 proposal:** Separate topic **other** from the orthogonal **insufficient_evidence** signal. Reserve review status for explicit confidence/evidence rules rather than the word “other”.

## Event audit

Each event is independently multi-label. “Negative” examples below are cases where the event is not in the gold set, including near-misses; this does not assert that the case has no other relevant event.

### supply_chain_disruption — Сбой поставок

- **Scope:** An actual delay, failure, or interruption in delivery, transport, or supplier operation.
- **Positive:** e01, containers delayed at a rail terminal.
- **Negative:** e03, low raw-material stock limits production, without a stated failed or delayed delivery.
- **Hard boundary:** Actual disrupted flow versus insufficient inventory/capacity; both only when both are explicit.
- **Likely Jev error:** Inferring a supply disruption from shortage, risk, or a downstream production cut.
- **v0.4 proposal:** Require explicit evidence of an interrupted flow or supplier operation; add a case with shortage but no shipment issue and the converse.

### shortage_capacity_constraint — Дефицит или нехватка мощности

- **Scope:** An actual insufficient stock, resource, storage/transport capacity, or production capacity that constrains supply or output.
- **Positive:** e03, remaining raw material supports only a week of production.
- **Negative:** e01, a delivery is late but no insufficient stock is reported.
- **Hard boundary:** A late shipment is not itself a shortage; a price increase is not proof of scarcity. e28 also raises an unresolved question about whether a water-use restriction counts as a resource shortage.
- **Likely Jev error:** Treating every mention of limited stock, a warehouse, or a possible supply risk as a current shortage.
- **v0.4 proposal:** Name the evidence required for stock versus capacity constraints and explicitly decide whether utilities or regulated resource access qualify. Review e28 only after that rule is written.

### production_operational_disruption — Операционный сбой производства

- **Scope:** An actual stop or material reduction in a facility’s production due to an incident or other operational disruption.
- **Positive:** e05, a furnace fault stops a line; e06, a fire suspends output.
- **Negative:** e27, a flood disrupts access and shipments, but the text does not say production stopped.
- **Hard boundary:** Production/output disruption versus shipment disruption; a hazard alone is insufficient. Environmental impact is a separate event dimension.
- **Likely Jev error:** Inferring lost production from a fire, repair, access problem, or delivery delay without an explicit output impact.
- **v0.4 proposal:** State whether material reduction needs a quantified threshold and whether only manufacturing output qualifies. Add an incident with a fire but no production impact.

### price_cost_change — Изменение цены или затрат

- **Scope:** A price or business cost has actually changed.
- **Positive:** e07, a new active polymer price rises by 12 percent.
- **Negative:** e42, analysts forecast a possible rise while current price lists remain unchanged.
- **Hard boundary:** Effective change versus forecast, and price/cost change versus shortage. Do not infer one from the other.
- **Likely Jev error:** Tagging forecasts, market volatility, or a causal explanation as if a change had already taken effect.
- **v0.4 proposal:** Specify whether an announced future effective date qualifies and distinguish a quoted price, cost, tariff, and market index. Add an announced-but-not-yet-effective case.

### trade_restriction — Ограничение внешней торговли

- **Scope:** An official tariff, quota, license, customs measure, or ban that constrains international goods trade.
- **Positive:** e09, an export quota takes effect.
- **Negative:** e13, a packaging-reporting rule has no stated border restriction.
- **Hard boundary:** A tariff is a trade restriction when it constrains imports/exports; it is not automatically a generic tax-change label. Sanctions are separate unless the text also states a cross-border goods restriction.
- **Likely Jev error:** Confusing any tax/customs language with a trade restriction, or assuming sanctions always imply an import/export ban.
- **v0.4 proposal:** Make the cross-border scope and “constrains trade” test explicit; add a tariff cost-only edge case and a non-tariff reporting rule.

### sanctions — Санкции

- **Scope:** An official sanctions measure, listing, or asset freeze.
- **Positive:** e11, an authority adds a company to a sanctions list.
- **Negative:** e41, commentators discuss possible future restrictions with no official action.
- **Hard boundary:** Official sanctions versus ordinary regulation or a trade restriction. e12’s court confirmation of an existing sanctions freeze stays sanctions-only; e31 supports both sanctions and trade restriction because it states both.
- **Likely Jev error:** Treating diplomatic criticism, a threat, or any trade control as an implemented sanctions measure.
- **v0.4 proposal:** Define whether a formally announced but future-effective measure is positive and require an identifiable official action/target. Add a paired sanctions-only and trade-ban-only case.

### regulation_tax_change — Изменение правил или налогов

- **Scope:** An official or formally proposed change to rules, taxes, or standards with business effect.
- **Positive:** e13, a reporting rule for packaging takes effect.
- **Negative:** e10, a customs duty is specifically an import restriction in the current gold.
- **Hard boundary:** A rule change versus a case enforcing an existing rule; general tax change versus tariff/trade restriction; proposed legislation versus enacted rule.
- **Likely Jev error:** Tagging every fine/investigation as regulation change, or applying it alongside sanctions/trade restrictions despite the annotation rule.
- **v0.4 proposal:** Make lifecycle states explicit: proposed, adopted, in force, and enforced. Preserve the current exclusion of sanctions, trade restrictions, and legal enforcement, then add one controlled example for each.

### cyber_security_incident — Киберинцидент

- **Scope:** A cyberattack, ransomware, data exposure, or IT incident that disrupts operation.
- **Positive:** e15, ransomware makes the internal order system unavailable.
- **Negative:** e38, an educational satellite is launched without a cyber incident.
- **Hard boundary:** Confirmed unauthorized access/attack versus a generic outage, vulnerability, or preventive check. e16 is a confirmed intrusion even though the story does not establish broader business harm.
- **Likely Jev error:** Inferring an attack from any outage, or requiring stolen customer data despite a confirmed intrusion.
- **v0.4 proposal:** Separate confirmed attack/access from suspected cause, and state whether a non-disruptive confirmed breach qualifies. Add outage-only and vulnerability-only controls.

### labor_workforce_event — Трудовое событие

- **Scope:** A strike, labor dispute, lockout, mass layoff, or substantial workforce change.
- **Positive:** e17, workers begin a strike; e18, 800 jobs are scheduled to be cut.
- **Negative:** e40, an anonymous source speculates about a possible strike that the parties do not confirm.
- **Hard boundary:** Confirmed/officially announced action versus forecast or rumor; substantial hiring versus ordinary recruitment. e35’s announced future hiring of 400 workers is gold-labeled positive, but “substantial” and the boundary with ordinary hiring are not defined.
- **Likely Jev error:** Treating any job posting or headcount forecast as a workforce event, or overlooking a formally announced future action because it has not happened yet.
- **v0.4 proposal:** Define materiality, whether confirmed future actions qualify, and treatment of hiring. Review e35 as a gold caveat; do not change it without that decision.

### insolvency_default — Неплатёжеспособность или дефолт

- **Scope:** A formal bankruptcy/insolvency process, a default, or a specific missed debt payment.
- **Positive:** e20, an issuer misses an actual bond coupon.
- **Negative:** e44, the company denies the bankruptcy rumor and says payments are current.
- **Hard boundary:** A confirmed missed payment or court process versus financial difficulty, a rumor, or a creditor’s separate legal action. e19 is insolvency-only; e34 is insolvency plus a separate creditor filing under the explicit v0.3 rule.
- **Likely Jev error:** Overreading financial stress as default, or tagging every court action as legal enforcement as well as insolvency.
- **v0.4 proposal:** Specify which formal stages count as a bankruptcy process and require a concrete missed obligation for payment default. Keep the e19/e34 distinction explicit.

### corporate_transaction_restructuring — Сделка или реструктуризация компании

- **Scope:** Material M&A, asset sale, spin-off, site closure, or corporate restructuring.
- **Positive:** e21, an acquisition closes; e22, a cloud division is spun off.
- **Negative:** e30, production capacity expands without a transaction or restructuring.
- **Hard boundary:** A site closure that accompanies layoffs can satisfy both this and labor; an investment or capacity change is separate unless the text states a transaction/restructuring.
- **Likely Jev error:** Tagging routine management changes or negotiations as a completed transaction, or missing a closure because the article foregrounds layoffs.
- **v0.4 proposal:** Define whether announced plans qualify, and distinguish transaction, restructuring, and site closure as examples under the same label or separate future dimensions. Confirm e18’s dual label against the final rule.

### product_recall_quality_safety — Отзыв или риск качества продукта

- **Scope:** A reported recall, confirmed product defect, safety concern, or official quality action.
- **Positive:** e23, a battery batch is recalled after overheating reports; e24, a drink batch is removed from sale after an official quality finding.
- **Negative:** e45, a possible recall is an unconfirmed social-media rumor.
- **Hard boundary:** Confirmed product issue versus rumor or ordinary warranty replacement; ordinary recall/quality action does not imply **legal_enforcement** without a separate case or fine.
- **Likely Jev error:** Treating a consumer complaint as confirmed defect, or missing a regulator-led withdrawal because no manufacturer recall term is used.
- **v0.4 proposal:** Define the confirmation threshold and whether a safety risk with no recall qualifies. Add a complaint-only case and a recall without a stated injury.

### legal_enforcement — Судебное или регуляторное взыскание

- **Scope:** A distinct lawsuit, official investigation, fine, enforcement action, or judgment, beyond ordinary legal formalization of another event.
- **Positive:** e25, an antitrust authority imposes a fine; e26, a regulator opens a formal investigation.
- **Negative:** e12, a court confirms implementation of an existing sanctions measure; e19, a court opens the ordinary bankruptcy process.
- **Hard boundary:** A separate legal development versus the legal mechanism that constitutes the primary event. e34 is gold-labeled both insolvency and legal enforcement because the creditor separately files after the missed payment; this follows the explicit v0.3 rule, but the rule should continue to require a distinct actor/action or later development.
- **Likely Jev error:** Labeling any court or regulator mention, or missing a distinct case because it is described as part of a bankruptcy or sanctions story. The Russian label “взыскание” is narrower than the definition, which also includes investigations and lawsuits.
- **v0.4 proposal:** Consider a broader label such as “отдельное судебное или регуляторное действие”; state whether a bankruptcy petition is a distinct action only when the text identifies a separate creditor filing after default. Keep e12/e19/e34 as boundary controls.

### environment_disaster_impact — Экологический инцидент или бедствие

- **Scope:** A natural disaster or ecological incident with explicit harm, interruption, or restriction to a company, site, or supply flow.
- **Positive:** e27, a flood closes factory access and halts shipment; e28, drought-related water limits reduce a factory line’s output.
- **Negative:** e49, a reserve reports ecosystem recovery but no company or supply impact.
- **Hard boundary:** An environmental story with no business impact versus a hazard affecting business; business impact must be stated, not inferred. e06’s factory fire is operational, not environmental, because no ecological harm is reported.
- **Likely Jev error:** Inferring impact from proximity to a hazard, or double-counting every industrial accident as environmental.
- **v0.4 proposal:** Define the treatment of man-made pollution and resource restrictions, and clarify whether an official water-use restriction is an environmental impact, a capacity shortage, or both. e28 is a useful boundary case.

### investment_capacity_change — Инвестиция или изменение мощности

- **Scope:** A material investment, capital project, facility opening/expansion, or explicit capacity reduction.
- **Positive:** e29, construction begins on a new plant; e30, a production line’s capacity is expanded.
- **Negative:** e21, an acquisition transfers ownership but does not state a capacity change.
- **Hard boundary:** Capital investment/capacity versus ordinary purchase, M&A, or an uncommitted plan. e35 combines a new plant/capacity announcement with future hiring and therefore also receives the labor label.
- **Likely Jev error:** Inferring a capacity change from spending or ownership change alone, or treating every future aspiration as an investment event.
- **v0.4 proposal:** State whether a formally announced but not started project qualifies and whether capacity reduction is always included. Add a canceled-project control.

## Business-event coverage gaps

The current 15 labels already include dedicated codes for cyber incidents, product recall/quality, and corporate transactions/restructuring; these should not be described as missing. The taxonomy does not have a dedicated code for several other plausible business-event families, including **fraud/corruption**, **major contract or order award/loss**, and **material partnership/joint venture**. A clear example may currently route to the unlisted-event review signal, depending on the taxonomy's explicit criteria. This is a gap assessment against the project’s stated business-news use, not a measured claim about real-news frequency: the new corpus is synthetic and cannot establish prevalence.

For a separate v0.4 proposal, decide whether these families are in scope, write inclusion/exclusion criteria and counterexamples, and add paired examples before adding any codes. Do not infer a new label from an article or expand v0.3 during this audit.

## Gold-label caveats to carry forward

These are review questions, not proposed edits to the v0.3 gold:

1. **Topic choice for similar official trade measures:** e09 is **politics_government**, while e10 is **law_regulation**. The difference may be defensible by framing, but the current topic definitions do not state the tie-break. Review both headlines and full texts together.
2. **Topic choice for tax/regulatory changes:** e13 is **law_regulation**; e14 is **economy_finance**. This may reflect environmental reporting versus tax impact, but the main-subject rule is not explicit enough to reproduce the distinction.
3. **e28 water restriction:** **environment_disaster_impact** plus **production_operational_disruption** is plausible. Whether the same text should also receive **shortage_capacity_constraint** depends on whether regulated water availability is an in-scope resource shortage; v0.3 does not settle this.
4. **e34 creditor filing:** **insolvency_default** plus **legal_enforcement** follows the special rule. Because bankruptcy filing is itself a normal legal procedure, examples and wording must preserve the distinction between the ordinary process in e19 and the separate, subsequent creditor act in e34.
5. **e35 future hiring:** **labor_workforce_event** is plausible under the rule for an announced substantial workforce change, but no materiality threshold separates it from ordinary hiring or a hiring plan.
6. **e47 status:** The gold records an out-of-list business event, no insufficient-evidence signal, and status **uncertain**. Clarify whether **uncertain** means “needs taxonomy review” here, while e50 means “insufficient source evidence”.
7. **Small synthetic corpus:** With 49 non-empty items and many event questions, counts are useful for exercising boundaries, not prevalence, calibrated thresholds, or production quality. The test harness’s asserted golds validate consistency with its own labels, not independent annotation agreement.

## Proposed v0.4 work, kept separate from v0.3

1. Add an explicit main-topic rule: classify the article’s central subject/framing, not merely its actor, vocabulary, or downstream effect. Include adjudicated paired examples for e09/e10 and e13/e14.
2. Keep event labels multi-label but require each label to have its own directly stated fact. Write pairwise inclusion/exclusion rules for shortage/supply interruption, price/shortage, production/environment impact, tariff/regulation, sanctions/trade restrictions, and insolvency/legal action.
3. Define lifecycle language consistently: rumor, proposal, formal announcement, adopted measure, effective measure, completed action, and confirmed outcome. Apply the same status rule across labor, investment, regulation, sanctions, and prices.
4. Separate “topic outside the list” from “insufficient evidence” in names and output semantics. Define what **uncertain** status means for both e47 and e50.
5. Clarify terms that are broader or narrower than their labels, especially **legal_enforcement** versus the Russian “взыскание”, and define whether operational resources such as water count as shortages.
6. Add independent human review of the caveated gold cases before calling them settled. Keep the current v0.3 labels intact until that review records an explicit decision.

## Review limits

This audit did not run the test suite, inspect Jev outputs, or evaluate live model behavior. It did not edit taxonomy v0.3, the corpus, code, thresholds, or existing documentation. All v0.4 items are proposals for a later taxonomy revision; they are not implementation decisions.
