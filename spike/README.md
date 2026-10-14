# Experimental spikes T09–T13

These prototypes investigate the Framework v1 operations without changing
production modules, public contracts, approved fixtures, or the separate T08
spike. Inputs are explicit materialized fixtures. No module reaches another
module's database, makes an external request, or depends on T08 completion.

## Modules

| Folder | Purpose | Current gate |
|---|---|---|
| [T09](T09/README.md) | Event candidate retrieval and create/attach/correct/merge/split/defer resolution | Not ready: opaque policy reference is not bound to trusted runtime policy |
| [T10](T10/README.md) | Business facts, unknowns, contradictions, profile updates, and question selection | Not ready: Business owner/ontology and receipt-read gaps |
| [T11](T11/README.md) | Evidence anchor integrity, provenance, source independence, and trust assessment | Not ready: trusted owner policy and persistence are not integrated |
| [T12](T12/README.md) | Provenance-preserving dependency graph build, projection, and query | Independent re-review closed HIGH/MEDIUM findings; one LOW diagnostic gap and DTO/owner integration gaps remain |
| [T13](T13/README.md) | Graph-constrained matching, impact approaches C/D, and informational recommendations | Not ready: T11 policy handoff and broader Events.read scenario coverage |

Shared synthetic inputs and strict operation fixtures are in
[`_shared`](_shared/README.md). They are frozen at provisional dataset
`t09-t13-independent-v1` v1.0.1 with canonical SHA-256
`f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
Provisional fixtures are not an approved gold dataset.

## Checks

Each module has its own `tests/`, `TEST_REPORT.md`, experiment artifacts, and
review reports under `results/`. Test modules separately: they use their own
`conftest.py` files, which collide if pytest collects all module suites in one
invocation. The coordinator's materialized cross-module checks are in
[`integration/`](integration/) and the current readiness summary is
[`INTEGRATION_REPORT.md`](INTEGRATION_REPORT.md).
