# T10 limitations and decisions

## Algorithm limits

- Extraction is a small rule set for selected Russian/English phrasings. It does not resolve entities, paraphrases, coreference, negation scope generally, table layouts or document structure. Misses and false extractions are expected outside tested patterns.
- Scalar contradiction detection covers a limited list of numeric predicates and overlapping validity intervals. It compares distinct new claims within one proposal and incoming claims/answers with visible current statements; it does not resolve arbitrary textual or entity-relation contradictions, nor decide which side is true.
- Bitemporal filtering checks `valid_from <= valid_as_of < valid_to` and `recorded_at <= known_as_of`. It does not infer missing publication times or normalize source-specific clocks.
- Question scores and event-to-field mappings are hand-authored ordinal weights. They are not probabilities, empirical utility, calibrated expected information gain, or a claim that the selected question will change a real bank decision.
- `QuestionAnswer` values are mapped only for a short allowlist of question IDs, now including the experimental `warehouse` and `service_dependency` questions. Unsupported answered IDs are preserved as missing input, not guessed.
- Repeated question IDs in the profile/history are suppressed regardless of `answered`, `skipped`, or `declined`; this avoids loops but a user/owner may later decide that a skipped item can be asked again.

## Contract and integration limits

- I/O is checked with existing Pydantic DTOs. New predicate codes and local code versions, including `stores_at` and `uses_service`, are experimental and have not been registered or approved by a Business ontology owner. Do not treat DTO validation as owner approval or integration readiness.
- **Exact warehouse/service contract gap:** OpenAPI `#/components/schemas/Statement/properties` contains `subject`, `predicate`, and one `value`, but no object/target entity or relation endpoint; `#/components/schemas/CodeRef/properties/code` is not a registered warehouse/service predicate catalog. This prototype can preserve an explicitly named warehouse, provider, or service as a text value with source/time provenance and ask for it. It cannot represent a typed company → warehouse/service-provider edge, item-to-warehouse association, service criticality, or provider entity resolution. Where that association is needed, retain `unknown`; do not synthesize a link until the Business/ontology owner approves a compatible representation. No DTO/OpenAPI changes were made.
- `Business.apply` validates every supersede ref against the exact passed current aggregate ref and the matching statement ID/revision/content hash. It rejects duplicate/absent/mismatching refs before producing a new snapshot; it also derives missing paths from the valid/known slice when applying. The pure prototype has no external transaction to roll back.
- `TrustedOwnerPolicy` is an isolated test-only context because the normative apply request does not carry an explicit owner policy reference. A successful synthetic policy test is not production confirmation authority.
- `apply_profile` mutates no repository, does not implement durable idempotency, concurrency control, transactional rollback, or a persisted receipt index. Callers must pass each snapshot explicitly.
- No full HTTP operation envelope, authorization, tenant scoping, or production Business database exists in this spike.

## Evidence and quality

- Synthetic fixtures are provisional, hand-authored and not independently approved gold labels. Passing tests shows engineering behavior on those fixtures only.
- No live LLM/model is present or benchmarked. Live model quality is `NOT MEASURED`.
- No real company data or external data source was used. Extraction quality and question utility for real bank workflows remain `PRELIMINARY`.
- The vendor pages are commercial product descriptions. Vendor datasets, algorithms, APIs and licensing terms were not accessed or adopted.

## Requires owner decision

1. Register/approve the predicate vocabulary and its version before any connector maps the prototype output to a production Business statement, including whether warehouse/service relations need typed target entities and item/process endpoints.
2. Define which owner and what evidence policy can authorize `confirmed`; an anchor or source citation alone is insufficient.
3. Decide whether skipped answers should always suppress a repeated question, and how a user can reopen a suppressed topic.
4. Validate question priorities with domain owners and reviewed, representative examples before interpreting them as operational importance.
