# Хранение, Evidence, provenance и граф

## Физическая модель

Одна PostgreSQL на окружение; schemas `documents`, `events`, `business`, `evidence`, `graph`, `runs`, `cases`. У каждой schema owner DB-role с SELECT/INSERT/UPDATE только внутри неё. Migration role отдельно. Development и Testing используют разные credentials/DB; Production profile отсутствует в локальном запуске.

Каждая запись содержит tenant_id, sandbox_id. Все запросы фильтруются по обоим значениям из trusted context. Cross-tenant refs отклоняются до чтения содержимого. В первый этап не вводится внешний object storage: immutable artifacts лежат в .local/artifacts/<environment>/<tenant>/<sandbox>/<sha256>.json|txt. Клиент не передаёт filesystem path. Запись файла atomic temp+rename; verified hash до регистрации ссылки в БД. Неиспользованный файл после rollback может удалить локальный maintenance CLI.

## Таблицы

| Schema/table | Ключ и основные поля | Инвариант |
|---|---|---|
| documents.documents | scope + document_id, current_revision | документ и публикация имеют стабильный ID |
| documents.versions | document_id + revision, kind raw/prepared, content_hash, artifact_ref, parent_version, metadata_json, recorded_at | immutable; prepared связан с raw |
| events.aggregates | event_id, revision, lifecycle active/merged/split, lineage_refs | merge не уничтожает старые IDs |
| events.versions | event_id + revision, EventSnapshot, valid_time, recorded_at | предыдущие версии читаемы |
| events.statements | statement_id + revision, Statement, event_id | утверждения имеют источник/unknown |
| business.aggregates | company_id, revision | scoped optimistic concurrency |
| business.versions | company_id + revision, BusinessSnapshot | immutable snapshots |
| business.statements | statement_id + revision, Statement, company_id | conflicts сохраняются |
| business.answers | question_id + answer_revision, answer status/value/source | skipped/declined не создают отрицательного факта |
| evidence.records | evidence_id + revision, SourceRef, anchor, source_hash, locator_status | `EvidenceRecord.ref.owner=Evidence`; source ref разрешён и anchor относится к immutable версии источника |
| graph.projections | graph_id + revision, ontology/rules/input manifest, graph artifact refs | graph immutable, replace by new version |
| graph.nodes / edges | projection revision + node/edge ID, typed JSON attributes, statement/evidence refs | references замкнуты внутри snapshot |
| runs.runs | run_id, parent/scenario IDs, status, input/output refs, versions, policy decisions, trace_status | фактическая история, не LLM narrative |
| runs.spans | run_id + sequence, parent_span_id, operation/dependency IDs, timing, safe status | sequence отражает наблюдавшиеся события |
| runs.dependencies | run_id + dependency sequence, request/response artifact refs, hashes, recording metadata | нет auth headers/secrets |
| runs.artifacts | hash + scope, media_type, schema_id/version, size, classification, relative storage key | hash проверяется при загрузке |
| cases.cases / versions | case_id + revision, CaseManifest, input/output/cassette refs, labels | сохранённый output не утверждённый gold |

JSONB разрешён только с конкретным schema_id/version и валидацией при записи/чтении. Техническая гибкость хранения не отменяет строгую форму payload. Generic unvalidated metadata dict в публичных моделях отсутствует.

Каждый командный owner дополнительно содержит `command_receipts` и `audit_entries`. Внешние ключи к чужим schemas не нужны: версии и hashes проверяются публичными read ports. Внутри owner schema FK обязательны там, где возможны.

Типы и ограничения общего хранилища: IDs — TEXT с ограничениями Identifier, revision — BIGINT>=0 (сохранённые версии >=1), timestamp — TIMESTAMPTZ UTC, semantic decimal — NUMERIC либо исходная DecimalString в валидированном JSONB, hashes — TEXT с Hash pattern. Scope fields NOT NULL входят во все PK/unique indexes и lookup predicates. JSONB columns NOT NULL кроме явно nullable artifacts. Индекс исторического чтения: scope + aggregate_id + recorded_at + revision; list indexes повторяют declared sort/cursor.

`command_receipts`: scope, operation_id, contract_major, idempotency_key — UNIQUE; command_hash, original_run_id, audit_id, committed_at, typed receipt_json и неизменяемый response_payload_json/schema/version/hash — NOT NULL после commit. При duplicate возвращается прежний domain payload/receipt, технический meta отражает новый invoke. `audit_entries`: scope + audit_id PK, actor_id, operation_id, command_hash, before_refs/after_refs, committed_at. Несохранённое in-flight состояние не считается committed receipt. Файл с результатом может быть подготовлен до transaction; receipt хранит его проверенный ref и semantic payload, поэтому отказ Runs не лишает владельца возможности вернуть результат.

## Протокол команды

Receipt scope: tenant + sandbox + operation_id + contract_major + idempotency_key. `command_hash` вычисляется по canonical payload, actor permissions scope и semantic parameters; request_id/run_id/timeout/retry attempt не включаются. Expected revisions входят в hash. Implementation/config, влияющие на изменение, входят в hash.

Одна PostgreSQL transaction владельца:

1. Создать/заблокировать receipt key; при concurrent insert ждать завершения конкурирующей transaction.
2. Если receipt существует: сравнить command_hash; вернуть сохранённый результат либо IDEMPOTENCY_CONFLICT.
3. Заблокировать изменяемые aggregates в сортированном порядке; отсутствие объекта имеет revision 0.
4. Проверить expected revisions, ссылки, права и предметные инварианты всего набора изменений.
5. Построить и валидировать domain output payload; записать новые immutable versions, current revisions, domain audit и окончательный receipt с этим payload. Невалидный output до commit откатывает команду.
6. Commit. До commit промежуточный receipt не виден как успешно применённый.

Ошибки до commit откатывают все доменные изменения данной команды. Нет общей transaction между Events, Business, Graph и Runs. Техническая история может быть partial, domain audit и receipt фиксируются вместе с изменением.

Авторитетный receipt доступен через существующее owner-read operation с query kind=receipt. Это типизированная ветка чтения внутри Documents.read/Events.read/Business.read/Graph.query/Evidence.read/Cases.query; новый endpoint не добавляется. Request содержит исходный operation ID и key, полномочия проверяются повторно.

## Evidence

SourceRef: owner Documents|Business|Runs, object ID, revision, hash. `EvidenceRecord.ref` принадлежит Evidence; `EvidenceRecord.source_ref` и `Evidence.register.source_ref` указывают только на Documents, Business или Runs. Evidence.register получает SourceRef и locator, читает источник через разрешённый read port и проверяет его существование, scope, immutable hash и anchor. TextSpan использует Unicode code point offsets [start,end), исходную строку до нормализации и quote_hash. Для подготовленного текста обязателен parent raw ref; восстановимость mapping определяется Documents.prepare.

Первый этап поддерживает text spans и whole-artifact anchors. PDF pages/coordinates остаются future locator variant: чтение PDF не требуется каркасу. `verified_anchor` означает целостность ссылки на источник, но не доказывает истинность утверждения. Для `Statement.epistemic_status=confirmed` DTO требует одну или более ссылок с owner Evidence; существование ссылки и целостность hash/anchor проверяет Evidence owner. После этого соответствующая owner policy должна явно разрешить подтверждение. Без такой policy Events/Business не сохраняют `confirmed`, и статус остаётся `unknown`/unverified. Универсальный порог reliability не вводится; policy может учитывать конкретные источники и обстоятельства. Клиентская метка `confirmed`, verified anchor или `source_reliability` отдельно не заменяют разрешение policy.

В v1 TextSpan имеет ровно один адресуемый текст: Documents version.raw.text. Для Business/Runs допускается WholeArtifact; неоднозначный поиск строки внутри произвольного JSON запрещён. GraphNode/GraphEdge и derived provenance используют StatementRef с aggregate revision и точным statement ID/revision/hash.

Source reliability, epistemic status и analytic likelihood — отдельные типы. User-declared не равно подтверждённому независимым источником. Нет автоматического калиброванного probability из raw model score.

## Provenance

Каждый значимый Statement и GraphEdge содержит Provenance: origin kind, source refs, input statement refs, producer run/ref, epistemic status, evidence refs. Derived provenance требует input refs и versioned derivation method. ExecutionMeta дополнительно содержит lineage summary: synthetic source, mock derivation, unknown origin. Summary вычисляется объединением зависимостей, а не принимается на доверии от request.

Mock output содержит mock_derivation даже если копирует реальные входные assertions. Источник скопированного факта сохраняется; синтетическое выполнение не переименовывает сам первоисточник. Replay — способ исполнения, а не новый тип первичного источника.

## Граф и актуальность

ProjectionManifest содержит ontology ref/hash, rules ref/hash, input knowledge slices, valid_as_of, known_as_of, build implementation/config. Slice: owner, partition_id, revision, selection_key. На первом этапе используются явно объявленные scoped partitions: company profile, event set, shared reference dataset. Автоматического анализа произвольных SQL-зависимостей нет.

Graph.query принимает required_slices и freshness_policy=current_required|allow_stale|historical. Сервер может ужесточить запрос. Сравнение учитывает новые сведения внутри selection_key, а не только IDs уже включённых statements. Изменение другого company partition не инвалидирует snapshot; изменение shared ontology/rules может затронуть все зависимые snapshots.

GraphSubgraph возвращает manifest, freshness current|stale|historical|unknown, knowledge_completeness complete_for_declared_slice|partial|unknown, traversal_truncated, missing_slices. Это три разные оси. Historical использует valid_as_of и known_as_of; позднее записанные сведения исключаются.

Graph.build создаёт candidate; Graph.publish валидирует manifest, expected revision и references, сохраняет новую версию. Исходные Statements не изменяются. Переизвлечение LLM создаёт новые предложения, а не перезаписывает историю.

## Приёмка

Два tenants и два sandboxes проходят изоляцию на reads/writes/refs. Commands тестируются на concurrent duplicate, conflicting key, version conflict и crash points. Исторический as_of не получает поздние знания. Изменение неиспользованной компании не делает граф stale; новая релевантная связь делает. Altered blob hash блокирует загрузку/replay.
