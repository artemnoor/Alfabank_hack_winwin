# Record/replay и версионированные сценарии

## Запись запуска

RunManifest фиксирует operation/scenario ID+version, contract hash, implementation ID/version и code build hash, input artifact hashes, resolved config hash, model/provider revision если известна, prompt/taxonomy/ontology/rules refs, analytical time, RNG seed, environment runtime manifest и dependencies. Неизвестная provider revision остаётся unknown; точную восстановимость такой модели не обещают.

Машиночитаемые формы RunManifest, ModelIdentity, StateCapture, StepCheckpoint, DataPolicyDecision и DependencyRecord находятся в OpenAPI components. operation ID и input/output artifacts хранятся в enclosing RunRecord; dependency entries — в RunRecord.dependencies. Дублируемые версии/hashes в meta, record и manifest должны совпадать. Checkpoints — schema-validated технические artifacts, связанные с scenario_run_id и run_id, доступны через Runs.query artifacts; отдельная операция не нужна.

CassetteEntry: sequence, dependency_port, dependency_kind, request_schema/version, canonical_request_hash, safe request artifact, response_schema/version, response artifact или typed error, measured timing, original execution reference, classification. Auth/secret fields исключаются до записи. Их отсутствие не заменяется фиктивными credential values.

Hashing: UTF-8 JSON, отсортированные object keys, без whitespace, arrays сохраняют порядок, Unicode не нормализуется неявно, NaN/Infinity запрещены, decimal quantities представлены строками. Все алгоритмически значимые поля включены; transport correlation IDs исключены по явному списку. Hash spec version `canonical-json-v1` хранится в manifest. Это локальный формат, не заявление о RFC 8785 conformance.

## Строгий replay

1. Проверить права, hashes, schemas, implementation availability и полноту recording.
2. Создать новый run с replay_of; исходный manifest остаётся immutable.
3. Подставить recorded analytical clock, seed и разрешённые input artifacts.
4. Каждое обращение gateway сопоставить по dependency_port + sequence + canonical request hash + schema/config versions.
5. Подставить записанный response/error; trace показывает replay substitution и original reference.
6. При missing/mismatched entry вернуть REPLAY_MISS; network fallback запрещён. В конце проверить unexpected unused entries, если replay profile требует exact dependency sequence.

Replay не возвращает прежний operation output вместо исполнения алгоритма. Отдельный mock может вернуть записанный output, но descriptor kind=mock и такой запуск не доказывает проверку нового алгоритма.

Смена промпта/модели меняет request hash. Записанный ответ старого запроса не подставляется. Для сравнения нужен live run. Новая реализация может replay прежние зависимости только при совпадении фактических requests и объявленном compatible profile; это новый эксперимент, не старое выполнение.

Новые run IDs, actual telemetry timestamps, receipt.committed_at и observed duration не обязаны совпадать. Для command replay явно исключаются enclosing meta, receipt.original_run_id, receipt.audit_id и receipt.committed_at; business/event IDs, revisions, hashes и recorded_at утверждений сохраняются. Последнее обеспечивается recorded DomainClockPort, не текущими часами машины. ComparisonSpec задаётся ExactExpectation.ignored_paths либо property/facts expectations; это не отдельный неописанный DTO. Byte equality применяется только к явно перечисленным deterministic payload fields.

## Reads и команды

Для replay вычисления owner reads заменяются записанными immutable bundles. Тест PostgreSQL read adapter отдельно выполняется на seed state — replay не доказывает корректность SQL.

Команда replay запускается в новом sandbox с восстановленным before-state и idempotency receipts. Manifest содержит before-state hash, command hash и expected semantic after-state hash. Existing receipt в production не используется для теста команды. Domain state comparison исключает новые run IDs, но сохраняет identity/version semantics. Восстановление разрешено только локальному CLI/CI с sandbox privileges.

## Сценарий первого каркаса

`document-business-impact@1.0.0`, typed inputs: RawMaterial + BusinessInput; optional fetch source. Шаги:

1. Sources.fetch, если выбран source; иначе inline document.
2. Documents.prepare → Documents.register → Documents.read.
3. Evidence.register для используемых исходных spans.
4. Understanding.classify; optional hints передаются explicit binding.
5. Understanding.extract.
6. Events.read → Events.propose_resolution → Events.apply → Events.read.
7. Business.propose_profile → Business.apply → Business.read.
8. Business.propose_questions, при наличии полезных неизвестных; ответ не обязателен.
9. Graph.build → Graph.publish → Graph.query.
10. Matching.match → Impact.assess → Recommendations.propose.
11. Evidence.read для итоговых оснований; Runs.query для просмотра.

Сценарий не добавляет новый public operation. CLI вызывает ExecutionService. HTTP-only integration runner проходит те же 25 endpoints. Передача данных между шагами — typed functions с version/hash, unit tests и provenance preservation. Binding не вызывает LLM и не добавляет факты. Извлечение evidence spans и их регистрация связываются явно: spans после extraction могут потребовать отдельного Evidence.register шага до Events.apply.

Mock сценарий использует согласованный dataset `radio-export-v1`: две статьи/два упоминания, одна компания, подтверждённая продажа радиодеталей, неизвестное происхождение закупок, potential exposure и unknown materiality. Второй dataset `steel-buffer-v1` проверяет смягчающее условие запасов. Это синтетика, не факт о реальных компаниях.

## Остановка и возобновление

CLI поддерживает stop_after=<step_id>; checkpoint записывается после подтверждённого окончания шага. StepCheckpoint содержит input/output hashes, bindings version, implementation/config, command receipt при наличии, source versions и scenario version.

Resume разрешён только для той же scenario version при совпадении manifest и всех требуемых hashes. Для изменяемого состояния проверяется допустимость сохранённой версии: последующие commands требуют актуальный expected revision. Если её нет, вернуть RESUME_CONFLICT; пользователь создаёт новый run/предложение. Выполненная команда не повторяется без проверки её receipt. Уже committed, но не записанный checkpoint восстанавливается через owner receipt query. Автоматического угадывания и rollback всех шагов нет.

Technical failed dependency останавливает dependent steps; unknown/partial идёт дальше только по explicit scenario predicate. Retries <=3, all attempts traced. stop_after сохраняет данные для Cases.save; checkpoint не превращается автоматически в approved regression fixture.

## Приёмка

- Полный mock и mixed runs проходят одну программу; mixed использует real.prepare.
- Остановка после каждого шага доступна; промежуточный payload загружается в Playground.
- Resume не дублирует commands; изменённый input/config/state даёт конфликт.
- Missing cassette, changed prompt, extra network call, modified artifact дают явный отказ.
- Frozen analytical clock, DomainClockPort и RNG проверяются; hidden external network запрещён OS/container-level egress policy в CI replay job. Единственное сетевое исключение для stateful tests — явно разрешённая изолированная Testing PostgreSQL; model/source egress закрыт. Запись команды в восстановленную локальную БД не подменяет внешнюю зависимость.
