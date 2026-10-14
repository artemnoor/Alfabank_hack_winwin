# T10 remediation: независимый re-review

- Проверенная база: integration HEAD `80da94e12518d2aeb794e4dca9b3578c6b7d9763`, branch `codex/review-t10-final`.
- T10 remediation: `c864e17 fix(spike): address T10 review findings`; этот commit является предком проверенной базы.
- Исходные finding-и: `spike/T10/results/INDEPENDENT_REVIEW.md` (первичный reviewer не автор remediation).
- Dataset: shared v1.0.1, provisional, canonical hash `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
- Контрактная проверка: Business operation cards в `docs/specs/framework-v1/03-operations.md`, bitemporal правила `docs/specs/framework-v1/02-contracts.md:34`, StatementRef/supersede требования `02-contracts.md:43` и executable `packages/contracts/src/alfalab_contracts/semantics.py:391-406`.
- Implementation и tests не изменялись. Единственный создаваемый файл этого re-review — данный отчёт.

## Итог

Все четыре исходных finding-а проверены против remediation. Два HIGH и numeric-conflict MEDIUM воспроизведены как исправленные. Warehouse/service coverage теперь реализовано для ограниченных прямых текстовых упоминаний, вопросов, unknown и provenance; исходный coverage finding закрыт в scope прототипа. CRITICAL и HIGH открытых дефектов не обнаружено.

T10 **не готов к подключению к Framework как полноценный Business owner**. Остаются явно документированные integration ограничения: новые predicate codes требуют Business ontology approval, а текущий Statement DTO не выражает типизированную связь с warehouse/service provider. Отдельно `Business.read` не ищет receipts: переданы только snapshots, а ReceiptQuery всегда возвращает null. Это MEDIUM gap operation coverage, не регрессия алгоритмического remediation.

| Finding | Исходная severity | Статус re-review | Основание |
|---|---:|---|---|
| T10-R1: future `recorded_at` скрывает unknown | HIGH | CLOSED | `_valid_at` применяет valid-time и `recorded_at <= known_as_of`; targeted test/probe подтвердили, что поставщик не попадает в исторический срез и вопрос остаётся. |
| T10-R2: foreign/stale supersede ref закрывает local statement | HIGH | CLOSED | Apply сверяет точный aggregate ref, statement ID/revision/content hash и компанию до построения нового snapshot; foreign/stale/hash/absent/duplicate regressions отклонены, входной snapshot не мутируется. |
| T10-R3: противоречия между новыми утверждениями/ответами не фиксируются | MEDIUM | CLOSED в заявленном numeric scope | Пары new/new и new/old сопоставляются; probes на двух новых фактах и двух входных ответах дали по одной Contradiction. Произвольные текстовые/отношенческие конфликты по-прежнему вне заявленного алгоритма. |
| T10-R4: нет warehouse/service coverage | MEDIUM | CLOSED в offline scope; остаточное integration ограничение MEDIUM | Есть прямые `stores_at`/`uses_service`, отдельные unknown paths, вопросы и source/time provenance; sparse/negative cases не создают позитивной связи. Для typed entity edges и ontology registration нет согласованной формы. |
| T10-I1: Business.read receipt lookup | MEDIUM | OPEN / documented | `read_profile` получает только snapshots; для ReceiptQuery всегда возвращает `receipt=None`, без набора receipts или owner port. Карточка Business.read допускает ReceiptResult и fixture `receipt`. |

## Проверка remediation и доказательства

### T10-R1 — transaction-time срез

`spike/T10/src/t10_business.py:348-362` извлекает обе границы из `TimeSlice` и требует `recorded_at <= known_as_of` наряду с valid-time. `_current_claims`, `_fact_paths`, `_field_known` и reconciliation получают тот же `TimeSlice` (`:367-374,552-558,694-713`). Это соответствует `02-contracts.md:34`.

Проверка текущего regression `test_regression_future_recorded_statement_does_not_fill_profile_or_hide_question` (`spike/T10/tests/test_t10_business.py:599-636`) и независимый in-memory probe использовали утверждение поставщика с `valid_from=2026-01-01`, `recorded_at=2026-10-14T01:00Z` и историческим `known_as_of=2026-10-01`. Результат: `future leak: False active supplier IDs: set()`. Unknown `/dependencies/suppliers` остаётся; тест также проверяет, что предлагается `supplier_names`.

### T10-R2 — точная и атомарная supersede-проверка

`apply_profile` (`spike/T10/src/t10_business.py:879-897`) перед закрытием записи сверяет канонически полный `aggregate_ref` с текущим snapshot, отклоняет повтор refs, проверяет `(statement_id, revision)`, точный hash сериализованного statement и company ID. Старые объекты только копируются; закрытие выполняется после проверок. Regressions: чужой aggregate (`:639-660`) и параметризованные stale aggregate, wrong hash, missing statement, duplicate ref (`:662-689`). Все проверяют неизменность входного snapshot и незакрытый исходный statement.

Независимый probe с foreign aggregate и нулевым hash вывел `supersede aggregate_ref does not match the current snapshot`; snapshot сохранил исходную сериализацию (`unchanged: True`). Целевые regressions также подтвердили полный набор проверок ссылок.

### T10-R3 — конфликты между входящими сведениями

`_contradictions_for` включает сравнения всех пар новых statements (`spike/T10/src/t10_business.py:564-600,572-578`) и новых с предыдущими. `propose_profile` передаёт новые claims против видимых прежних утверждений (`:641`); `apply_profile` объединяет proposal statements и statements из incoming answers перед conflict detection (`:904-921`). Проверки тестов: два новых описания inventory (`test_regression_conflicts_between_two_statements_in_one_new_proposal`, `:691-699`) и новый ответ против текущего snapshot (`test_regression_apply_detects_incoming_answer_conflict_with_current_snapshot`, `:701-722`).

Дополнительно проверена пара входных ответов `inventory_days=8` и `inventory_days=12` в одном `Business.apply`: snapshot сохранил обе numeric statements и одну contradiction (`incoming answer pair conflict: 2 1`). Две фразы в одном новом proposal также дают `2` statements и `1` contradiction (`new proposal facts conflict: 2 1`). Это подтверждает исправление исходного missing new/new conflict. Ограничение к numeric scalar allowlist описано в `LIMITATIONS.md` и здесь не расширялось.

### T10-R4 — склады и внешние услуги

Добавлены event-relevant questions `warehouse` и `service_dependency` (таблица `FieldQuestion` в `spike/T10/src/t10_business.py:150-235`), missing paths и `_PATH_PREDICATES` (`:283-300`), правила извлечения прямых фраз (`:309-311`) и answer-to-predicate mapping (`:480-489`). Source text material сохраняется в provenance. Tests `test_warehouse_and_service_facts_are_explicit_provenanced_and_never_inferred` и `test_warehouse_and_service_answers_keep_source_provenance_and_negative_stays_unknown` (`spike/T10/tests/test_t10_business.py:724-809`) проверяют явное извлечение, sparse unknown, event-aware вопросы, ответы, provenance и отдельные отрицательные predicates.

Независимый probe подтвердил: фраза `Сырьё хранится на складе Северный. Компания использует внешний сервис Облако Z.` породила `stores_at` и `uses_service`; sparse профиль торговца радиодеталями сохранил `/logistics/warehouses` и `/dependencies/services` в missing. Это устраняет первоначальное отсутствие поддержки в эксперименте.

Остаток не является скрытой ошибкой: `spike/T10/LIMITATIONS.md:15` прямо указывает, что Statement DTO не содержит typed target/relation endpoint, а predicates не зарегистрированы ontology owner. Поэтому значения хранятся как явно названный текст; T10 не может доказать company→warehouse/provider связь, привязку склада к конкретному компоненту или разрешить provider entity. До owner approval такие связи остаются unknown. Это integration gate, а не основание менять approved DTO в spike.

## Открытый MEDIUM integration gap: Business.read receipts

`Business.read` нормативно описан как чтение версии профиля **либо receipt** (`docs/specs/framework-v1/03-operations.md:249-264`). В текущем прототипе `read_profile(query, snapshots)` принимает только snapshots и при любом `ReceiptQuery` сразу возвращает `ReceiptResult(receipt=None)` (`spike/T10/src/t10_business.py:965-970`). Функция не получает receipts и не имеет owner read port; тесты проверяют профильный read, но не успешный receipt read. В `INDEPENDENT_REVIEW.md` это уже зафиксировано как documented gap. Это не блокирует четыре исправленных алгоритмических regressions, но означает, что модуль нельзя объявить полностью совместимым с Business.read operation до отдельной реализации/согласования этого пути.

## Фактические проверки

Запускались из worktree `codex/review-t10-final`:

```powershell
$env:PYTHONPATH = 'packages/contracts/src;spike/T10/src;spike/T10/tests'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T10/tests -q --tb=short
```

**90 passed, 0 failed, 0 skipped.**

Целевые remediation cases:

```powershell
$env:PYTHONPATH = 'packages/contracts/src;spike/T10/src;spike/T10/tests'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T10/tests -q --tb=short -k 'regression_future_recorded_statement or regression_apply_rejects_reviewers_foreign_supersede_probe_atomically or apply_rejects_each_incomplete_or_stale_supersede_reference_atomically or regression_conflicts_between_two_statements_in_one_new_proposal or regression_apply_detects_incoming_answer_conflict_with_current_snapshot or warehouse_and_service_facts_are_explicit_provenanced_and_never_inferred or warehouse_and_service_answers_keep_source_provenance_and_negative_stays_unknown or reconstructs_unknown_when_only_future_statement_exists'
```

**11 passed, 79 deselected.** Дополнительно на общем контрактном пакете: **31 passed**; shared v1.0.1 validator: **13 passed, 0 failed**, canonical hash совпал. В `spike/T10/src` не найдено imports/calls сетевых, model SDK или DB adapters. Код T10 и contracts не менялись. Перед commit re-review: `git diff --check` должен пройти; staged будет только этот report.

## Качество и готовность

- Engineering: tests **PASS (90/90)** на синтетическом наборе.
- Алгоритмическое качество: **PRELIMINARY**; live model/data quality **NOT MEASURED**.
- Четыре исходных finding-а: HIGH-01/HIGH-02 и numeric-conflict MEDIUM закрыты тестируемой remediation; R4 покрыт в рамках явных text facts/questions.
- Integration readiness: **NOT READY**. Нужны ontology-owner решения по warehouse/service predicates и типизированным связям, а также receipt-read путь; тестовые `TrustedOwnerPolicy`, изолированный in-memory apply и provisional fixtures не являются production owner implementation.
