# Проверки и CI-матрица готовности

## Виды готовности

Framework Ready: все обязательные checks 25 операций + infrastructure/global gates passed. Algorithm Ready: отдельная implementation прошла независимые gold/metamorphic/property/quality tests по утверждённым thresholds. Product Ready: реальный кейс, полезность, эксплуатация и пользовательские требования подтверждены. Отсутствующий real не блокирует Framework Ready; несовместимый real не включается в разрешённый профиль.

## Матрица

CI экспортирует readiness.json и HTML view. Source: contracts/operations.json + JUnit/test evidence, не вручную заполненные галочки. Ключ результата: git build hash, contract/schema closure hashes, fixture manifest hash, runtime lock hash. Старый отчёт другой сборки не отображается как готовность текущей.

Строка: operation_id + implementation_id/version. Колонки: contract, http, mock, fixtures, independent, playground, history, provenance, replay, negative, boundaries, idempotency, state_conflict, receipt_recovery, real_availability, algorithm_quality. Status passed|failed|not_run|not_applicable|unavailable, evidence test IDs, reason. not_applicable требует статического обоснования из descriptor и review. not_run не passed. algorithm_quality и real_availability не сливаются с framework gate.

## Набор проверок каждой операции

| ID | Проверка | Применимость |
|---|---|---|
| C01 | Request/output/error schemas, extra fields и scalar coercion | все |
| C02 | operation ID/path совпадают с registry; HTTP independent fixture | все |
| C03 | общие semantic tests всех разрешённых implementations | все |
| C04 | fixtures валидны, input hashes/versions верны | все |
| C05 | history, actual implementation/config, metrics unknown semantics | все |
| C06 | provenance preservation и server-derived summary | все |
| C07 | strict replay profile, network miss и artifact tampering | все, с различием profile |
| C08 | sandbox/tenant/access/policy отрицательные случаи | все |
| C09 | изоляция импортов/SQL/network dependencies | все |
| C10 | operation доступна в общем Playground | все |
| K01 | duplicate key возвращает исходный receipt | commands |
| K02 | changed payload/key и expected revision conflict | commands |
| K03 | concurrency и crash before/after commit | commands |
| K04 | restored before-state replay, semantic after-state | commands |
| R01 | historical/version read, pagination/missing object | reads |
| S01 | controlled external server: empty, timeout, malformed response | source |

Чтения и commands используют реальную PostgreSQL в integration tests. Unit fakes не заменяют transaction/permissions tests. Mock AI fixtures не заменяют quality benchmark.

## Сквозные сценарии

- E01 full mock document-business-impact, evidence и provenance доступны.
- E02 mixed: real.prepare + mock algorithms, та же программа.
- E03 synthetic lineage через >=3 операции, persistence/load; origin не становится real.
- E04 save/load case, strict replay, compare; saved output не получает gold approval.
- E05 missing cassette, changed prompt/hash, hidden network: fail closed.
- E06 cross-tenant/sandbox и попытки production DSN/provider override.
- E07 command conflict/concurrent duplicate/crash; unknown outcome разрешается receipt.
- E08 graph staleness: unrelated company, used fact, new relevant fact, shared rules и historical cut.
- E09 stop_after каждого шага; resume без дублей; version/state mismatch → RESUME_CONFLICT.
- E10 schema compatibility + consumer bindings + two implementations same frozen inputs.
- E11 чистый локальный bootstrap, seed, Playground и smoke без model key.
- E12 добавление тестовой implementation одного модуля без правки соседей/HTTP/UI; registry + contract suite обнаруживают её.
- E13 canary secrets во входах/headers/provider errors отсутствуют в logs, trace, artifacts и export; classified forbidden data не уходят external.
- E14 отказ history до команды блокирует mutation; отказ history после commit оставляет receipt и явный partial/unknown trace.

## CI jobs

1. docs-contracts: OpenAPI/schema validation, unique 25 IDs, ref closure, examples, Pydantic export diff.
2. static: ruff, mypy strict, TS typecheck, import boundary checks.
3. contracts-unit: parametrized contract/semantic suite; no live Internet/model keys.
4. postgres-integration: migrations, isolated DB roles, owner tests и concurrency/fault injection.
5. strict-replay: egress denied; deterministic state fixtures, missing/tampered records.
6. browser: build UI, start API, Playwright all 25 operations + common flows.
7. windows-bootstrap: документированный PowerShell clean procedure + seed + smoke. Linux job проверяет тот же CLI.
8. readiness: собирает полную matrix, failure при обязательном not_run/failed; публикует JSON/HTML/JUnit.
9. data-scan: Git diff, fixtures/export/artifacts manifest на секреты и запрещённые classifications; raw artifacts не публикуются как CI logs.

Jobs без model keys; opt-in live evaluation отдельный, не часть default CI. .local и generated secrets не попадают в git. Fixtures из external versioned store скачиваются только из allowlist и проверяются hashes; default набор маленький и локальный.

## Fixtures

fixtures/approved/<operation_id>/<case_id>/manifest.json: schema/version, before_state refs, request, expected error/result rules, cassette refs, analytical_time, seed, classification, approval review reference, hashes. Small payloads inline; large только verified refs. Минимум: success; domain empty/unknown где применимо; invalid input; характерный отказ. Commands дополнительно duplicate, conflict и restored-state. Reads additionally missing/forbidden.

Два сквозных datasets: radio-export-v1, steel-buffer-v1. Несколько событий/дубли/противоречия присутствуют в fixtures Understanding/Events. Quality expectations могут быть exact, properties, fact set или metric thresholds; scope оценки явно задаётся. Изменение expected требует review независимо от реализации.
