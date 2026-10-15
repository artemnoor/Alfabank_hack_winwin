# Future blind-test candidate inputs — annotation protocol

**Status:** candidate inputs only; awaiting independent human annotation. This is not yet a blind benchmark and has no gold labels or Jev outputs.

## Before annotation

1. Freeze the tested Jev model/provider revision, request builder, taxonomy, and Policy version. Record exact hashes before any run.
2. Give annotators only `news.json` and this guide. Do not provide current Jev outputs, the original corpus labels, or the error-analysis reports.
3. Two people label every case independently. A third person adjudicates disagreements after both label files and hashes are frozen.
4. Keep labels and adjudication with a custodian outside the implementation branch. Run Jev only after labels are frozen; publish output hashes before the custodian releases labels for scoring.

## Annotation fields

For each item, record:

- one main topic from taxonomy v0.3.0-spike, or `other_uncertain`;
- zero or more event codes, each supported by its own exact quote;
- whether each statement is confirmed, an official decision, a plan, a rumor, a negation, or contradictory;
- `unlisted_event` separately from insufficient evidence;
- insufficient evidence for the event assertion, not merely uncertainty about the main topic;
- a short rationale and any disagreement flag.

Do not infer production stoppage from delayed shipping, a legal violation from an investigation, or a completed action from a proposal. Multiple event labels are allowed only when the text independently supports each one. Keep disagreements; never rewrite an annotator's first pass.

## Holdout handling

The input texts are visible in this repository, so this set is not blind to the owner or developers. It can become a label-blind prospective evaluation only if taxonomy/prompt/policy are frozen before annotation, annotators do not see predictions, and a custodian withholds labels until output hashes are fixed. Any tuning after seeing scored results requires a new benchmark version.
