# T13 test report

## Run

Environment: project interpreter reports Python 3.12.15; pytest 8.4.2; pinned project Pydantic v2 package; no new dependencies. Pytest cache was disabled and Python bytecode writes were disabled.

```powershell
$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T13/tests
```

Latest remediation result: **63 passed, 0 failed, 0 skipped**. Tests include exact Evidence ObjectRef matching, required graph-path evidence, disputed source handling, event-owner trust gating, inactive events, Business-slice mismatch explanations, and StatementRef/path lineage. Coverage was not measured.

The deterministic 30-case runner was executed with:

```powershell
$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T13/experiments/run_offline.py
```

Output is recorded in `results/approach-comparison.json`. The same shared dataset v1.0.1 cases and materialized graph/profile/evidence inputs are passed to both implementations. The runner reports:

- 30 scenarios processed; dataset version 1.0.1, canonical SHA-256 `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`;
- C: 11 potential-mechanism scenarios, 25 accepted target/path claims; 11 potential and 19 unknown exposure outputs, with no confirmed exposure;
- D: 11 potential-mechanism scenarios over 25 graph paths; 11 potential and 19 unknown exposure outputs, with no confirmed exposure;
- zero accepted C claims without a supplied graph path or available, verified-anchor evidence;
- zero D mechanisms without a supplied graph path/evidence;
- zero mechanisms from the sector-only case;
- zero non-null financial quantities in contract-shaped assessments;
- 17 informational recommendations in the bank-manager harness; all within the local action allowlist;
- one explicit auxiliary calculation: 10,000 RUB/month of gross procurement exposure under the named synthetic assumptions, not financial loss.

Additional checks passed: `tests/contracts` **31 passed**; `spike/_shared/validation/validate.py` **13 checks passed, 0 failed**; integration scenarios **7 passed**; pinned contract codegen `tools/contracts_codegen.py --check` passed; `git diff --check` passed. These checks did not modify shared fixtures or approved contracts. Module suites were run separately because multiple test packages define `conftest.py` and an all-in-one pytest collection aliases those modules.

Approach C's output is generated from controlled model-shaped fixtures. **Live model quality is NOT MEASURED.** Counts above are guardrail-harness results, not accuracy/precision/recall or proof of real-world algorithm quality. The shared expected properties and all data remain provisional and require independent review.

## Coverage by failure class

- Positive/direct and indirect paths; paths of different depths and edge statuses.
- Negative paths, absent targets, sector-only cases, wrong entity and unsupported event/company relations.
- Unknown supplier, partial graph, stale graph, forecast/historical event, rumor, contradictory statements, unverified anchor, disputed source reliability.
- Strict Pydantic DTO parsing plus `validate_matching_pair`, `validate_impact_pair`, and `validate_recommendation_pair` checks.
- Nonexistent graph IDs, unsupported evidence IDs, wrong path endpoints, free-form extra fields, invented amount and changed units/values.
- Directed path orientation, irrelevant-edge/order invariance, event-state changes, deterministic repeat-run byte comparison.
- Recommendation audience, allowed action, approval floor, evidence-subset, empty allowlist, informational-only behavior, and no action when evidence/event context is insufficient.

## Results by quality dimension

- **Engineering quality:** local prototype executes; 63 deterministic unit/negative/contract/reproducibility tests pass.
- **Algorithm quality:** PRELIMINARY. Only 30 provisional synthetic cases and hand-authored context mappings were exercised. No public-company corpus, expert adjudication, model inference, calibration, or outcome labels were used.
- **Integration readiness:** not ready for Framework runtime. DTO pair compatibility passes, but runtime trusted-policy binding, numeric scenario-input gap, directed-path semantics, and approved action catalog need owner review. No production owner, database, HTTP endpoint, or side effect is implemented.
