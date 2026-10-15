# AI Factory independent review log

Date: 2026-10-15. Review scope: new `spike/T08/fact_extraction/` files and
`spike/T08/test_fact_extraction.py`. Review was read-only; no external model/API
calls.

## Pass 1

- **HIGH, fixed:** `PolzaDeepSeekFlash` accepted a custom transport that could
  receive the authorization header and article text and send them elsewhere.
  Removed transport injection from the live constructor and Windows environment
  factory. Live construction now installs only the pinned HTTPS transport; tests
  substitute a private instance field.
- **MEDIUM, fixed:** a company name quote was checked for presence but not tied to
  the event. Required exact event and company evidence to share one relation quote.

## Pass 2

- Reviewer noted that same-sentence co-occurrence alone still allowed a reporter
  to be mistaken for the affected company. Added explicit `company_role` to the
  strict extraction-only schema and prompt. `reporter`, `mentioned`, and `unknown`
  remain unresolved and are omitted from event actors/objects; `missing_data`
  records the unresolved link. Added reporter-vs-affected regression coverage.
- Reviewer confirmed that the reporter relation is no longer emitted and found
  no remaining CRITICAL/HIGH/MEDIUM code findings.

## Pass 3 — bounded live-pilot runner

- Independently reviewed `live_pilot.py` and the latest provider error/cost
  handling before the authorized request.
- Confirmed default-deny authorization, a fixed 10-case synthetic allowlist
  paired with saved Jev outputs, a hard request cap, no retries, stop-on-first
  failure, and a run-once artifact guard. The report does not save prompts,
  source articles, raw provider responses, or credentials.
- Offline orchestration checks: **3 passed, 30 deselected**; verified that the
  first failure stops after one attempt, a second run cannot spend again, and a
  successful mock path is capped at exactly ten requests.
- No blocking findings. This code review did not call Jev or DeepSeek.

## Remaining limitation

The model can still predict the wrong company role. Text-boundary validation
cannot prove semantic entailment. Such extraction remains unconfirmed and must
be checked by the Evidence/T09 flow when those runtime owners exist.
