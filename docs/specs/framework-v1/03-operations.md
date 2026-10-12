# Закрытый каталог 25 публичных операций

Версия всех операций — 1.0.0. Owner — логическая ответственность, не отдельный процесс. Полная форма request/response и всех вложенных полей: [OpenAPI](contracts/openapi.json) и [декларативные модели](contracts/pydantic-models.md). Карточки задают семантику и обязательства сверх формы JSON.

## Общие обязательства каждой операции

Все операции: typed payload Protocol + descriptor + independent POST endpoint + mock.baseline@1.0.0 + approved fixtures + C01–C10 + общий Playground. Commands дополнительно K01–K04, reads R01, Sources.fetch S01. Даже compute пишет техническую историю через общий executor; это не доменная мутация. Все errors имеют общий ErrorResponse, безопасный outcome и настоящий trace.

Mock baseline детерминирован по semantic input hash + fixture version + seed. Scenario=default выбирает согласованный fixture recipe по входному case; неподдерживаемая комбинация даёт INVALID_INPUT, а не случайный canned result. Mocks обязаны соблюдать общие инварианты, но их результаты не объявляются проверкой качества real. Scenario empty/partial/contradictory применяется только к согласованному fixture; недопустимая комбинация отклоняется. Fault modes timeout/retryable_error/fatal_error — общая fault-injection обёртка до вызова core; crash после commit проверяется отдельно, не этой обёрткой.

У commands/read mock означает deterministic implementation над настоящим изолированным owner repository. Register/apply/publish/save и последующее read видят одно согласованное состояние. Тесты fixtures указывают before-state, expected result properties и after-state. Изолированное тестирование не требует соседних алгоритмов: inline bundles либо минимальный seed state + typed read adapters. Для API приёмки включается настоящий общий executor.

Минимальные fixtures каждой операции: перечисленные ниже предметные случаи, invalid request/extra field/scalar coercion, denied scope, fault modes, replay success/miss. Timeout без реального ожидания моделируется controlled dependency; observed duration измеряется фактически. Утверждение fixtures — отдельный code review. Контрактный example JSON не подменяет этот suite.

## Индекс

| № | Операция | Вид | HTTP |
|---|---|---|---|
| 1 | Sources.fetch | source | POST `/api/v1/sources/fetch` |
| 2 | Documents.prepare | compute | POST `/api/v1/documents/prepare` |
| 3 | Documents.register | command | POST `/api/v1/documents/register` |
| 4 | Documents.read | read | POST `/api/v1/documents/read` |
| 5 | Understanding.classify | compute | POST `/api/v1/understanding/classify` |
| 6 | Understanding.extract | compute | POST `/api/v1/understanding/extract` |
| 7 | Events.propose_resolution | compute | POST `/api/v1/events/propose-resolution` |
| 8 | Events.apply | command | POST `/api/v1/events/apply` |
| 9 | Events.read | read | POST `/api/v1/events/read` |
| 10 | Business.propose_profile | compute | POST `/api/v1/business/propose-profile` |
| 11 | Business.propose_questions | compute | POST `/api/v1/business/propose-questions` |
| 12 | Business.apply | command | POST `/api/v1/business/apply` |
| 13 | Business.read | read | POST `/api/v1/business/read` |
| 14 | Graph.build | compute | POST `/api/v1/graph/build` |
| 15 | Graph.publish | command | POST `/api/v1/graph/publish` |
| 16 | Graph.query | read | POST `/api/v1/graph/query` |
| 17 | Matching.match | compute | POST `/api/v1/matching/match` |
| 18 | Impact.assess | compute | POST `/api/v1/impact/assess` |
| 19 | Recommendations.propose | compute | POST `/api/v1/recommendations/propose` |
| 20 | Evidence.register | command | POST `/api/v1/evidence/register` |
| 21 | Evidence.read | read | POST `/api/v1/evidence/read` |
| 22 | Runs.query | read | POST `/api/v1/runs/query` |
| 23 | Cases.save | command | POST `/api/v1/cases/save` |
| 24 | Cases.query | read | POST `/api/v1/cases/query` |
| 25 | Evaluation.evaluate | compute | POST `/api/v1/evaluation/evaluate` |

## 01. Sources.fetch

Получить одну ограниченную страницу материалов из зарегистрированного источника; ничего не регистрировать как документ.

- **Владелец / тип:** `sources` / `source`.
- **HTTP:** `POST /api/v1/sources/fetch`; `operationId=Sources.fetch`.
- **Вход:** `Sources_fetchRequest` → `FetchInput`: `source_id`, `cursor`, `since`, `limit`.
- **Выход:** `Sources_fetchResponse` → `FetchOutput`: `materials`, `next_cursor`, `warnings`.
- **Разрешённые доменные зависимости:** SourceAdapter, SourcePolicy, ClockPort; source_id разрешается только серверным registry.
- **Читаемое состояние:** Нет business-state; adapter cursor передан явно.
- **Изменяемое состояние / эффекты:** Нет. Сеть источника — внешний эффект; cursor возвращается, не коммитится скрыто.
- **Правила и характерные отказы:** Не более limit материалов; нормализованный RawMaterial сохраняет исходный текст и URL. Повторный fetch может получить дубли: это не новая идентичность события. URL из текста не открывается. Partial page явно помечена; malformed upstream → DEPENDENCY_FAILED.
- **Fixtures:** page: 2 синтетические статьи и next_cursor; empty: 0 материалов; timeout: controlled server задерживает ответ; malformed: upstream нарушает форму; forbidden-source: незарегистрированный source_id.
- **Replay:** Подставить записанные ответы SourceAdapter; ни одного живого сетевого запроса в strict replay.
- **Приёмка:** C01–C10; S01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 02. Documents.prepare

Нормализовать явно переданный текст, сохранив проверяемое соответствие исходным символам.

- **Владелец / тип:** `documents` / `compute`.
- **HTTP:** `POST /api/v1/documents/prepare`; `operationId=Documents.prepare`.
- **Вход:** `Documents_prepareRequest` → `PrepareInput`: `material`, `normalize_newlines`, `trim_outer_whitespace`.
- **Выход:** `Documents_prepareResponse` → `PrepareOutput`: `prepared`.
- **Разрешённые доменные зависимости:** Нет доменных read ports или сети.
- **Читаемое состояние:** Только inline RawMaterial.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** real.prepare: CRLF/CR → LF при normalize_newlines, затем удаление Unicode whitespace только по краям при trim_outer_whitespace; иной редакции текста нет. material содержит подготовленный текст и его hash, raw_hash относится к исходному. SpanMap задаёт монотонное отображение code points; CRLF → LF отображает один output code point на два input code points. Для пустого текста quality=rejected, map=[], warning=empty_text; непустой текст quality=valid. Неподдерживаемая разметка не очищается молча.
- **Fixtures:** normalize: CRLF, кириллица, emoji и крайние пробелы; unchanged: оба флага false; empty: пустой текст; bad-hash: INVALID_INPUT. Mock baseline на этих входах имитирует ровно эти правила; mock alternative меняет разрешённые warnings, не смысл текста.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 03. Documents.register

Зарегистрировать новую immutable версию документа и вернуть receipt.

- **Владелец / тип:** `documents` / `command`.
- **HTTP:** `POST /api/v1/documents/register`; `operationId=Documents.register`.
- **Вход:** `Documents_registerRequest` → `RegisterDocumentInput`: `document_id`, `expected_revision`, `raw`, `prepared`.
- **Выход:** `Documents_registerResponse` → `RegisterDocumentOutput`: `version`, `receipt`.
- **Разрешённые доменные зависимости:** DocumentsRepository, owner transaction, ArtifactStore, ScopePolicy.
- **Читаемое состояние:** Текущая ревизия document_id и собственные receipts.
- **Изменяемое состояние / эффекты:** documents aggregate/version, owner audit/receipt.
- **Правила и характерные отказы:** expected_revision=0 создаёт новый документ. Новая версия содержит raw и опционально prepared; parent_ref указывает предыдущую версию документа, а raw_hash связывает prepared с raw в той же версии. Подготовленный текст не подменяет raw. Новый register с тем же semantic content и новой key возвращает существующую версию, applied=false; audit/receipt остаются. Не создаётся ложная новая публикация из-за повторного fetch.
- **Fixtures:** create: raw+prepared; revise: изменённый текст при revision=1; duplicate-key: тот же receipt; duplicate-content: новая key, версия не растёт; conflict: stale expected_revision; invalid-map: rollback.
- **Replay:** Полный replay только в новом sandbox из before-state + записанных dependencies; сверить semantic after-state и receipt. Read-back из соседних owners также фиксируется.
- **Приёмка:** C01–C10; K01–K04; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 04. Documents.read

Прочитать immutable версии документов либо receipt регистрации.

- **Владелец / тип:** `documents` / `read`.
- **HTTP:** `POST /api/v1/documents/read`; `operationId=Documents.read`.
- **Вход:** `Documents_readRequest` → `ReadDocumentsInput`: `query`.
- **Выход:** `Documents_readResponse` → `ReadDocumentsOutput`: `DocumentResult` | `ReceiptResult`.
- **Разрешённые доменные зависимости:** DocumentsRepository, ArtifactStore, ScopePolicy.
- **Читаемое состояние:** documents versions/receipts.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** revision и as_of одновременно запрещены. Без revision/as_of берётся последняя доступная версия. С as_of выбирается последняя recorded_at<=known_as_of, опубликованная не позже valid_as_of, если published_at известен; отсутствие published_at не создаёт выдуманную дату и возвращает warning в документе. missing_ids явно перечислены. Receipt branch допустим только для Documents.register.
- **Fixtures:** latest: документ после revise; historical: версия до исправления; missing: неизвестный ID в missing_ids; receipt: найден/не найден; forbidden: другой sandbox.
- **Replay:** Повторное вычисление read response над recorded owner-read snapshot. Корректность SQL отдельно проверяется на восстановленной PostgreSQL.
- **Приёмка:** C01–C10; R01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 05. Understanding.classify

Классифицировать документ независимо от extraction.

- **Владелец / тип:** `understanding` / `compute`.
- **HTTP:** `POST /api/v1/understanding/classify`; `operationId=Understanding.classify`.
- **Вход:** `Understanding_classifyRequest` → `ClassificationInput`: `material`, `taxonomy`, `allowed_codes`, `multi_label`.
- **Выход:** `Understanding_classifyResponse` → `ClassificationOutput`: `topics`, `event_hints`, `classification_status`, `missing_data`.
- **Разрешённые доменные зависимости:** TaxonomyRegistry; опциональный ModelPort только у соответствующей real implementation.
- **Читаемое состояние:** Только inline material/taxonomy/codes.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** topics/event_hints принадлежат allowed taxonomy/schema. При multi_label=false максимум один topic. unknown type даёт other/uncertain, а не придуманную метку. Raw score не называется вероятностью без отдельной калибровки. Эта операция никогда не запускает extract.
- **Fixtures:** radio-news: export_restriction; multi-topic: две допустимые категории; unknown-topic: other; empty-text: no_content; uncertainty: null score; bad-taxonomy: SEMANTIC_VALIDATION.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 06. Understanding.extract

Извлечь ноль или несколько упоминаний событий, сущности и атомарные утверждения из текста.

- **Владелец / тип:** `understanding` / `compute`.
- **HTTP:** `POST /api/v1/understanding/extract`; `operationId=Understanding.extract`.
- **Вход:** `Understanding_extractRequest` → `ExtractionInput`: `material`, `event_schema`, `hints`, `known_entities`.
- **Выход:** `Understanding_extractResponse` → `ExtractionOutput`: `mentions`, `evidence_spans`, `unresolved_entities`, `missing_data`.
- **Разрешённые доменные зависимости:** EventSchemaRegistry, опциональный ModelPort; classification не является зависимостью.
- **Читаемое состояние:** Только material, hints, known_entities.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** hints=[] допустим. Один документ может дать несколько mentions. Unknown event type сохраняется согласованным other/unknown code и исходным evidence. Нет сетевой entity resolution. Evidence spans ссылаются на prepared_hash; binding переводит их в raw spans по span_map перед Evidence.register. Extraction не авторизует `confirmed`: для этого нужны сохранённая Evidence-ссылка, проверенные Evidence owner hash/anchor и явно разрешающая Events/Business owner policy при применении.
- **Fixtures:** two-events: ограничение экспорта и изменение цены; no-event: mentions=[]; contradictory: два утверждения с источниками; unknown-actor: unresolved_entities; invalid-span: output validation failure.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 07. Events.propose_resolution

Предложить создание, привязку, исправление, объединение или разделение канонических событий.

- **Владелец / тип:** `events` / `compute`.
- **HTTP:** `POST /api/v1/events/propose-resolution`; `operationId=Events.propose_resolution`.
- **Вход:** `Events_propose_resolutionRequest` → `ResolutionInput`: `mentions`, `existing`, `evidence`, `policy`.
- **Выход:** `Events_propose_resolutionResponse` → `ResolutionOutput`: `proposal`.
- **Разрешённые доменные зависимости:** Versioned ResolutionPolicy; опциональный ModelPort. Рабочая Events БД не требуется.
- **Читаемое состояние:** Явно переданный EventSnapshot и EvidenceRecord[].
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Не изменяет существующие event IDs. Каждое mention имеет решение либо unresolved_mentions. Неуверенное совпадение можно defer. create/attach/correct/merge/split имеют разные инварианты. Новый extraction сам по себе не переписывает канонические события.
- **Fixtures:** new: create одного события; duplicate: attach к существующему; correction: новая версия факта; merge: два predecessor → один successor; split: один → два; uncertain: defer; incompatible-snapshot: ошибка.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 08. Events.apply

Атомарно применить допустимое предложение разрешения событий.

- **Владелец / тип:** `events` / `command`.
- **HTTP:** `POST /api/v1/events/apply`; `operationId=Events.apply`.
- **Вход:** `Events_applyRequest` → `ApplyEventsInput`: `proposal`, `expected_revisions`, `evidence`.
- **Выход:** `Events_applyResponse` → `ApplyEventsOutput`: `snapshot`, `receipt`.
- **Разрешённые доменные зависимости:** EventsRepository/transaction, EvidenceReadPort для проверки ссылок, scope policy.
- **Читаемое состояние:** Указанные Events aggregates/receipts и immutable Evidence refs.
- **Изменяемое состояние / эффекты:** events versions/statements/lifecycle/lineage, audit/receipt.
- **Правила и характерные отказы:** Проверяются source_snapshot и expected_revisions всех targets. Для новых IDs expected_revision=0. Перед сохранением каждого `confirmed` Statement Events разрешает его Evidence refs через Evidence owner, проверяет scope/hash/anchor и требует явной Events owner policy, допускающей это основание. Anchor verification не доказывает истинность; отсутствие разрешающей policy оставляет утверждение `unknown`/unverified. merge/split создают successors и сохраняют predecessors c lifecycle; lineage ациклична. Несогласованная одна из правок откатывает всю команду владельца. Выходной snapshot содержит затронутые события и новую revision partition.
- **Fixtures:** create/apply; merge с историей; split; duplicate-key; competing-revision: VERSION_CONFLICT; missing-evidence: rollback; crash-after-commit: recovery по Events.read receipt.
- **Replay:** Полный replay только в новом sandbox из before-state + записанных dependencies; сверить semantic after-state и receipt. Read-back из соседних owners также фиксируется.
- **Приёмка:** C01–C10; K01–K04; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 09. Events.read

Прочитать scoped снимок канонических событий или receipt Events.apply.

- **Владелец / тип:** `events` / `read`.
- **HTTP:** `POST /api/v1/events/read`; `operationId=Events.read`.
- **Вход:** `Events_readRequest` → `ReadEventsInput`: `query`.
- **Выход:** `Events_readResponse` → `ReadEventsOutput`: `EventResult` | `ReceiptResult`.
- **Разрешённые доменные зависимости:** EventsRepository и scope policy.
- **Читаемое состояние:** events versions/statements/lineage/receipts.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** event_ids=[] означает выборку partition, не всех tenants. Bitemporal filtering: known_as_of ограничивает запись, valid_as_of — действующие утверждения. limit/cursor дают устойчивую сортировку по event_id; cursor привязан к query/scope и known_as_of. Удалённые merge/split predecessors доступны исторически.
- **Fixtures:** partition-page; historical-before-correction; merged-lineage; empty-partition; receipt-found/absent; cursor-other-scope: отказ.
- **Replay:** Повторное вычисление read response над recorded owner-read snapshot. Корректность SQL отдельно проверяется на восстановленной PostgreSQL.
- **Приёмка:** C01–C10; R01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 10. Business.propose_profile

Получить предложение бизнес-фактов и неизвестных параметров из description, документов и ответов.

- **Владелец / тип:** `business` / `compute`.
- **HTTP:** `POST /api/v1/business/propose-profile`; `operationId=Business.propose_profile`.
- **Вход:** `Business_propose_profileRequest` → `ProfileInput`: `company`, `description`, `documents`, `answers`, `existing`, `as_of`.
- **Выход:** `Business_propose_profileResponse` → `ProfileOutput`: `proposal`.
- **Разрешённые доменные зависимости:** ProfileRules/optional ModelPort; все бизнес-входы inline.
- **Читаемое состояние:** Явный existing snapshot или null.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Фраза «Я продаю радиодетали» подтверждает только пользовательское утверждение о деятельности. География закупок, объёмы, выручка и импортозависимость остаются missing/unknown; гипотезы имеют hypothetical. Отсутствие existing означает expected_revision=0. conflicting facts сохраняются. Ответ skipped не превращается в отрицательный факт.
- **Fixtures:** minimal-radio: только деятельность, неизвестные поставщики/оборот; detailed: сведения с источниками; conflicting: два поставщика без разрешения; skipped-answer; empty: missing_data, без выдуманных фактов.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 11. Business.propose_questions

Предложить ограниченный набор полезных вопросов, не изменяя профиль.

- **Владелец / тип:** `business` / `compute`.
- **HTTP:** `POST /api/v1/business/propose-questions`; `operationId=Business.propose_questions`.
- **Вход:** `Business_propose_questionsRequest` → `QuestionsInput`: `profile`, `event`, `question_history`, `budget`.
- **Выход:** `Business_propose_questionsResponse` → `QuestionsOutput`: `questions`, `stop_reason`.
- **Разрешённые доменные зависимости:** QuestionPolicy/optional ModelPort.
- **Читаемое состояние:** Inline profile, optional event и question_history.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Число вопросов <=min(budget, preferences.max_questions). suppressed_targets и declined соблюдаются. Каждый вопрос объясняет недостающий параметр; can_skip=true в каркасе. Данные для критического решения не требуют бесконечного опроса. Ноль вопросов — нормальный результат со stop_reason.
- **Fixtures:** minimal-profile: вопрос о закупках; budget-zero: questions=[]; declined-target: не спрашивать снова; complete-profile: complete; event-prompt-disabled: event не расширяет вопросы.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 12. Business.apply

Применить предложение фактов, явно переданные ответы и настройки вопросов к одной компании.

- **Владелец / тип:** `business` / `command`.
- **HTTP:** `POST /api/v1/business/apply`; `operationId=Business.apply`.
- **Вход:** `Business_applyRequest` → `ApplyBusinessInput`: `proposal`, `answers`, `preferences`, `evidence`.
- **Выход:** `Business_applyResponse` → `ApplyBusinessOutput`: `snapshot`, `receipt`.
- **Разрешённые доменные зависимости:** BusinessRepository/transaction, EvidenceReadPort, scope policy.
- **Читаемое состояние:** Состояние компании/receipts и Evidence refs.
- **Изменяемое состояние / эффекты:** business versions/statements/answers/preferences, audit/receipt.
- **Правила и характерные отказы:** proposal.expected_revision проверяется на company ID. Supersede сохраняет историю, не удаляет conflicting original. Ответы имеют явные статусы. Nullable preferences означает сохранить прежние; для новой компании defaults max_questions=3, allow_event_prompts=true, suppressed_targets=[]. Перед сохранением `confirmed` Business разрешает Evidence refs через Evidence owner, проверяет scope/hash/anchor и требует явной Business owner policy, допускающей это основание. Anchor verification не доказывает истинность; без разрешающей policy факт остаётся `unknown`/unverified. Универсальный порог source reliability не задаётся.
- **Fixtures:** create-minimal; add-answer; supersede-conflict; skipped-answer; duplicate-key; stale-revision; foreign-statement: rollback; crash receipt recovery.
- **Replay:** Полный replay только в новом sandbox из before-state + записанных dependencies; сверить semantic after-state и receipt. Read-back из соседних owners также фиксируется.
- **Приёмка:** C01–C10; K01–K04; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 13. Business.read

Получить версию профиля компании либо receipt Business.apply.

- **Владелец / тип:** `business` / `read`.
- **HTTP:** `POST /api/v1/business/read`; `operationId=Business.read`.
- **Вход:** `Business_readRequest` → `ReadBusinessInput`: `query`.
- **Выход:** `Business_readResponse` → `ReadBusinessOutput`: `BusinessResult` | `ReceiptResult`.
- **Разрешённые доменные зависимости:** BusinessRepository, scope policy.
- **Читаемое состояние:** business versions/answers/preferences/receipts.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** revision и as_of одновременно запрещены; оба null выбирают последнюю версию. Отсутствующая компания возвращает snapshot=null. Проверяются company_id и receipt operation ID, чужой tenant не раскрывается.
- **Fixtures:** current-minimal; previous-revision; historical-facts; missing-company: null; receipt; forbidden-company.
- **Replay:** Повторное вычисление read response над recorded owner-read snapshot. Корректность SQL отдельно проверяется на восстановленной PostgreSQL.
- **Приёмка:** C01–C10; R01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 14. Graph.build

Построить candidate графа по inline знаниям без публикации или изменения первичных утверждений.

- **Владелец / тип:** `graph` / `compute`.
- **HTTP:** `POST /api/v1/graph/build`; `operationId=Graph.build`.
- **Вход:** `Graph_buildRequest` → `BuildGraphInput`: `graph_id`, `knowledge`, `ontology`, `rules`.
- **Выход:** `Graph_buildResponse` → `BuildGraphOutput`: `candidate`.
- **Разрешённые доменные зависимости:** OntologyRegistry, BuildRules, optional GraphBuilder adapter. БД Knowledge Graph не требуется.
- **Читаемое состояние:** KnowledgeSnapshot со statements/entities/evidence/slices.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Узлы/рёбра замкнуты; отношение разрешено указанной ontology. Inferred relation содержит method/input refs; прямое отношение ссылается на исходный Statement. Candidate revision=0. Manifest отражает именно входные slices и as_of, builder/config. Partial knowledge даёт completeness=partial/unknown, не ложное complete.
- **Fixtures:** radio-minimal: activity node, неизвестная supply dependency; confirmed-chain: 3 nodes/2 edges; contradictory-edge; no-relations: nodes без edges; bad-ontology: SEMANTIC_VALIDATION.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 15. Graph.publish

Сохранить новую immutable графовую проекцию по проверенному candidate.

- **Владелец / тип:** `graph` / `command`.
- **HTTP:** `POST /api/v1/graph/publish`; `operationId=Graph.publish`.
- **Вход:** `Graph_publishRequest` → `PublishGraphInput`: `candidate`, `expected_revision`.
- **Выход:** `Graph_publishResponse` → `PublishGraphOutput`: `projection_ref`, `receipt`.
- **Разрешённые доменные зависимости:** GraphRepository/transaction; KnowledgeReadPorts Events/Business/Documents/Reference для проверки manifest; ArtifactStore.
- **Читаемое состояние:** Свои graph revisions/receipts, указанные версии исходных знаний.
- **Изменяемое состояние / эффекты:** graph projections/nodes/edges, audit/receipt. Исходные знания не меняются.
- **Правила и характерные отказы:** candidate revision=0; graph_id задаёт aggregate, expected_revision задаёт предшественника. Нельзя публиковать candidate с нарушенным manifest или references. Допускается публикация исторического/отстающего candidate с сохранением ограничения; актуальность проверяется при query. Целевой production policy может запретить неподходящие snapshots.
- **Fixtures:** publish-new; publish-rebuild-new-ontology; historical-candidate; duplicate-key; stale-expected-revision; invalid-edge: rollback; changed-source: stored manifest остаётся прежним, query stale.
- **Replay:** Полный replay только в новом sandbox из before-state + записанных dependencies; сверить semantic after-state и receipt. Read-back из соседних owners также фиксируется.
- **Приёмка:** C01–C10; K01–K04; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 16. Graph.query

Вернуть согласованный ограниченный подграф либо receipt Graph.publish.

- **Владелец / тип:** `graph` / `read`.
- **HTTP:** `POST /api/v1/graph/query`; `operationId=Graph.query`.
- **Вход:** `Graph_queryRequest` → `QueryGraphInput`: `query`.
- **Выход:** `Graph_queryResponse` → `QueryGraphOutput`: `SubgraphResult` | `ReceiptResult`.
- **Разрешённые доменные зависимости:** GraphRepository; KnowledgeReadPorts только для scoped freshness comparison.
- **Читаемое состояние:** Указанная graph revision, текущие scoped partition revisions.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Traversal deterministic BFS, sorted seed/node/edge IDs; max_depth/max_nodes соблюдаются. seed_ids=[] означает весь snapshot в пределах max_nodes. relations=[] допускает все отношения ontology. current_required при stale/unknown даёт VERSION_CONFLICT. allow_stale возвращает ограничения; historical требует совпадающий TimeSlice manifest. Missing graph → subgraph=null. Несвязанные company partitions не влияют.
- **Fixtures:** current-chain; unrelated-company-update: current; relevant-new-fact: stale; historical-cut; truncated-BFS; missing; forbidden-ref; receipt.
- **Replay:** Повторное вычисление read response над recorded owner-read snapshot. Корректность SQL отдельно проверяется на восстановленной PostgreSQL.
- **Приёмка:** C01–C10; R01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 17. Matching.match

Найти потенциальное соответствие события компаниям в явно переданном scope.

- **Владелец / тип:** `matching` / `compute`.
- **HTTP:** `POST /api/v1/matching/match`; `operationId=Matching.match`.
- **Вход:** `Matching_matchRequest` → `MatchingInput`: `event`, `graph`, `profiles`, `mode`, `limit`.
- **Выход:** `Matching_matchResponse` → `MatchingOutput`: `matches`, `candidate_scope`, `search_complete_for_scope`, `missing_data`.
- **Разрешённые доменные зависимости:** MatchingPolicy/optional classifier adapter; нет скрытого Graph.query.
- **Читаемое состояние:** Inline event, GraphSubgraph, BusinessSnapshot[].
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** candidate_scope соответствует profiles. search_complete_for_scope не заявляет охват рынка. paths состоят из рёбер переданного graph. none_found означает в данном scope и данных ничего не найдено. strict/balanced/broad — версии семантики policy, не универсальная гарантия сравнимого score; mock fixture закрепляет результат каждого режима.
- **Fixtures:** direct-exposure: confirmed path; indirect: potential; unrelated: matches=[] с complete scope; sparse: unknown и missing_data; truncated-graph: incomplete; invalid-path: output violation.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 18. Impact.assess

Оценить механизмы воздействия по одному событию, профилю, match, графу и evidence.

- **Владелец / тип:** `impact` / `compute`.
- **HTTP:** `POST /api/v1/impact/assess`; `operationId=Impact.assess`.
- **Вход:** `Impact_assessRequest` → `ImpactInput`: `event`, `profile`, `match`, `graph`, `evidence`, `rules`, `as_of`.
- **Выход:** `Impact_assessResponse` → `ImpactOutput`: `assessment`.
- **Разрешённые доменные зависимости:** Versioned ImpactRules/optional ModelPort. Нет обязательного business DB read.
- **Читаемое состояние:** Только EventRecord, BusinessSnapshot, Match, GraphSubgraph, EvidenceRecord[].
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Variant C/D — отдельные implementations одного operation contract, не отдельные endpoints. exposure, likelihood, materiality, analytical confidence и source reliability не взаимозаменяемы. Без объёмов/единиц/метода финансовая quantity=null. none_found не преобразуется автоматически в neutral/no risk. Противоречия и stale/partial graph отражаются в missing/limitations.
- **Fixtures:** radio-minimal: potential, materiality=unknown, no invented money; direct-confirmed; steel-buffer: mitigating assumption explicit; contradiction: low/unknown confidence; no-path: unknown; bad-company-match: SEMANTIC_VALIDATION.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 19. Recommendations.propose

Предложить информационные действия из разрешённого каталога, не выполнять их.

- **Владелец / тип:** `recommendations` / `compute`.
- **HTTP:** `POST /api/v1/recommendations/propose`; `operationId=Recommendations.propose`.
- **Вход:** `Recommendations_proposeRequest` → `RecommendationInput`: `assessment`, `audience`, `allowed_actions`, `constraints`.
- **Выход:** `Recommendations_proposeResponse` → `RecommendationOutput`: `recommendations`, `missing_data`.
- **Разрешённые доменные зависимости:** ActionPolicy/optional ModelPort.
- **Читаемое состояние:** Inline assessment, allowed_actions, audience, constraints.
- **Изменяемое состояние / эффекты:** Нет; банковские/уведомительные действия не вызываются.
- **Правила и характерные отказы:** Каждая рекомендация ссылается на assessment/evidence и допускается audience. requires_approval не ниже каталога. При unknown воздействии допустим запрос сведений/проверка, а не безусловная финансовая операция. Empty allowed_actions → пустой список. Explanation text не выдаётся за execution trace.
- **Fixtures:** potential-radio: проверить закупки; bank-manager: разрешённое informational action; empty-actions: []; low-evidence: conditional suggestion; disallowed-action: output violation; approval-downgrade: output violation.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 20. Evidence.register

Создать проверяемую ссылку на immutable первоисточник и anchor.

- **Владелец / тип:** `evidence` / `command`.
- **HTTP:** `POST /api/v1/evidence/register`; `operationId=Evidence.register`.
- **Вход:** `Evidence_registerRequest` → `RegisterEvidenceInput`: `evidence_id`, `expected_revision`, `source_ref`, `locator`.
- **Выход:** `Evidence_registerResponse` → `RegisterEvidenceOutput`: `evidence`, `receipt`.
- **Разрешённые доменные зависимости:** EvidenceRepository/transaction, DocumentsReadPort/BusinessReadPort/RunsReadPort по SourceRef.owner, ArtifactStore.
- **Читаемое состояние:** Immutable версия источника и собственные evidence revisions/receipts.
- **Изменяемое состояние / эффекты:** evidence record, audit/receipt.
- **Правила и характерные отказы:** Разрешённые source owners Documents|Business|Runs. В v1 TextSpan адресует только Documents version.raw.text; у Business/Runs допускается WholeArtifact. WholeArtifact проверяет hash всего immutable источника. Span offsets code points raw text; quote_hash соответствует substring. verified_anchor относится к anchor, не к истинности факта. source_reliability=unassessed по умолчанию.
- **Fixtures:** raw-span: кириллица/emoji; whole-profile-version; whole-run-artifact; bad-hash; out-of-bounds; foreign-source; duplicate-key; version-conflict.
- **Replay:** Полный replay только в новом sandbox из before-state + записанных dependencies; сверить semantic after-state и receipt. Read-back из соседних owners также фиксируется.
- **Приёмка:** C01–C10; K01–K04; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 21. Evidence.read

Прочитать основания и, если разрешено, исходные артефакты либо receipt регистрации.

- **Владелец / тип:** `evidence` / `read`.
- **HTTP:** `POST /api/v1/evidence/read`; `operationId=Evidence.read`.
- **Вход:** `Evidence_readRequest` → `ReadEvidenceInput`: `query`.
- **Выход:** `Evidence_readResponse` → `ReadEvidenceOutput`: `EvidenceResult` | `ReceiptResult`.
- **Разрешённые доменные зависимости:** EvidenceRepository, owner source read ports, ArtifactStore, data policy.
- **Читаемое состояние:** Evidence records/receipts; referenced source artifacts только при include_source_text=true.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Missing refs перечислены. include_source_text не даёт новых прав. Недоступный source не превращает evidence в verified fact; ArtifactView показывает availability. Historical source immutable. Receipt branch допускает только Evidence.register.
- **Fixtures:** span-with-source; metadata-only; missing-ref; source-policy-denied: no content; tampered-source-hash: error; receipt; cross-sandbox.
- **Replay:** Повторное вычисление read response над recorded owner-read snapshot. Корректность SQL отдельно проверяется на восстановленной PostgreSQL.
- **Приёмка:** C01–C10; R01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 22. Runs.query

Получить фактически сохранённые запуски, trace, manifests и зависимости.

- **Владелец / тип:** `runs` / `read`.
- **HTTP:** `POST /api/v1/runs/query`; `operationId=Runs.query`.
- **Вход:** `Runs_queryRequest` → `QueryRunsInput`: `run_ids`, `operation_id`, `scenario_id`, `include_artifacts`, `limit`, `cursor`.
- **Выход:** `Runs_queryResponse` → `QueryRunsOutput`: `runs`, `next_cursor`.
- **Разрешённые доменные зависимости:** RunsRepository, ArtifactStore, scope/data policy.
- **Читаемое состояние:** runs/spans/dependencies/artifacts.
- **Изменяемое состояние / эффекты:** Нет доменных изменений; собственный query run записывается технически.
- **Правила и характерные отказы:** Список выбирается по snapshot начала query, исключает текущий query run, не вызывает рекурсивное Runs.query. include_artifacts=false сохраняет refs, content_json=null, availability=metadata_only. Неизвестные стоимость/версии/метрики не заменяются нулями. missing run_ids дают пустой/частичный список; failed run остаётся доступен. Artifact downloads ограничены 2MiB whole response; превышение → LIMIT_EXCEEDED с указанием запроса metadata-only.
- **Fixtures:** successful-run; failed-partial-trace; unknown-cost; metadata-only; dependency-error; missing-run; forbidden-run; self-query-no-recursion.
- **Replay:** Повторное вычисление read response над recorded owner-read snapshot. Корректность SQL отдельно проверяется на восстановленной PostgreSQL.
- **Приёмка:** C01–C10; R01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 23. Cases.save

Сохранить immutable версию воспроизводимого эксперимента на основе разрешённого run.

- **Владелец / тип:** `cases` / `command`.
- **HTTP:** `POST /api/v1/cases/save`; `operationId=Cases.save`.
- **Вход:** `Cases_saveRequest` → `SaveCaseInput`: `case_id`, `expected_revision`, `source_run_id`, `title`, `tags`.
- **Выход:** `Cases_saveResponse` → `SaveCaseOutput`: `case`, `receipt`.
- **Разрешённые доменные зависимости:** CasesRepository/transaction, RunsReadPort, ArtifactStore/data export policy.
- **Читаемое состояние:** Source run и его artifacts/cassettes; свои case revisions/receipts.
- **Изменяемое состояние / эффекты:** cases versions + pinned artifact references, audit/receipt.
- **Правила и характерные отказы:** Копируются manifest/refs/hashes, а не только красивый output. Source run не меняется. Неполная запись допускается как draft с replay unavailable/incomplete. approval всегда draft; expected answer не утверждается. Forbidden/secret/unknown data нельзя сохранить обходом server policy. Ссылки на сохраняемый case pin artifacts от обычного TTL.
- **Fixtures:** complete-run-save; incomplete-run-save: draft; update-case-revision; duplicate-key; stale-revision; source-other-tenant; unknown-data: DATA_POLICY_DENIED.
- **Replay:** Полный replay только в новом sandbox из before-state + записанных dependencies; сверить semantic after-state и receipt. Read-back из соседних owners также фиксируется.
- **Приёмка:** C01–C10; K01–K04; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 24. Cases.query

Открыть сохранённые версии экспериментов или receipt Cases.save.

- **Владелец / тип:** `cases` / `read`.
- **HTTP:** `POST /api/v1/cases/query`; `operationId=Cases.query`.
- **Вход:** `Cases_queryRequest` → `QueryCasesInput`: `query`.
- **Выход:** `Cases_queryResponse` → `QueryCasesOutput`: `CaseResult` | `ReceiptResult`.
- **Разрешённые доменные зависимости:** CasesRepository, ArtifactStore/data policy.
- **Читаемое состояние:** cases versions/pinned artifacts/receipts.
- **Изменяемое состояние / эффекты:** Нет.
- **Правила и характерные отказы:** Query не запускает алгоритм. revision при нескольких case_ids применяется к каждому ID; отсутствующие исключаются без выдуманного case. Tags — AND. Порядок case_id, revision; cursor scope/query-bound. include_artifacts=false возвращает metadata. Replay/live выбираются в отдельном вызове исходной публичной операции.
- **Fixtures:** latest-case; previous-revision; tag-filter; missing: cases=[]; metadata-only; corrupt-artifact: explicit unavailable/error; receipt; forbidden-case.
- **Replay:** Повторное вычисление read response над recorded owner-read snapshot. Корректность SQL отдельно проверяется на восстановленной PostgreSQL.
- **Приёмка:** C01–C10; R01; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.


## 25. Evaluation.evaluate

Оценить явно переданные результаты по выбранным ожиданиям, независимо от Runs БД.

- **Владелец / тип:** `evaluation` / `compute`.
- **HTTP:** `POST /api/v1/evaluation/evaluate`; `operationId=Evaluation.evaluate`.
- **Вход:** `Evaluation_evaluateRequest` → `EvaluationInput`: `results`, `expectations`, `require_same_input`, `method`.
- **Выход:** `Evaluation_evaluateResponse` → `EvaluationOutput`: `report`.
- **Разрешённые доменные зависимости:** EvaluationMethodRegistry, SchemaRegistry; safe Artifact decoder. Сеть не нужна.
- **Читаемое состояние:** Inline ObservedResult[], expectations[], pinned schema/method refs.
- **Изменяемое состояние / эффекты:** Нет; отчёт сохраняется как обычный run output.
- **Правила и характерные отказы:** require_same_input=true и разные input_hash → comparable=false с limitation; не фиктивный победитель. Exact сравнение исключает только approved ignored_paths. Property paths — RFC6901 JSON Pointer без исполнения expression. Facts method demo-facts-v1 сравнивает нормализованные statement IDs в typed output; F1=1 при двух пустых sets, 0 при одном пустом. Threshold и gold явно заданы expectations, не из saved output. Time/cost сравниваются только по recorded observed metrics при наличии.
- **Fixtures:** exact-equal; property-missing: passed=false; facts-partial: известный F1; different-input: comparable=false; no-expectations: report с limitation, не passed-quality; unavailable-artifact: explicit metric unknown.
- **Replay:** Полный replay с materialized inputs; внешние ModelPort responses записываются при их наличии. Вызов real с новым model/prompt — новый live эксперимент.
- **Приёмка:** C01–C10; доказать все инварианты этой карточки. Наличие output по правильной схеме недостаточно.

## Сквозные владельцы и вспомогательные возможности

Storage — ArtifactStore и owner repositories; Evidence — операции 20–21. Quality — Evaluation.evaluate плюс обязательные suites и readiness report. Observability/Run History — runtime recording и Runs.query. Playground — клиент общего каталога/исполнения/Cases/Evaluation, не новый бизнес-owner. Configuration/model gateway — typed infrastructure ports, не дополнительные public operations.

Scenario start/stop/resume, sandbox bootstrap, fixture approval и CI export — локальные CLI/CI tools с отдельными полномочиями. Они не расширяют утверждённый каталог HTTP execution операций. Банковское действие/доставка уведомления отсутствуют.
