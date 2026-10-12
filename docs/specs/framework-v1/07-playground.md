# Минимальный Developer Playground

## Реализация

Один React/TypeScript/Vite UI, один HTTP client к FastAPI. JSON editor — textarea с форматированием, JSON parse error и schema validation; обязательства Monaco/custom forms нет. UI получает registry из /system/catalog, схемы из /openapi.json. Типы генерируются из schemas; UI не содержит копию business DTO и не вызывает модели напрямую.

Первый вертикальный срез UI поддерживает Documents.prepare; после подключения registry тот же workbench обслуживает все 25 операций. Различие operation kind отражается в предупреждениях/controls, не в отдельных реализациях алгоритмов.

## Экран операции

1. Search/select: operation ID, owner, description, type, contract version.
2. Implementation selector: доступные ID/version, unavailable с причиной, kind real/mock. Parameter editor валидируется по implementation-specific schema.
3. Input editor: JSON payload, fixture selector, data declaration и independent recording/live/replay controls.
4. Trusted environment/sandbox показаны сервером. Нельзя вводить DSN/provider URL или переключиться на production клиентским полем.
5. Run: validate, invoke конкретного endpoint, show run ID и executed implementation.
6. Tabs: structured output, safe errors, trace tree, dependencies, evidence, measurements, provenance. Missing trace/metrics/cost явно unknown/partial.
7. History/Cases: search, open, save draft, load to editor. Отредактированный historical input создаёт новый эксперимент.
8. Replay: source run, completeness/compatibility check; strict mode обязателен. Unavailable показывает причину до запуска, сервер повторно проверяет.
9. Compare: фиксированный input snapshot, две implementation selections/config; два обычных invoke; Evaluation.evaluate с exact/property/facts ожиданиями. Разные inputs дают noncomparable, если требуется одинаковый input.
10. Send to next: JSON Pointer выбранной части → editor следующей операции; validate; пользователь видит любое преобразование. Сохранённый binding имеет version/hash. Скрытого LLM mapping нет.

Результаты команд содержат receipt. UI отличает committed, not_applied и unknown. Save/apply buttons отключены без полномочий. Результат mock или с synthetic/mock lineage обозначен рядом с output, в истории, сравнении и экспорте.

## Инфраструктурные интерфейсы

История: Runs.query; drafts: Cases.save/query; evidence: Evidence.read; сравнение: Evaluation.evaluate. Каталог содержит безопасные configuration schemas и доступность, не credentials. Browser использует token, введённый локально; production credentials не существуют в default profile. Token хранится в памяти вкладки, не экспортируется в case/localStorage/trace.

CLI export создаёт draft bundle; Git inclusion отдельно review. UI может подготовить downloadable разрешённый bundle через уже загруженные artifacts только при server-derived ExecutionMeta.data_policy.export_allowed=true; отдельный export service не требуется. Policy/secret scan повторяются при CLI экспорте и в CI. Права на просмотр уже полученного текста не являются техническим запретом его ручного копирования; такую гарантию каркас не заявляет.

## Приёмка

- Для всех 25 descriptors E2E открывает operation, загружает fixture, вызывает endpoint, видит payload/run ID.
- Command fixture сначала seed state, затем команда и read подтверждают изменение.
- UI comparison работает на mock.baseline/mock.alternative и real.prepare/mock для Documents.prepare.
- Тесты history/save/load/replay/transfer используют общие controls и настоящие infrastructure endpoints.
- Нет необъявленных AI/network requests из browser. Неизвестная стоимость не выводится как 0; partial trace не выглядит complete.
- Keyboard access, label каждого control, focus на ошибку, status region и читаемые предупреждения проверяются. Специальный графический viewer не входит в Framework Ready.
