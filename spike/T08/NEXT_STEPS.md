# Next steps before T08 can be trusted

## Must happen before any integration decision

1. **Human-adjudicate the packet.** Decide e33, e34, e35 and listed topic-boundary cases. Preserve each decision, evidence span and rationale in a new corpus revision; never rewrite the original v1 labels.
2. **Choose taxonomy semantics.** Resolve main-topic ties, “officially scheduled price change”, material workforce changes, simultaneous sanctions/trade restrictions, and `other_uncertain` vs out-of-list event. Review `TAXONOMY_PROPOSAL.md`; v0.4 is not approved or tested.
3. **Create a genuinely blind set.** Current D is visible, and all current gold labels are single-author drafts. Two independent humans and a separate adjudicator are needed. Keep blind text/gold outside the developer repository until evaluation is frozen.
4. **Pre-register the policy.** Specify negative/abstain/positive handling independently for topic, each event, out-of-list and evidence sufficiency. Set acceptable upper bounds for dangerous false positives before looking at validation output.
5. **Only then request a new paid Jev budget.** No live call has been made in this task. Do not use these counterfactual threshold tables to pick a production cutoff.

## Suggested next API experiment and budget

After human review approves the 10 cases and both taxonomy revisions, the smallest useful *paired prompt-comparison* is **20 live attempts**: 10 fixed synthetic cases × v0.3 and v0.4, same Jev model ID, client version, provider settings, and request order. Include boundary pairs covering legal enforcement, shortage, price/regulation, sanctions/trade, topic choice, and e35-style future workforce plans. Record sanitized outputs only; no raw prompt/article/provider body in artifacts. Use a frozen request ledger and no automatic retries. A failed request consumes one attempt and yields no label; report partial paired cases without replacement.

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
