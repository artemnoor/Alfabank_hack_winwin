# Next steps before T08 can be trusted

## Сейчас

T08 готов передавать в T09 только неподтверждённые event-кандидаты по Policy v2.1. Это не разрешение на автоматическую обработку или production integration. В текущей работе live-запросов не было; прежний API-бюджет остаётся исчерпанным.

## Must happen before any integration decision

1. **Human-adjudicate the baseline packet.** It covers all 49 non-empty baseline stories without Jev outputs or draft labels. Resolve e03/e09/e10/e18/e25/e26/e27/e28/e32/e33/e34/e35 and any other disagreements with exact evidence spans. Preserve decisions in a new corpus revision; never rewrite v1 labels.
2. **Choose taxonomy semantics.** Review the separate 0.4.1 proposal and resolve topic/event boundaries. It is unapproved and has not been tested with Jev.
3. **Treat the existing 60 texts as visible validation only.** Their authors and developers have seen them; no amount of label hiding turns them into a final blind test. Do not tune taxonomy/prompt/policy on them if their results will be used as independent evidence.
4. **Create a true blind benchmark separately.** An independent custodian must create/hold new inputs after freeze and keep both texts and labels outside developer access until output hashes are locked. Use two annotators and a third adjudicator.
5. **Pre-register risk and policy.** Specify Choice, per-event, unlisted and evidence handling independently. Set acceptable bounds for consequential false positives before examining blind results.
6. **Only then request a new paid Jev budget.** No live call was made in the current work. The prior budget remains exhausted; do not use the same 45 results to select production thresholds.

## Suggested next API experiment and budget

After human review approves the cases and the owner selects v0.3 versus v0.4.1 for comparison, the smallest useful *paired prompt-comparison* is **20 live attempts**: 10 fixed synthetic cases × v0.3 and v0.4.1, same Jev model ID, client version, provider settings, and request order. Include boundaries for legal enforcement, shortage, price/regulation, sanctions/trade, topic choice, and future workforce plans. Record sanitized outputs only; no raw prompt/article/provider body in artifacts. Use a frozen request ledger and no automatic retries. A failed request consumes one attempt and yields no label; report partial paired cases without replacement.

This 20-call study can tell us whether taxonomy wording changes the responses on those selected examples. It **cannot** establish production quality, rare-event recall or a safe manual-review rate. Before starting it, require an explicit user budget grant; the earlier budget remains exhausted.

For the question “how much review can be removed without increasing dangerous errors?”, a later blinded evaluation must be sized from an agreed risk target. As a rough binomial illustration, observing zero false positives among 59 independent negative examples gives an approximate one-sided 95% upper bound near 5% (rule-of-three); each consequential category and relevant deployment slice needs its own adequate support, and examples may not be independent. This is not a proposed acceptance target; the owner must set the acceptable limit first.

## What must be measured in the next phase

- Exact paired v0.3/v0.4 predictions and event scores on approved cases; no response substitution or fallback.
- Human-adjudicated exact topic, event sets, evidence states, out-of-list and uncertainty labels.
- Review coverage and selective risk on a blind set, including per-code FP and FN and risk upper bounds.
- Stability on prespecified metamorphic variants, including changes that should change lifecycle interpretation.
- Latency/cost from returned usage only; failed-attempt cost may remain unknown.
- Missing, malformed, throttled or blocked calls handled as unavailable/review, never as negative examples.

## What is safe to reuse now

- Offline client validation and security safeguards, after ordinary code review.
- The stored response artifacts as historical observations with their documented provenance limitations.
- Tri-state Noul bookkeeping as an experimental offline analysis tool.
- Human-review and benchmark instructions.

Do not use v0.3/v0.4 thresholds to auto-publish classifications, and do not integrate this spike into the production runtime yet.
