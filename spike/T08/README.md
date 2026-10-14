# T08 Jev classification spike

Изолированная проверка Jev через Polza AI для русскоязычных синтетических бизнес-новостей. Spike не подключён к runtime, не меняет OpenAPI и не использует другой классификатор.

## Текущий результат — 2026-10-14

- Engineering: **PASS** — 86 тестов, Ruff и offline runner прошли; сохранённые Choice ответы дополнительно сверены с официальной формулой confidence.
- Polza API: **PASS в ограниченном объёме** — 44 staged ответа плюс один исторический smoke schema-valid на Jev 1.13.0. Все текущие staged отчёты совпадают с hash Jev клиента; runner изменился после live-партии.
- Model quality: **NOT MEASURED для решения об интеграции**. Предварительные частичные числа по 45/49: тема 31/45 (68,9%), event micro-F1 0,840, multi-label exact 34/45, review 42/45 (93,3%). Gold — односторонний synthetic draft, есть спор e33, четыре ответа отсутствуют.
- Integration: **NOT READY** — нет нормативного Understanding.classify adapter и runtime policy/provenance/history/replay integration.
- Live budget: пилотный ledger содержит **50 попыток** (включая один legacy TypeSafe POST). Кроме них в истории есть три более ранних HTTP 451 route-check вызова; общий известный след — **53**, если считать их одним бюджетом. Ledger не включает старые route-check и является только локальной best-effort защитой. Никаких новых live вызовов без отдельного разрешения.

Полные метрики и ограничения: TEST_REPORT.md и TEST_REPORT.json. Финальный aggregate v4: results/jev-live-aggregate-20261014-v4.json. Предыдущие агрегаты и отчёты сохранены без перезаписи.

## Offline commands

    python -m unittest discover -s spike/T08 -p "test*.py" -v
    ruff check spike/T08
    ruff format --check spike/T08
    python spike/T08/run_spike.py

Офлайн runner проверяет входы, taxonomy и corpus и не вызывает классификатор.

## Live API safety

Проектный маршрут — POST https://polza.ai/api/v1/systemone, Jev model ID typesafe/jev. Ключ читается только из POLZA_AI_API_KEY окружения Windows. Он не выводится и не сохраняется. Запросы фиксируют synthetic case hash; transport запрещает redirects и proxy discovery, автоматических повторов нет.

Дополнительные вызовы требуют отдельного решения и нового бюджета; текущий пилот закрыт. Local ledger — только best-effort локальная защита, не защита от редактирования/удаления или смены LOCALAPPDATA/XDG_STATE_HOME.

Старые HTTP 451 были на прямом TypeSafe host. Их точная причина неизвестна, и они не описывают Polza доступность. Географические/юридические ограничения не обходились. Все три таких route-check входят в общий исторический след из 53 вызовов, но не в 50-попытковый пилотный ledger.

## Данные и taxonomy

Исходный baseline неизменён: corpus hash 592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d. Taxonomy 0.3.0-spike неизменена: hash 855a61f9b6c199d8440b8b81bbd09234e376896121ed163af2ed7f0c1455d. Deep corpus содержит 160 synthetic cases; Jev на них не запускался. Gold labels остаются односторонними draft; D не blind, B24 спорный. Разногласие по e33 описано в experiments/2026-10-14-independent-review.md.

Метки тем выбираются одним Jev Choice; события задаются независимыми Noul вопросами. IPTC, GDELT, Event Registry и RavenPack — только справочные источники, не запускаемые модели.

## Следующий шаг

Не интегрировать автоматически. Сначала провести human adjudication gold labels, создать отдельный versioned blind benchmark и согласовать новый live budget. Затем проектировать adapter к утверждённым input/output DTO и policy boundaries без изменения OpenAPI.
