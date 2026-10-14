# T10 test report

## Latest run

- Command: set `$env:PYTHONPATH = 'packages/contracts/src;spike/T10/src;spike/T10/tests'`, then `& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T10/tests -q`
- Worktree: `codex/spike-t10-business`.
- Python: pinned workspace Python 3.12.15; Pydantic 2.14.1 from the existing workspace environment.
- Dataset: `t09-t13-independent-v1` `1.0.1`, canonical SHA-256 `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
- Result: **90 passed, 0 failed, 0 skipped** (0.21 seconds).
- Machine-readable run: `results/t10-remediation-r1.json`; the initial baseline artifact `results/t10-run-v1.json` is retained in history.
- Coverage: not measured.
- Model/network/database calls: none.

## Coverage by concern

- All 22 provisional shared T10 scenarios are executed and have property assertions.
- Unit and negative cases cover profile extraction, question ranking, apply/read, malformed/extra fields, invalid budgets, stale revisions, missing evidence policy, and mismatched evidence hashes.
- Incomplete, unknown, skipped and declined answers are kept distinct from positive/negative assertions.
- Contradictory and historical facts are tested, including profile and apply variants of the exact future-recorded supplier probe, conflicts between two claims in one proposal, incoming-answer conflicts against the current snapshot, disputed inventory statements, and expired suppliers.
- Supersede tests reproduce the independent-review foreign aggregate + wrong-hash probe and separately reject stale aggregate refs, wrong hashes, absent statement refs, and duplicate refs without changing the passed snapshot.
- Warehouse/service tests cover explicit document extraction with source hash/ref, answered fields with provenance, explicit negative claims that do not close unknown, sparse-profile unknown fields, and port/cyber conditioned questions.
- Determinism, sentence-order metamorphism, irrelevant-text metamorphism, and an asserted-versus-possible meaning change are tested.
- Provenance and security cases cover document refs, anchor/policy gates, payload-free debug logs, and the absence of external-call imports.
- Response DTOs are checked through the existing `validate_dto`; request payload construction uses strict generated Pydantic models.

## Interpretation

Engineering quality: **PASS** for the deterministic offline suite and reviewed remediation. The separate re-review found no open Critical/High finding; the initial review report remains preserved. Algorithm quality on real organizations is **PRELIMINARY**, because the synthetic corpus is not approved gold. No live model quality claim is made (**NOT MEASURED**). The module is not **INTEGRATION READY**: predicate vocabulary/version, warehouse/service representation, Business owner policy, and the in-memory apply/read boundary require explicit owner review.
