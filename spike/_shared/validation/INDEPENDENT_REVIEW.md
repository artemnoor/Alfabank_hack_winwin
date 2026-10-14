# Independent review: shared T09–T13 dataset

Reviewed frozen commit `db48cd37491e8fab8a9f122ae4b100da72197a81` on branch `codex/review-shared-dataset`. Canonical data SHA-256 matches the coordinator’s `sha256:c30fb7ba9febd8b10bf35b4620a21890c57532c07fa55ad9566977ea6f21d25f`.

The corpus is synthetic and remains marked `provisional_not_gold_not_approved`. No model outputs are labels. No external service or dataset was used. The reviewed commit changes only `spike/_shared/**`; approved fixtures are unchanged. This report is the only remaining reviewer worktree change.

## Findings

| Severity | Finding |
|---|---|
| HIGH | Raw-byte hashes in the frozen manifest do not match the committed LF-normalized files. The recorded expected hashes match CRLF versions of four contract JSON files and all five operation fixtures. `.gitattributes` requires LF (`spike/_shared/.gitattributes:1`), while `freeze_v1.py:48–54` writes JSON using `Path.write_text` without fixing newline behavior. `data.json` raw hash and canonical dataset hash do match. The documented `validate.py` command exits 1 with 5 checks passed and 3 failed: manifest file SHA mismatch (`approved-fixture-refs.json`), fixture SHA mismatch (`understanding-extract.json`), and downstream domain coverage skipped because no strict fixtures were checked. This reproduces from the clean reviewer checkout and is a cross-checkout reproducibility defect, not local Git configuration. Keep v1 immutable; fix serialization and hashes in a new dataset version, then validate from a clean checkout. |
| MEDIUM | The T12 inferred-edge check has no executable input. `data.json:5028–5033` names case `inferred-relation-grounding` with `input_ref: hypothetical-only`, but no such input or hypothetical/inferred/disproved statement exists in the corpus. `graph-query.json:12` explicitly says the materialized graph contains no inferred edges. Thus the expectation that an inferred edge must include a method and input statement refs is prose only; explicit negative-assertion handling is also not exercised by a graph input. Add a versioned synthetic input carrying the relevant epistemic status and refs, or revise the case to identify an existing input. |

## Checks run

The repository’s pinned Python 3.12.15 / Pydantic 2.14.1 environment was used.

- `& 'C:/Users/Артём/Documents/ChatGPT/Хакатон Альфабанк/.venv/Scripts/python.exe' -B spike/_shared/validation/validate.py` — **FAIL**, exit code 1; 5 passed / 3 failed, as detailed above.
- Direct strict `validate_operation_exchange` checks, bypassing only the invalid raw-file-hash gate — **PASS, 5/5**: `Understanding.extract`, `Events.read`, `Business.read`, `Evidence.read`, `Graph.query`.
- Validator subchecks run independently — **PASS**: PDF/framework source pins; approved fixture pointers; 16-operation/OpenAPI lock; company/event/case coverage; owner-policy and graph provenance invariants; deterministic builder reproduction.
- Independent evidence-anchor audit — **PASS**: 44 evidence records; source text hashes, source refs/hashes, and available text-span quote hashes match. One deliberately unavailable source remains unverified.
- Fixture metadata and canonical request/response data hashes — **PASS, 5/5**.
- Dataset SHA — **PASS**: actual canonical hash equals manifest hash; `model_outputs_used_as_labels=false`, `external_sources_used_for_facts=false`.

Scenario counts: T09 32, T10 22, T11 12, T12 13, T13 30. The cases cover the requested core negative conditions: near-name entities, distinct fires, rumors, forecasts, stale events, unknown suppliers, conflicting inventory, reprints, and unsupported sector-only impact.

The validator rewrites `VALIDATION_REPORT.md`; I restored its initially clean committed copy after running the documented command. No author data or other file was changed by this review.