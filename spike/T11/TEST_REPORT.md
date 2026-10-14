# T11 test report

## Run

Environment: pinned workspace Python 3.12.15; Pydantic v2 from the existing workspace. No new dependency, network service, model, or database was used; test commands disable pytest cache. The only artifact write was the local T11 offline result file.

```powershell
$env:PYTHONPATH='spike/T11/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest spike/T11/tests -p no:cacheprovider -q
```

Recorded result: 53 passed, 0 failed, 0 skipped. The updated result artifact for shared corpus v1.0.1 is spike/T11/results/offline-v1.0.1.json; the prior v1.0.0 run is retained. The offline experiment runner emitted all 12 case results.

## Coverage by property

- Exact quoted span, whole-artifact hash, Unicode code-point offsets, empty/out-of-range spans.
- Wrong quote, wrong source hash, wrong source version, unavailable source, malformed strict DTO.
- Separate source assertion and factual status; rumor wording remains unknown; missing evidence remains unknown.
- Conflicting current stock values remain disputed; stale evidence stays historical; publication uses valid_as_of while source registration uses known_as_of.
- Missing/invalid publication dates cannot be treated as applicable to an explicit valid-time cutoff; missing, malformed, or late collected_at/recorded_at values cannot enter a historical knowledge-time snapshot. The policy gate rechecks both cutoffs.
- Ten syndicated reprints collapse to one publisher root; two distinct roots are counted separately.
- Named policy positive and negative gates, statement-to-claim scope, exact pinned policy id/schema/version/canonical hash, caller-edited allow-list rejection, policy time recheck, and no automatic confirmed.
- Provenance keeps evidence refs, source ref/version/hash, locator offsets/hash, and annotation provenance.
- Determinism under reordered observations, duplicate annotations, stable canonical hashes, logger redaction, and no network/model imports.
- Strict `EvidenceRecord` validation and the materialized normative `Evidence.read` request/response exchange; `Evidence.register` input DTO shape is validated without invoking the owner.
- Explicit coverage gap: Business/Runs WholeArtifact references fail closed because the shared corpus does not provide those owner snapshots.

## Metrics

| Metric | Result |
|---|---:|
| Collected tests | 53 |
| Passed | 53 |
| Failed | 0 |
| Skipped | 0 |
| Coverage | Not measured |
| Live model quality | NOT MEASURED |

## Interpretation

These results establish repeatable engineering behavior for a provisional synthetic harness. They do not establish calibrated source trust, real-world factual accuracy, or the correctness of a production confirmation policy. The independent re-review verified the HIGH and MEDIUM remediations; trusted owner policy and production Evidence ownership remain unresolved.
## Integration verification

- Contract suite command: $env:PYTHONPATH='packages/contracts/src'; & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider -q tests/contracts. Result: 31 passed, 0 failed.
- Offline runner command: & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T11/experiments/run_offline.py. Result: exit 0, 12 cases. The regenerated artifact keeps the shared dataset v1.0.1 hash and local T11 fixture v1.0.0 content hash; owner policy is pinned to v1.0.1.
- Shared validator command: $env:PYTHONPATH='packages/contracts/src'; & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py. Result: exit 0, 13 checks passed, 0 failed; five strict operation fixtures passed. Dataset canonical hash: sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725.
- The earlier 5-pass/3-fail validator report came from the separate T11 author worktree pinned to shared v1.0.0 at base db48cd37491e8fab8a9f122ae4b100da72197a81. Its approved-fixture refs expected sha256:7b743eaa0bf9642a7066cfccd1f7b7364d286a70ff84711c1140b20be95e3124 but committed bytes were sha256:631fa3dc43aff07abcaa4d63e433369974aa219e31977c83a88bcec66856d133; its Understanding.extract fixture expected sha256:4e1abab21f80b9a25b583805395c453579f2eb69f6c0c914fea27fb20b504f09 but bytes were sha256:81f9d919850ce1599fa5f655acf6c2b25313fd5bb534b2c02973e6c642d28575.
- Integration uses shared dataset v1.0.1 published by c5f32e5 and T11/T09 repins from 66832de. The current manifest now expects approved-fixture refs sha256:f0978b3def832636137eda386916f1dba452879d11bc95bd199fe9e73cc423ad and Understanding.extract fixture sha256:4d8f7f7594d49bb341f52ad095066f276ea22d4acc83b292fd5d8589fa6f9cf3; both match current committed bytes. This is the branch/base correction behind the different validator result, not a T11 logic change.
- The shared validator's generated validation report already matched the tracked v1.0.1 13/13 result; no shared file change remained.
