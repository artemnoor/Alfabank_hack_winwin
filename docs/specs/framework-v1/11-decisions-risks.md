# Решения, альтернативы и риски

## Утверждённая основа

| Решение | Выбрано | Альтернатива / компромисс |
|---|---|---|
| Исходная цель и приоритеты | переносимый каркас; независимые тесты, параллельность, контролируемые mocks и замена компонентов | готовый бизнес-продукт до кейса / универсальная платформа отложены |
| Q4–Q7 | modular monolith, DI, независимый HTTP, общий execution, materialized analytical inputs | меньше deployment overhead; границы нужно проверять |
| Q8–Q11 | public operation как единица; server isolation; execution/data provenance; strict replay | инфраструктура сложнее простого mock response, но доказуемая |
| Q12–Q17 | укрупнение обосновано ответственностью; Sources/Documents и Understanding/Events разделены; owner state; proposal/apply | больше явно тестируемых операций, меньше скрытых effects |
| Q14/Q18 | graph projection, scoped freshness/history/completeness | нужны projection manifests и проверка неполных зависимостей |
| Q19/Q22 | experiments != approved fixtures; synthetic/public only; independent data gates | закрытые данные требуют отдельного будущего решения |
| Q20–Q21 | closed 25 operations, CI readiness; Framework/Algorithm/Product раздельны | объём значительный; хорошие mocks не доказывают качество AI |
| Q23–Q24 | versioned code scenarios, stop/resume, explicit compatibility | нет произвольных workflows и одновременного исполнения всех версий |

## Конкретизации этой спецификации

Не являются результатом испытаний: baseline runtime/React stack, PostgreSQL 16 + owner roles, filesystem artifacts, POST для всех typed invokes, один current contract=1.0.0, receipt query в существующих read operations, JSON artifact transport для history, initially real.prepare, limits defaults, manual synthetic review CLI. Они выбраны для реализации требований без новых public operations. Изменение проходит spec review до реализации затронутой части.

## Риски и проверки

| ID | Риск | Эксперимент/доказательство | Где закрывается |
|---|---|---|---|
| R01 | 25 операций слишком дороги | реальная стоимость T03/T04; корректировка прогноза без скрытого урезания | T03/T04/T18 |
| R02 | graph contract привязан к ontology | две projections одних Statements, explicit incompatibility tests | T12 |
| R03 | неправильные merge/split | curated duplicate/ambiguous/correction cases; reference history checks | T09 + будущая Events session |
| R04 | commit без надёжного receipt/audit | concurrent commands, fault points before commit/after commit/before response | T04/T09/T10/T12 |
| R05 | resume дублирует effects | interrupted checkpoint and changed-state tests | T16 |
| R06 | скрытый nondeterminism | egress-denied replay, frozen clock/RNG, recorded read tests | T06/T17 |
| R07 | fact-level provenance чрезмерно велик | измерение artifact sizes и traversal bounds на approved dataset | T11/T12/T18 |
| R08 | секрет/closed data утекли через errors/traces | canary tests + independent gates; автоматический scan не универсален | T06/T17 |
| R09 | несовместимые LLM capabilities | capability registry + typed parameters, unsupported parameters fail | новая real implementation |
| R10 | framework пригоден только для текущего бизнеса | небольшой второй scenario другой области без правки execution ядра | после Framework Ready, до заявления универсальности |
| R11 | исторические знания содержат future leak | valid/known cut tests, frozen source snapshots | T09/T10/T12 |
| R12 | local role/DB setup слишком сложен | clean Windows/Linux bootstrap с diagnosis/retry | T00/T18 |

## Что остаётся открытым намеренно

- Поведение команды, предлагающей `confirmed`, если Evidence целостно, но политика владельца не разрешает подтверждение: отклонять всю команду или сохранять предложение в непроверенном виде. До T09/T10 команда не должна молча понижать статус или сохранять `confirmed` без разрешения.
- Реальный кейс, продуктовая аудитория, разрешённые данные и Product Ready критерии.
- Модели/провайдеры/графовая БД сверх baseline, лицензии источников и реальная стоимость.
- Quality thresholds, независимый gold dataset, правила calibration и исследовательское сравнение C/D.
- Production throughput/SLA, retention/privacy policy закрытых данных, настоящая доставка уведомлений.
- Полная онтология/отраслевые predicates, сложное entity resolution и причинные правила.

Эти вопросы не дают исполнителю права выбирать произвольные значения в каркасе. Он использует demo ontology/rules и mocks из approved fixtures; для real-добавления требуется отдельная спецификация.

## Отложено

Микросервисы по блокам, Kafka/event platform, Redis, workflow DSL/editor, parallel workflow/сложные очереди, промышленный graph stack, отдельная lab business backend, реальная notification delivery, закрытые банковские данные, автоматическое gold approval и много одновременно исполняемых версий.

## Следующие отдельные сессии

1. Understanding/Events: taxonomy, extraction evidence, identities и независимая оценка.
2. Business: sparse profiles, statements, contradictions, question usefulness.
3. Graph: ontology evolution, projection/freshness и backend substitution.
4. Matching/Impact: exposure против causality, C/D, uncertainty и gold.
5. Sources/Documents: реальные источники, formats, legal reuse, throughput.
6. Recommendations/Evaluation: allowed actions, quality metrics, Product Ready.
