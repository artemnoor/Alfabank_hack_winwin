# Контракты, HTTP и Pydantic

## Wire format

Нормативная форма всех моделей — contracts/openapi.json. Именованные схемы включают 25 request/response pairs, payload DTO, общие типы и системные metadata. Их проверенное количество приведено в validation-report.json. Все object schemas закрыты additionalProperties=false. Nullable и отсутствующее поле различаются: поля текущего wire format обязательны, nullable передаётся явным null. Arrays при отсутствии данных передаются пустыми, а не null.

Выполнение: POST /api/v1/<owner>/<operation>. Чтения тоже используют POST, чтобы передавать строгий query DTO и execution options; доменный эффект определяется kind, а не HTTP method. Техническая запись run происходит и при чтении.

Request: contract_version, request_id, sandbox_id, implementation selection, execution options, data_declaration, payload; commands дополнительно idempotency_key. Tenant и environment выводятся из серверного principal/profile. Свойства tenant_id, environment, DSN, credentials и provider URL в request отсутствуют и отклоняются.

ImplementationSelection содержит id и version, не закрытый enum алгоритмов. parameters — строгий union зарегистрированных форм: MockParameters или пустая RealPrepareParameters в первом каркасе. Descriptor дополнительно проверяет соответствие конкретной формы выбранной реализации: baseline/alternative требуют MockParameters, real.prepare — пустую модель. Новая реализация с существующей формой параметров добавляется регистрацией без изменения operation DTO. Новая форма параметров проходит контролируемое расширение схем и consumer tests; произвольный dict не допускается. MockSelection/RealPrepareSelection — именованные ограниченные варианты для документации текущих registrations.

Response: meta + status success|partial|abstained + operation payload. ErrorResponse: nullable meta + ErrorInfo. Валидация ответа выполняется до признания операции успешной. Повторяемый request_id служит корреляции и не заменяет idempotency_key.

Live execution фиксирует analytical_time и random_seed. Replay execution ссылается на source_run_id и требует strict=true; analytical time/seed загружаются из manifest. Во всех случаях sandbox проверяется по principal. Replay command требует нового восстановленного sandbox.

## Pydantic

Каждая именованная object schema — отдельный BaseModel, ConfigDict(extra='forbid'). Числа и bool валидируются строго; '1' не становится int, 1 не становится bool. JSON timestamps представлены ограниченными RFC3339 UTC strings и преобразуются явно. Decimal quantities — DecimalString, преобразование в Decimal внутри алгоритма. float применяется только к raw scores/metric thresholds; NaN/Infinity запрещены.

Объединения TypedValue/EvidenceLocator/queries/expectations имеют discriminator kind; ExecutionOptions — mode. Nullable unions остаются различимыми от omission. Внутренние Protocol принимают соответствующий payload BaseModel и OperationContext; возвращают конкретный output BaseModel.

Декларации всех полей: contracts/pydantic-models.md. OpenAPI экспорт Pydantic сравнивается семантически: ссылки и порядок descriptions не важны; required, types, constraints, enum, discriminator и extra policy важны. Для schema diff входа и выхода проверяются оба направления отдельно.

## Межполевые validators

Это обязательные правила поверх JSON Schema; перечислены здесь, чтобы implementation не трактовала shape-valid data как заведомо корректные.

| Тип/область | Правило |
|---|---|
| RawMaterial | content_hash = SHA256 UTF-8 text; source URL — metadata, не инструкция на сетевой fetch |
| PreparedMaterial | raw_hash совпадает с исходным текстом; prepared_hash с material.text; span map ordered, bounds valid, покрывает подготовленные code points |
| Validity | valid_to > valid_from, если оба известны; unknown bounds не заменяются текущим временем |
| TimeSlice | valid_as_of и known_as_of независимы; recorded_at > known_as_of исключает утверждение из исторического среза |
| ObjectRef | owner соответствует типу; scope проверяется trusted context; hash проверяется при разрешении |
| StatementRef | aggregate_ref.owner только Events или Business; statement_id/revision/hash находятся внутри указанной immutable версии aggregate. Ссылка на весь профиль не подменяет ссылку на конкретное утверждение |
| Statement | derived/inferred имеет derivation method и input refs; подтверждение требует допустимого основания; conflicting claims сохраняются |
| Provenance | клиентский origin_verified не повышает trust; producer_run_id/source refs сверяются или помечаются unknown |
| QuestionAnswer | answered требует value; skipped/declined/unknown требуют null value; skip не создаёт false |
| TopicScore | score_method обязателен при raw_score; calibrated=true требует зарегистрированной calibration method |
| EventDecision | create без существующего target; attach/correct — один target; merge — >=2 targets и один successor; split — один target и >=2 successors; defer ничего не изменяет |
| EventChangeProposal | proposed ID уникальны; все mention/target refs разрешимы; merge/split lineage ациклична |
| ProfileChangeProposal | expected_revision относится к указанной компании; supersede refs принадлежат ей; противоречия не уничтожаются |
| GraphSnapshot | node/edge IDs уникальны; edge endpoints существуют; relation namespace/version соответствует ontology; derived edges с основаниями |
| ProjectionManifest | input slices уникальны по owner/partition/selection; hashes/versions доступны; builder соответствует исполнению |
| Match / Impact | event, company и graph manifests согласованы; paths состоят из существующих разрешённых рёбер; none_found не означает доказанное отсутствие риска |
| FinancialScenario | известные числа имеют input refs, units, method и assumptions; отсутствующие входы дают quantity=null/unknown |
| Recommendation | action принадлежит allowed_actions и audience; approval нельзя понизить; assessment_id совпадает |
| EvidenceRecord | source_hash и locator совпадают с immutable source; text span [start,end) корректен; reliability не повышается произвольным вводом |
| ArtifactView | available требует content_json; оно декодируется и валидируется по schema ref/hash; остальные states дают null |
| DependencyRecord | response либо error; оба одновременно запрещены; replay substitution имеет original reference |
| Measurement | unknown требует value=null; measured/estimated требует value и действительный method в trace |
| CaseRecord | draft; запись кейса не утверждает expected quality |
| EvaluationInput | comparable только при одинаковом declared input hash, если require_same_input=true; expectations утверждаются вне Cases.save |

ObjectRef.hash вычисляется по каноническому semantic record без собственного поля ref.hash, чтобы избежать self-reference. ArtifactRef.hash относится к фактически сохранённым bytes. Эти два hash domain не смешиваются.

StatementRef.hash относится к каноническому Statement. Разрешение StatementRef использует существующее Events.read/Business.read по aggregate ID/revision, затем выбирает и проверяет конкретное утверждение; новый endpoint и прямой SQL другого owner не нужны. Для unsaved proposals ссылки на ещё не сохранённые утверждения остаются внутри proposal по statement_id; их нельзя выдавать за durable StatementRef.

## Ошибки

| Code | HTTP | Retry | Эффект |
|---|---:|---|---|
| INVALID_INPUT / SEMANTIC_VALIDATION | 422 | нет | not_applied |
| UNAUTHENTICATED | 401 | нет | not_applied |
| ACCESS_DENIED / DATA_POLICY_DENIED | 403 | нет | not_applied |
| VERSION_CONFLICT / IDEMPOTENCY_CONFLICT | 409 | нет | not_applied |
| REPLAY_MISS / REPLAY_INCOMPATIBLE / RESUME_CONFLICT | 409 | нет | not_applied или not_applicable |
| IMPLEMENTATION_UNAVAILABLE / HISTORY_UNAVAILABLE | 503 | после устранения причины | not_applied |
| DEPENDENCY_FAILED | 502 | по descriptor | явный outcome |
| TIMEOUT | 504 | по безопасному протоколу | unknown для команды, если receipt ещё не проверен |
| OUTPUT_CONTRACT_VIOLATION | 500 | нет | фактический outcome, не автоматический rollback |
| REQUEST_TOO_LARGE | 413 | нет | not_applied |
| LIMIT_EXCEEDED | 429 | по лимиту | not_applied |

Empty read — HTTP 200 с null/missing IDs. Unauthorized ref не маскируется как успешный найденный объект; наружный safe_message не раскрывает содержимое другого tenant.

## Версии и совместимость

Контракты первого каркаса имеют version=1.0.0. Общий envelope version фиксируется в runtime manifest отдельно. Реализация/модель/промпт не изменяют contract version автоматически. Новая semantic guarantee/status/meaning требует contract change; incompatibility — новая major. Minor допустим только после consumer compatibility tests, включая strict unknown-fields consumers.

Первый этап поддерживает одну исполняемую версию операции. Исторические schemas архивируются, нужны для чтения сохранённых artifacts. UI показывает supported versions. Новый алгоритм на старом input — новый run. CI проверяет typed bindings и утверждённые сценарии; migration/adapter имеет отдельные version/hash.

## Системный API

- GET /system/catalog: 25 descriptors, фактические implementation availability, безопасные schemas/config parameters, разрешённые sandboxes, build/readiness hashes. Требует authentication.
- GET /openapi.json: OpenAPI snapshot текущего приложения, JSON schemas. GET /docs: Swagger. В testing/development доступны с разрешённым origin; production surface задаётся политикой.
- GET /health/live, /health/ready: техническая готовность процесса/БД, без содержимого конфигурации.

health может быть unauthenticated только с минимальным status; это явно задаётся OpenAPI security override. Новые configuration mutation endpoints в этап не входят.

## Первичные технические источники

OpenAPI 3.1 использует Schema Object на основе JSON Schema 2020-12: [официальная спецификация](https://spec.openapis.org/oas/v3.1.1.html). Формат 3.1.0 выбран для снимка каркаса, а не как заявление о последней версии стандарта.

Pydantic поддерживает strict validation и генерацию JSON Schema: [strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/), [JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/). Особенности strict JSON/datetime учтены явным строковым wire format.

FastAPI предоставляет DI и настройку operation IDs: [dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/), [OpenAPI configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/). Runtime/DI вне HTTP остаётся собственным небольшим composition root.

PostgreSQL предоставляет ON CONFLICT: [INSERT](https://www.postgresql.org/docs/16/sql-insert.html). Конкретный протокол receipt/locks в 05-storage.md является решением проекта и требует concurrency/failure tests.
