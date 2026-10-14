# T10 plan and status

| Work item | Status | Evidence |
|---|---|---|
| Read Business operation cards and generated Pydantic DTOs | Done | `Business.propose_profile`, `Business.propose_questions`, `Business.apply`, `Business.read`; pinned operation/schema hashes in shared lock |
| Freeze input corpus | Done, provisional | Shared dataset v1.0.1, `fixtures/scenario-index.json` |
| Direct-claim extraction and provenance | Implemented, narrow rules | `src/t10_business.py`; extraction/provenance tests |
| Explicit unknown, hypothesis, and negative handling | Implemented | tests for sparse profiles, hypotheticals, explicit negatives, skipped and declined answers |
| Conflict and history behavior | Implemented, limited scalar scope; proposal and incoming-answer conflicts included | Pairwise tests for new claims and conflicts against the current snapshot; original statements remain |
| Bitemporal visibility (`valid_as_of` + `known_as_of`) | Implemented across profile resolution, question selection, conflict visibility, supplier helper, and apply gap clearing | Future-recorded profile/question/apply probes use `recorded_at=2026-10-14T01:00Z` against `known_as_of=2026-10-01T00:00Z` |
| Supersede reference integrity | Implemented for current aggregate ref, exact statement revision/hash, duplicate and absent targets | Invalid/foreign refs are rejected before building a next snapshot; current input remains unchanged |
| Warehouses and services | Implemented as narrow explicit text predicates/questions; no entity relation inference | Provenanced document/answer, negative, unknown, and event-conditioned question tests; see exact ontology gap in `LIMITATIONS.md` |
| Event-conditioned question ranking | Implemented, heuristic | `experiments/question-priority.md`; budget, suppression, preference, history, and event tests |
| `Business.apply` / `Business.read` simulation | Implemented on explicit snapshots | Revision, owner-policy, receipt, read and immutability tests |
| Shared scenario coverage | Done | All 22 shared T10 scenarios run with property assertions |
| Strict contract compatibility | Prototype DTO compatibility checked | Typed request/response models and `validate_dto`; see `TEST_REPORT.md` |
| Live model benchmark | Not run | No LLM adapter or network call; model quality `NOT MEASURED` |
| Independent review | Complete for reviewed findings | Initial review remains preserved; separate re-review verified the R1–R4 remediation with no open Critical/High finding; owner ontology and receipt-read gaps remain |
| Framework integration | Not ready | Predicate registry/policy integration and owner review are outstanding |

## Experiment hypotheses

1. Product/sector clues should not create supplier, geography, import-share, procurement-volume, or capacity statements.
2. Questions attached to an event can be prioritized by a transparent ordinal decision-impact rubric, with explicit reasons and an upper bound.
3. A skipped/declined/unknown answer should not become either a positive or negative business fact.
4. Contradictory values, source and time references should remain visible so the next question can target reconciliation.

The tests can refute these properties for the implemented fixture inputs. They cannot establish real-world extraction recall, calibrated question value, or model quality.
