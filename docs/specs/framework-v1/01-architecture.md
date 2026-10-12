# Архитектура и правила разработки

## Уточнения для реализации

Зафиксированы как минимальные технические уточнения спецификации: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + psycopg, Alembic; PostgreSQL 16; React + TypeScript + Vite; pytest, HTTPX, jsonschema, Playwright; uv для Python, npm с package-lock для frontend. Это выбор каркаса, не выбор моделей или аналитических алгоритмов.

При задаче T00 фиксируются точные patch-версии Python/Node, uv и npm, все зависимости и digest PostgreSQL-образа. Node — ветка 22. Если выбранная ветка несовместима с разрешаемым набором пакетов, изменение runtime оформляется ADR до начала функциональных задач. Воспроизводимость подтверждается lock-файлами и CI, а не словами «установите latest».

Docker Compose запускает только PostgreSQL. API и UI работают локально. Нативная PostgreSQL допускается при прохождении того же smoke-теста. Основной проверяемый путь — Windows PowerShell; CI повторяет его на Windows, основные тесты также на Linux.

## Целевое дерево репозитория

Это планируемые файлы; в текущей задаче создаётся только спецификация.

```text
apps/api/src/alfalab/
  bootstrap/                 # composition root, реестр, серверные профили
  transport/http/            # 25 тонких handlers + системные GET
  execution/                 # invoke, policy, context, dependency recording
  modules/
    sources/
    documents/
    understanding/
    events/
    business/
    graph/
    matching/
    impact/
    recommendations/
    evidence/
    runs/
    cases/
    evaluation/
  scenarios/                 # версионированные программы и typed bindings
apps/playground/src/         # общий JSON workbench
packages/contracts/src/alfalab_contracts/
  common/                    # envelope, refs, provenance, ошибки
  <owner>/v1/                # входы/выходы, экспорт публичного интерфейса
tests/
  contracts/                 # параметризуются по реестру
  architecture/
  integration/
  replay/
  security/
  e2e/
fixtures/approved/           # manifest + маленькие синтетические данные
fixtures/cassettes/          # только разрешённые записи
infra/                      # compose PostgreSQL, bootstrap DB, Alembic
config/                     # безопасные примеры профилей; без секретов
tools/                      # локальный CLI, export, readiness report
docs/                       # спецификация, ADR, локальный runbook
.local/                     # игнорируется Git: секреты, артефакты, sandboxes
```

Каждый модуль содержит `public.py`/публичные Protocol, `operations/`, `implementations/mock/`, `implementations/real/` при наличии, `storage/` при владении состоянием. Один модуль не равен одному классу. Один файл операции не обязан содержать алгоритм и HTTP handler.

## Разрешённые зависимости

| Слой | Разрешено | Проверка |
|---|---|---|
| contracts | stdlib, Pydantic; common и явно указанные DTO другого владельца | Нет FastAPI, ORM, HTTPX, implementation imports |
| operation core | собственные contracts, Protocol, common types | Нет прямого создания клиентов/engine, getenv, wall clock |
| owner storage | собственные таблицы и типизированные read ports | SQL-доступ ограничен DB-ролью владельца |
| external adapter | свой Protocol, HTTPX/SDK | Вызывается только через dependency gateway |
| transport | contracts + ExecutionService | Нет импорта алгоритмов и SQL |
| scenarios | публичные операции, contracts, typed bindings, execution | Нет внутренностей модулей, SQL, самостоятельных AI-вызовов |
| bootstrap | concrete implementations, adapters, execution | Единственное место сборки concrete dependencies |
| Playground | сгенерированные TS-типы, HTTP client | Нет LLM SDK, секретов, DB clients |

AST-проверка импортов использует явную allowlist. Запреты дополнительно проверяются SQL permissions и сетевой изоляцией replay; статический анализ сам по себе не является Python sandbox.

Каждый владелец БД имеет отдельную DB-роль и schema. Общая PostgreSQL не предоставляет модулям взаимный write-доступ. Cross-owner ссылки проверяются через публичные read ports; SQL JOIN к чужой schema запрещён. Bootstrap/migration role не используется процессом API.

## Владельцы

| Владелец | Авторитетное состояние | Кто может менять |
|---|---|---|
| Documents | исходные записи, версии подготовленного текста, координаты нормализации | Documents.register |
| Events | event IDs, event assertions, revisions, merge/split lineage | Events.apply |
| Business | профиль, assertions/relations, answers, question preferences | Business.apply |
| Evidence | проверенные anchors и metadata ссылок на источники | Evidence.register |
| Graph | опубликованные projection manifests, nodes/edges | Graph.publish |
| Runs | run/step records, dependencies, trace, immutable result artifacts | Execution через внутренний writer; HTTP Runs.query только читает |
| Cases | черновики экспериментов и их версии | Cases.save |
| Impact / Recommendations | смысл схем и инвариантов результатов | соответствующая операция создаёт новый run artifact; физически хранит Runs |

Sources и Understanding не владеют каноническими документами/событиями. Evaluation возвращает отчёт как run artifact. Утверждённые regression fixtures принадлежат репозиторию, изменения проходят code review.

Профиль и событие владеют своими атомарными утверждениями. Общая форма Statement не создаёт отдельный универсальный Claim Service. Предметные predicates в первом сценарии версионируемы и предварительны.

## Добавление реализации существующей операции

1. Создать implementation в собственном модуле; реализовать public Protocol без изменения соседей.
2. Объявить descriptor: operation_id, implementation_id/version, kind, capabilities, parameters schema, dependency ports, поддерживаемый contract version, replay profile.
3. Добавить сборку в bootstrap; передать зависимости конструктору. Импорты concrete implementation в transport запрещены.
4. Добавить implementation-specific fixtures и запустить общий contract suite.
5. Подключить только разрешённые environments. Production allowlist не меняется автоматически.
6. Проверить metadata, Playground, replay и сохранение provenance. Обновить readiness manifest.

Параметры новой реализации имеют отдельную строгую схему. Их нельзя принимать как невалидируемый dict. Если операция сохраняет семантику, новая реализация не требует изменения payload DTO. Смена семантики проходит contract review.

## Параллельная работа

После T02 контракты и common interfaces заморожены для текущей версии. Module owners могут реализовывать операции по утверждённым fixtures до готовности соседей. Изменение shared contracts: отдельный PR, owner и затронутые consumers, compatibility report. Shared runtime/HTTP handlers не редактируются каждой командой: модуль поставляет descriptor и implementation, routes строятся из реестра с конкретными request/response models.

Интеграция запрещена, если implementation обходит executor, скрывает dependency, нарушает schema или меняет чужое состояние. Показатели качества могут быть низкими у экспериментального алгоритма; такая реализация явно не Algorithm Ready.
