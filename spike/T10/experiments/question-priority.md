# Question-priority experiment

## Hypothesis

When an event is explicitly supplied, questions about facts that can clarify the event-to-company mechanism should be proposed before unrelated profile gaps. This is tested as an ordinal ranking hypothesis only.

## Offline rule

1. Read the explicit event type. A sector-only or unrecognized event produces no event-conditioned questions; it does not use industry similarity as a fallback.
2. Select the hand-authored field set for that event. A field is a candidate only when its value is not known at the requested valid time, it has a recorded contradiction, and it is not suppressed or already asked.
3. When no event is supplied (or event prompts are disabled), consider only fields listed in `missing_data` or a contradiction. The event cannot expand that set.
4. Give each candidate a hand-set integer weight from 0 to 10 for event relevance. A conflict raises the field to at least 10. Sort by descending weight, then field code for deterministic ties.
5. Return at most `min(budget, profile.preferences.max_questions)`. An explicit zero budget returns no questions.
6. Attach a reason stating what is unknown and why the field matters. Priority labels are derived from the same ordinal band: high >= 8, medium >= 5, otherwise low.

The concrete weights and event-to-field map are in `src/t10_business.py`. They are hypotheses chosen for testability. They are not frequencies, likelihoods, utility dollars, a calibrated information-gain estimate, or a learned model. No probabilistic model exists for these variables.

## Test comparisons

The 22 shared provisional scenarios include export controls, sanctions, port closure, input-price events, tax changes, a forecast, sector-only news, unknown suppliers/routes, contradictory inventory, previous answers, suppression and question budgets. Tests compare identical profile inputs under different event types and confirm that a strong event-specific unknown ranks ahead of unrelated fields. Negative tests ensure the system does not create facts when no company-specific relationship is present.

## Next experiment

After a domain owner reviews the field map and independent reviewers validate the cases, collect reviewed examples of which user answer would change the next analytical action. Use that set to compare this ordinal baseline with an owner-defined scoring rubric. Do not tune weights against unreviewed model outputs or describe them as expected information gain.
