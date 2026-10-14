# Shared dataset validation report

- Dataset: `t09-t13-independent-v1` version `1.0.1`; v1.0.0 is preserved in historical commit `db48cd37491e8fab8a9f122ae4b100da72197a81` and superseded due CRLF-sensitive hashes and a dangling T12 case.
- Command: `python -B spike/_shared/validation/validate.py`.
- Canonical dataset SHA-256: `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
- Scope: canonical hashes, pinned sources, immutable approved-fixture refs, current OpenAPI closure, five strict operation exchanges, domain/provenance rules, and fixture counts.
- Environment: Python `3.12.15`; Pydantic `2.14.1`.
- Network/database/model calls: none.
- Passed checks: 13; failed checks: 0; skipped checks: 0.
- Provisional scenario counts: T09 `32`, T10 `22`, T11 `12`, T12 `15`, T13 `30`.

## Passed

- dataset identity and canonical/file hashes
- PDF/framework source pins
- immutable approved fixture and dataset refs
- 16-operation and OpenAPI component lock
- strict Pydantic exchange: Understanding.extract
- strict Pydantic exchange: Events.read
- strict Pydantic exchange: Business.read
- strict Pydantic exchange: Evidence.read
- strict Pydantic exchange: Graph.query
- company/event/case coverage and evidence anchors
- executable T12 hypothetical/inferred/negative graph inputs
- confirmed-policy and graph provenance invariants
- deterministic freeze builder reproduction

## Failed

- None.

## Interpretation

A green strict contract check establishes payload shape and contract semantics only. Synthetic property expectations are provisional and do not establish algorithm quality or real-world truth.
