# Общий механизм исполнения и Dependency Injection

## Публичный внутренний интерфейс

ExecutionService.invoke принимает operation descriptor, типизированный request и trusted principal/context; возвращает типизированный response. HTTP и CLI используют этот интерфейс. Реализация операции получает payload и OperationContext, а не FastAPI Request.

OperationContext предоставляет: principal, tenant_id, sandbox_id, execution environment, run_id, analytical clock, RNG, artifact/evidence read ports, dependency gateway, trace recorder, cancellation flag, limits. Все источники времени/случайности алгоритма идут через context. Реальное время телеметрии хранится отдельно от analytical clock.

Время появления знания в системе не задаётся клиентским analytical_time. Owner commands получают recorded_at через серверный DomainClockPort; его значение записывается как clock dependency и подставляется при replay. Предложенный Statement.validity.recorded_at является provisional до apply; при сохранении owner устанавливает авторитетное время записи. Для импорта исторического before-state привилегированным fixture CLI сохраняется исходное recorded_at. committed_at receipt и телеметрия показывают реальное время текущего запуска и исключаются из semantic replay equality по явному списку.

## Порядок

1. Проверить размер HTTP body до подробного разбора; authenticate principal из серверного credential store.
2. Проверить sandbox/tenant и разрешённую operation. Клиент не задаёт environment, DSN, module path или произвольный provider URL.
3. Разобрать operation-specific request и version; errors не включают отвергнутое содержимое.
4. Разрешить implementation по server registry, validate parameters и capabilities. Отсутствующий real возвращает IMPLEMENTATION_UNAVAILABLE.
5. Определить trusted data classification; применить независимые processing/egress/record/export policies. До этого raw payload не логируется.
6. Зафиксировать input/config hashes, versions, RNG seed, analytical time, dependency manifest. Нельзя повысить происхождение клиентским полем.
7. Создать run record. Если обязательная запись недоступна, отклонить команду до доменных эффектов. Для вычисления также вернуть HISTORY_UNAVAILABLE до исполнения, если выбран full recording.
8. Вызвать implementation. Все внешние операции проходят gateway. Подготовленные inline inputs не разрешают скрыто читать рабочую бизнес-БД.
9. Валидировать выход и semantic invariants. Присоединить фактический execution provenance и lineage.
10. Сохранить разрешённый результат, trace и зависимости. Завершить run; вернуть response.

Если policy допускает локальную ephemeral processing неизвестных данных, шаги 6–10 сохраняют только безопасные metadata. UI показывает recording=metadata_only и replay=unavailable. Закрытые данные не являются поддерживаемым режимом первого каркаса.

## Ошибки и статусы

HTTP 200: success, partial, abstained. Пустой список/unknown — допустимый содержательный результат. HTTP 401/403: доступ; 409: версия/idempotency conflict; 422: schema/semantic validation; 429: лимиты; 502: dependency failure; 504: timeout; 500: нарушение выходного контракта/внутренний сбой; 503: implementation/history unavailable. JSON errors имеют общий безопасный формат.

ErrorInfo: code, category, retryable, safe_message, field_paths, dependency_id nullable, outcome=not_applied|applied|unknown|not_applicable. Нет provider body, input echo, stack locals, auth headers. Trace хранит безопасный stack fingerprint и component ID, подробности только при разрешённой классификации.

Если команда зафиксировалась, а финальная запись Runs не удалась, receipt владельца остаётся авторитетным. Ответ по возможности содержит committed receipt и trace_status=partial. Потеря ответа не означает rollback. Последующий повтор того же command key возвращает исходный receipt. Исходный run может остаться outcome=unknown; такая неопределённость видна, а не исправляется выдуманным trace.

## DI и registry

Composition root строит immutable registry при старте. Descriptor содержит ровно одну operation schema pair и список implementation descriptors. Startup проверяет уникальность IDs, ровно 25 operation IDs, schema hashes, параметры, разрешённые dependency ports, наличие mock, route count.

Встроенные реализации: `mock.baseline@1.0.0` для всех операций; `mock.alternative@1.0.0` для вычислений, где нужен UI comparison; `real.prepare@1.0.0` для Documents.prepare. Команды/чтения mocks используют owner repositories и test state; это stateful fake, а не константный ответ. Остальные real отсутствуют явно. Infrastructure execution/history/policy/recording работают фактически, их нельзя подменить вымышленной telemetry.

remote adapter реализует тот же Protocol и вызывает удалённую operation schema pair. Он передаёт ограниченный подписанный контекст, timeout и idempotency key; remote IDs/latency отображаются как реальные dependency spans. Доставка адаптера в первый каркас не обязательна; conformance transport test выполняется на локальном тестовом сервере.

## Минимальные лимиты

Начальные безопасные defaults, не SLA: HTTP body 2 MiB; документ 200000 Unicode code points; page size <=100; snapshot <=10000 statements; graph <=10000 nodes/20000 edges; depth <=5; scenarios <=50 steps; timeout operation 30 s, source fetch 15 s; retry attempts <=3 с backoff 0.1/0.5/1 s и контролируемым clock в тестах. Профиль может ужесточать значения. Увеличение требует resource test.

Mock timeout имитируется управляемым clock; тест не ждёт реальный timeout. Provider/token/cost limits задаются только при добавлении real adapter. Неизвестная цена не приравнивается к нулю.

## Повторы и отмена

Validation, access, policy и output-contract errors не retryable. Retries внешних reads разрешены descriptor; каждый attempt записывается. Команду повторяют только с тем же key/hash после проверки receipt. Изменение input/config — новая логическая команда.

Сценарий останавливается между шагами по stop_after либо cancellation. Внешний вызов уже мог завершиться после отмены: outcome фиксируется фактически или unknown. Общей транзакции/компенсации между владельцами нет.

## Приёмка

- HTTP, CLI и сценарий дают одинаковый semantic result на одном deterministic input/config.
- Попытка real→mock fallback отклоняется; descriptor фактической реализации совпадает с trace.
- Failure injection до/после command commit подтверждает receipt semantics.
- Запрещённые зависимости обнаруживаются; payload с неизвестными полями/реализацией не выполняется.
- Метрики: duration_ms measured, tokens nullable, cost nullable + measured|estimated|unknown; trace complete|partial|metadata_only.
