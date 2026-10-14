# T11 limitations and decisions still needed

- Shared sources and T11 annotations are synthetic and provisional. The case annotations were hand-authored by the prototype author and have not yet received independent review.
- The prototype does not extract claims from prose. It accepts a relation annotation (`supports`, `contradicts`, `mentions_only`, or `unknown`) as an explicit input, with annotation provenance.
- A valid quote does not show the source is truthful. A source assertion is not the same as a sufficiently established fact.
- `supported_unconfirmed` means the accepted annotations say that one or more sources support the proposition; it is not a factual confirmation.
- Publisher-root and syndication-family identifiers are inputs. T11 cannot prove that two roots are controlled by independent organizations or that two outlets did not coordinate.
- Source reliability fields are carried by the normative record but are not scored or upgraded. There is no universally justified reliability threshold in this experiment.
- Temporal relevance is explicitly annotated as current, historical, or unknown. T11 does not infer freshness from an arbitrary time-to-live or resolve all historical revisions.
- Point-in-time assessment keeps valid time and knowledge time separate: `published_at <= valid_as_of`; the latest available `collected_at`/`recorded_at <= known_as_of`. Missing/invalid registration time is fail-closed and makes that observation inapplicable. Missing/invalid `published_at` is inapplicable only when a valid-time cutoff is requested.

- The prototype does not implement `Evidence.register` or `Evidence.read` persistence. It validates the existing `Evidence.read` exchange and the register input DTO shape; production operation ownership remains out of scope.
- Anchor rechecking currently consumes immutable `Documents` snapshots. The normative contract also permits `Business` and `Runs` `WholeArtifact` references, but this shared corpus has no materialized owner snapshots for those cases. Such references fail closed as unavailable in this prototype; this is a fixture-coverage gap, not a claim that the normative operations reject them.
- Tests use no live source, model, or external data. Live model quality is **NOT MEASURED** and algorithm quality is **PRELIMINARY**.
- The implementation pins shared dataset v1.0.1 (canonical hash sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725). The local hand-authored annotation fixture remains version 1.0.0 with its own pinned content hash; both are explicitly versioned and provisional.
- The positive owner-policy example is restricted to the shared corpus's exact synthetic policy v1.0.1. The code pins its id, schema, version, dataset id, and canonical JSON SHA-256 sha256:7ab45d5de57f60f612f11820a444bacf216cd77704f5e5598218eae7ca0e6327. Caller-edited policy content is not eligible for owner review. This test-only pin is not a trusted production owner registry and never writes confirmed.
- Integration readiness is NOT READY pending owner-policy agreement and a separately approved integration design. Independent re-review is complete for the recorded findings; T11 cannot establish production trust in an owner policy from caller-provided input.
