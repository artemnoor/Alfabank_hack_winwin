# T09 limitations and open decisions

## Known gaps

- The prototype is rules-only. There is no live model, embedding, semantic
  similarity, or latency/cost evaluation. Model quality is **NOT MEASURED**.
- `ResolutionInput` has structured mentions but no article title/body text,
  publication-source clustering, or headline history. Text similarity and
  publisher syndication analysis therefore cannot be evaluated here.
- Participant resolution depends on stable entity IDs. Near-name candidates
  are held for review; this avoids silent legal-entity merges but increases
  `defer` when entity IDs are absent or aliases are not curated.
- Event taxonomy identity requires matching namespace, code, and version. A
  semantically equivalent event represented by another taxonomy code is not
  automatically mapped.
- `EventRecord` has no direct event-time field. The prototype uses validity
  bounds from its statements as a limited time signal. Missing bounds leave
  temporal compatibility unknown; the 14-day window is experimental.
- Correction rules recognize only explicit field-specific completion patterns
  currently implemented for `valid_from`, `valid_to`, and
  `/event/successor_supplier` only when the predicate is
  `alfalab.events/identifies_supplier`, its version matches the event
  vocabulary already present in the record, and the new value is an
  organization entity. Other paths remain missing; a new unrelated entity
  cannot clear them. A corrected successor carries forward all unresolved
  predecessor data.
- A `split` depends on the existing record retaining all related mention IDs
  and exactly the corresponding combined facts. If the snapshot lacks those
  lineage clues, the prototype cannot safely infer which record to split.
- A `merge` is intentionally narrow: selected records must have identical
  event type, participant IDs, factual statement signatures, statement status,
  provenance, and compatible time scope. Conflicting predecessor certainty or
  provenance defers the merge. The successor retains separately sourced or
  differently rated assertion variants rather than deduplicating on facts only.
- Distinct actor/object role assignments cannot attach solely because IDs are
  shared across swapped roles. Same-type multi-event aggregates split only
  when source mentions identify disjoint facility entity IDs; aliases are not
  inferred.
- Policy binding remains a compatibility gap. The normative
  `Events.propose_resolution` operation accepts `ResolutionInput.policy` as an
  opaque `VersionedRef` (`id`, `version`, `hash`); it does not carry candidate
  thresholds, a typed policy body, or a resolver. The Python `ResolutionPolicy`
  argument is the actual experimental runtime configuration, with a visible
  local default/override; the request reference is included in the proposal
  fingerprint but does not set those parameters. Changing the reference alone
  cannot be claimed to materialize new thresholds. This mismatch is covered by
  a regression test and must be resolved by an approved trusted owner binding
  before integration; the spike does not invent a policy registry or modify
  DTOs.
- Non-active `EventRecord.lifecycle` values (`merged`, `split`) are excluded
  from candidate retrieval. Generated event identifiers append a SHA-256
  suffix whenever sanitization or truncation would otherwise permit collisions.
- Defer is a decision action in the proposal; `unresolved_mentions` remains
  empty when every input has an explicit defer decision. This follows the
  contract rule that a mention is assigned to a decision or left unresolved,
  never both.
- All tests and metrics use synthetic, hand-authored, provisional expectations.
  They were designed to probe failure modes and have not been independently
  approved as gold labels. The perfect focus-action agreement in this small
  suite is not a quality estimate.
- Existing official Event Registry API terms could not be inspected in this
  review. No Event Registry, GDELT, or RavenPack data/service was used.

## Requires owner or reviewer decision

- Whether the same event window should be calendar-day based, exact timestamp
  based, or conditioned on event type/source cadence.
- Which statement fields constitute event identity versus a correction,
  especially when one event changes participant or scope over time.
- How a trusted owner resolves the input `VersionedRef` to approved runtime
  thresholds and source-authority rules. No such policy artifact/resolver is
  defined by this spike, so integration must remain blocked pending that
  binding.
- Whether an event-level policy may combine multiple source mentions before
  `Events.apply`, and what evidence sufficiency rules apply to merge/split.
- Whether raw normalized text may be passed to an experimental comparator
  without changing the approved contract; otherwise the T09 text-similarity
  track cannot be measured.
- Whether a reviewed Event Registry or other commercial API is permitted under
  bank egress, privacy, retention, licensing, and cost policies.
