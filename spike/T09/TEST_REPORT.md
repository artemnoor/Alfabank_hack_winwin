# T09 test report

Run in the assigned Python 3.12 environment. No packages, network calls, or
live model services were used.

## Versioned base

The independent-review baseline is T09 commit
`3159dc30fa1a8450564cfff195e1a99126b7db59`, plus the reviewed shared-data
correction `a5e2d2cd5f9df8fe72fc4c7c41683640eca69623`, its v1.0.1 review
`bb869df05549f7f108c8ada96cc76433a6a48e48`, the independent T09 review
`ad4365b7316ea37c7dbec67f111aa074c3ff12ac`, and the coordinator's v1.0.1
T09 pin from `66832de6d4b53237e6bb66e508e4641c27092efe`. The worktree carries
corresponding local commits `4d27df08d9092695b803c0a7fe2cad1207d069b3`,
`2767d434d405e9685f74e4b0a5061d992c41cc96`,
`8850a33d174b285145d967441e2692c5409f6774`, and
`6dd17ac5e27bf2151150959dab3891dfd4cdbccb`. The provisional shared dataset identity is
`t09-t13-independent-v1` version `1.0.1`, canonical SHA-256
`f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
The original v1.0.0 branch baseline had 95 tests; the independent reviewer and
v1.0.1 pin baseline had 96. The one-test difference came from the v1.0.1
coordinator pin change. This reconciles the former 95/96 report discrepancy.

## Executed checks

T09 module suite:

```powershell
$env:PYTHONPATH = 'spike/T09/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider spike/T09/tests
```

Result: **113 passed, 0 failed, 0 skipped** in 1.96s. This includes 17
regression cases added after the reviewed 96-test v1.0.1 baseline. Coverage was
not measured.

Framework contract suite:

```powershell
$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider tests/contracts
```

Result: **31 passed, 0 failed, 0 skipped** in 6.92s.

Shared dataset validator:

```powershell
$env:PYTHONPATH = 'packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
```

Result: **13 passed, 0 failed**. All five strict operation fixtures were
validated: `Understanding.extract`, `Events.read`, `Business.read`,
`Evidence.read`, and `Graph.query`. No files outside T09 were changed by the
validator.

Offline evaluator:

```powershell
$env:PYTHONPATH = 'spike/T09/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T09/experiments/evaluate.py
```

Result: **32/32** provisional focus actions matched; merge precision **1.0**
(1 TP, 0 FP), merge recall **1.0** (1 TP, 0 FN), false merge rate **0/31**,
false split rate **0/31**, defer rate **11/71 = 0.15493**. The evaluator wrote
[results/metrics-v1.json](results/metrics-v1.json). These are small, in-sample,
hand-authored provisional expectations, not approved gold labels or an estimate
of production accuracy.

## Regression coverage added

- Merge defers when the incoming event time is outside the duplicate records'
  compatible time scope.
- Merge defers when duplicate predecessors disagree on `disputed` or
  `disproved` status/provenance; `disproved` mentions also defer.
- Merge successors retain distinct assertion statuses and source provenance,
  including separate repost records, instead of collapsing them by fact alone.
- A same-type source aggregate with mentions at distinct facility IDs splits
  into separate event records.
- Actor/object role inversion blocks attachment even when entity IDs are shared.
- An unrelated entity fact cannot correct `/event/successor_supplier`; wrong
  predicate, namespace, vocabulary version, or entity kind does not satisfy
  that datum.
- A correction clears only the matching `valid_to` missing datum and retains
  an unrelated predecessor `/event/successor_supplier` unknown.
- `merged` lifecycle records are excluded from candidate retrieval.
- Mention IDs that collide after normalization receive distinct bounded event
  IDs.
- The policy reference is demonstrably opaque until an owner binds it to
  runtime parameters; the gap and local threshold behavior are documented.

The suite also covers positive/negative decisions, strict DTO and operation-pair
semantics, incomplete/contradictory/unknown data, boundaries, determinism,
provenance, security, reproducibility, regression, and metamorphic changes.
Fixtures remain provisional.

## Quality status

| Dimension | Status | Evidence |
|---|---|---|
| Engineering quality | **PRELIMINARY PASS** | Executable offline prototype; 113 T09 tests and 31 contract tests pass; 13 shared validator checks pass; no dependencies added |
| Algorithm quality | **PRELIMINARY** | 32 synthetic groups; evaluator metrics above; no independently approved labels or real-news evaluation |
| Model quality | **NOT MEASURED** | No LLM, embedding, or live comparator was invoked |
| Integration readiness | **NOT READY** | The approved request carries only an opaque policy `VersionedRef`; runtime threshold binding is unresolved; no operation envelope, service, `Events.apply`, or persistence integration |
