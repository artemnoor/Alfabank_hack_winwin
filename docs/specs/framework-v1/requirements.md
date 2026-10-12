# Трассировка требований

| Требование | Нормативное место | Доказательство / задача |
|---|---|---|
| Закрытые 25 операций | contracts/operations.json; 03-operations.md | C02, T01, T17 |
| Полные типизированные DTO/OpenAPI/Pydantic | contracts/openapi.json; pydantic-models.md; 02-contracts.md | C01, schema export diff, T01 |
| Независимый HTTP и inline analytical input | 01-architecture; 03-operations | C02/C04, E01/E12 |
| DI, заменяемость, отсутствие private imports | 01-architecture; 04-execution | C09, E12, T03 |
| Mocks и stateful fake commands | 03-operations; 05-storage | C03, K01–K04, T02/T04 |
| Full mock + mixed E2E | 06-replay-scenarios | E01/E02, T16 |
| Единый продукт/CLI/Playground execution | 04-execution | same semantic result HTTP/CLI, T03/T16 |
| Профиль/события/граф не нужны из рабочей БД для compute | 03-operations; 06-replay-scenarios | independent fixed snapshot tests |
| Proposal/apply, owner state, idempotency | 05-storage | K01–K04, E07/E14 |
| Source/Evidence/provenance | 02-contracts; 05-storage | C06, E03, T11 |
| Реальная наблюдаемость, unknown metrics | 04-execution; 07-playground | C05, E14, T05 |
| Strict record/replay и nondeterminism | 06-replay-scenarios | C07, E05, T06 |
| Stop/checkpoints/resume | 06-replay-scenarios | E09, T16 |
| Graph projection + scoped staleness/history | 05-storage | E08, T12 |
| Отдельные environments и side effects | 09-local-data | C08/C09, E06 |
| Независимые processing/egress/record/export permissions | 09-local-data | E13, T06 |
| История/cases/catalog/config API предусмотрены | 02-contracts; 07-playground | system metadata + 22–25, T05/T14/T15 |
| Минимальный Playground | 07-playground | C10, T15 |
| Утверждение fixtures отдельно от saved output | 08-verification; 09-local-data | E04, code review/manifest approval |
| Framework/Algorithm/Product раздельны | README; 08-verification | separate readiness gates |
| Clean checkout и воспроизводимость toolchain | 09-local-data; T00 | E11, T18 |
| Проверяемая параллельная разработка | 01-architecture; 10-implementation-plan | E12, module slices T07–T14 |
| Минимальная инфраструктура | README; 11-decisions-risks | dependency review, closed catalog |
| Риски не объявляются решёнными без проверки | 11-decisions-risks | R01–R12 и evidence tasks |
| Код пока не писать | текущий пакет | только Markdown/JSON specification artifacts; приложение отсутствует |
