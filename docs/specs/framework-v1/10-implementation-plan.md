# План реализации и параллельная разработка

Текущее состояние: T00 выполнена; bootstrap и doctor проверены на Windows и в Linux userland через WSL. T01 объединена в main через PR #1. T02 (PR #2), T03 (PR #4) и T04 (PR #3) реализованы в последовательных PR и проходят интеграционную приёмку; merge не выполнен. T05–T18 не начаты. Отдельная проверка на native Linux-хосте и повторная clean-room приёмка остаются в T18. Архитектурных развилок для исполнителя в этих задачах нет; выявленный конфликт или неоднозначность поднимается в spec review.

## Этапы и блокировки

| Задача | Результат / рекомендуемый владелец | Blocked by | Проверяемая приёмка |
|---|---|---|---|
| T00 Toolchain и чистый checkout — выполнено | Root README, exact runtime manifest, uv/npm locks, Compose PostgreSQL, базовые bootstrap/doctor CLI; platform | подтверждение spec | Windows и Linux userland в WSL создают окружение и подключаются к изолированной DB без model keys; повтор не разрушает state; versions/digest pinned. Native Linux и полный clean-room bootstrap/doctor повторно проверяются в T18 |
| T01 Pydantic и schemas | 215 моделей/типов, semantic validators, OpenAPI export, 25 descriptors; contracts owner | T00 | Реализовано; независимый аудит PASS после owner-ссылок и уточнения `confirmed`. OpenAPI shape, operation bindings, refs/extra/scalars/unions и положительные/отрицательные wire cases проверены; PR review ожидается |
| T02 Shared fixtures и public Protocol | approved radio/steel datasets, operation fixtures, input/output hash rules, Protocol/context stubs; contracts + QA | T01 | каждый mock operation имеет достаточный воспроизводимый сценарий; versions/hashes; consumer bindings валидируются |
| T03 Минимальный execution slice | Documents.prepare real/mock → typed HTTP → trace → общий UI editor; platform + frontend | T01 | одно выполнение через HTTP/CLI/Playground, actual execution metadata, schema errors sanitized |
| T04 Owner storage и receipts | migrations, DB-role isolation, artifacts, generic owner transaction helper, Documents.register/read; storage | T01 | roundtrip command/read, concurrent duplicate/conflict/crash, artifact hashes, scope isolation |
| T05 Run History и gateway | реальные run/spans/dependency records, Runs.query, safe errors/metrics; platform | T03,T04 | history before/after failures, partial trace, actual timings, unknown cost; no secret echo |
| T06 Policy и replay kernel | independent data gates, cassette matching, clock/RNG, replay denial; platform/security | T02,T05 | missing/changed records fail; blocked raw egress; canary tests; metadata-only replay unavailable |
| T07 Sources и Documents завершение | Sources.fetch mock/test source adapter, Documents.prepare/register/read vertical slice; sources owner | T02,T04,T05 | все 4 operations API/UI/contracts; inline prepare без fetch; source timeout/empty; spans/hash |
| T08 Understanding | classify/extract mocks, alternative mock, registered placeholders real; understanding owner | T02,T03,T05 | обе независимы; multi-label/multi-event/unknown, evidence spans; common tests/UI |
| T09 Events | propose_resolution/apply/read с isolated state; events owner | T02,T04,T05 | snapshot-only proposal; create/attach/correct/merge/split/defer; no silent overwrite; receipts/history |
| T10 Business | profile/questions/apply/read; business owner | T02,T04,T05 | sparse/conflicting profile, skips/declines, stateful commands, independent tests/UI |
| T11 Evidence | register/read, anchor verification и owner source ports; evidence owner | T02,T04,T05 | wrong hash/span rejected; Documents/Business/Runs sources; scope access; proof readback |
| T12 Graph | build/publish/query, projection manifest/freshness; graph owner | T02,T04,T05 | canonical statements unchanged; alternate ontology fixture; fresh/stale/history/unknown; scoped invalidation |
| T13 Matching/Impact/Recommendations | 3 operations, mocks и shared invariant suite; analytics owner | T02,T03,T05 | no business DB dependencies; no made-up quantities; action allowlist/approval; compare mock variants; no-path Impact remains unknown unless separate supplied evidence supports a conclusion, and `none_found` is never silently mapped to neutral/no risk |
| T14 Cases/Evaluation | save/query + evaluate; experiment owner | T02,T04,T05 | replayable draft roundtrip, exact/property/facts rules, noncomparable mismatched input, no automatic gold |
| T15 Playground завершение | catalog, parameters, history, evidence, save/load/replay/compare/transfer; frontend | T03,T05,T06 | common UI all controls; тестовые endpoint fixtures до готовности модулей; 25-operation E2E после интеграции |
| T16 Scenarios и checkpoints | document-business-impact v1, CLI stop/resume, typed bindings; integration owner | T06–T14 | full mock/mixed, stop after each step, no duplicate command, resume conflict rules |
| T17 CI matrix | все jobs и machine readiness artifact; QA/platform | T01; final gate T07–T16 | 25 rows, test evidence, no silent skip; matrix tied to build/schema/fixture hashes |
| T18 Clean-room приёмка | fresh checkout + bootstrap + E01–E14 + review risks; команда | T15,T16,T17 | Framework Ready report, reproducible demo, all mandatory gates; algorithm/product отдельны |

T06–T14 в dependency T16 означает все задачи T06,T07,T08,T09,T10,T11,T12,T13,T14. Dependencies не требуют готовых AI-моделей.

Промежуточные slices не объявляются Framework Ready. T03 записывает настоящие spans через временный in-memory RunsWriter, без обещания персистентности/replay; T05 подключает persistent writer через тот же interface. T04 проверяет owner storage/transaction integration; окончательная HTTP-приёмка команд ждёт T05 с обязательной историей. Так trace в T03 и commands в T04 не создают циклическую зависимость от T05. Bootstrap/doctor T00 проверяют только уже доступные ресурсы; seed, 25-operation smoke и UI добавляются своими задачами и принимаются в T18.

## Что можно делать параллельно

- После T01 frontend начинает T03, storage — T04, QA — T02 и основы T17.
- После T02 владельцы разрабатывают алгоритмические mocks и contract tests T07–T14 независимо, используя agreed Protocol и test doubles инфраструктуры. Финальная приёмка ждёт T04/T05.
- T09 не ждёт настоящего extraction: принимает fixture mentions/snapshot. T12 не ждёт Business: принимает KnowledgeSnapshot. T13 не ждёт Sources/Graph backend: получает inline input.
- Frontend T15 использует реальные schemas и HTTP mocks общего backend, не вторую бизнес-реализацию.
- Сборка T16 ждёт всех slices, но typed bindings могут проверяться сразу после T02.

## Definition of Done задачи операции

Одна задача завершается вертикально: DTO/validators → descriptor/DI → implementation → HTTP → fixtures/contract tests → общий Playground → history/provenance/replay profile. Нельзя закрыть задачу только наличием класса или URL.

Shared dependencies команды передают через interfaces. Не разрешается «временно» импортировать private соседнего модуля. Изменения shared schema: отдельный PR с consumer compatibility report. У каждого PR указаны затронутые operation IDs, fixture versions, tests и риск migration. Integration branch остаётся green; experimental real quality report может быть unavailable, contract failure — блокировка разрешённой реализации.

## Проверка параллельности

В E12 один разработчик/agent добавляет тестовый classifier implementation, другой — альтернативный Impact implementation. Оба меняют только свои implementation/fixtures и registry registration. После объединения все existing consumers/scenarios проходят без правки соседнего module core. Если требуются изменения operation contract — это отдельная согласованная задача, не доказанная независимая замена.

## Учёт объёма

Оценки времени не выдумываются. После T03/T04 фиксируется фактическая трудоёмкость первого compute и command/read slice; пересчитывается прогноз T07–T14. Каталог 25 остаётся закрытым. Необходимость новой операции/сервиса оформляется change proposal: требование, проваливающийся тест, минимальное решение, стоимость и альтернативы.

## Передача coding agent

Читать README этого пакета, затем свою карточку 03-operations, соответствующие contracts и обязательные runtime/storage/policy sections. Выполнять только незаблокированную задачу. Контракт и проверки определяют результат. При конфликте документов записать конкретные ссылки и остановить зависимую часть; остальные независимые задачи могут продолжаться. После изменения запустить применимый suite и обновить readiness evidence, не вручную status.
