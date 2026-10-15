# T08 → DeepSeek → T09: итог технической проверки

Дата: 2026-10-15. Актуальный статус: **offline prototype verified; Polza API and model alias responded; 3/5 current-version synthetic extractions passed local validation; T09 runtime integration unavailable**.

### Офлайн-проверки после последнего изменения

| Проверка | Результат |
|---|---|
| Полный T08 suite | `py -3.12 -m pytest spike/T08 -q` — **212 passed** |
| T08 → extraction unit/integration | `py -3.12 -m pytest spike/T08/test_fact_extraction.py -q` — **40 passed** |
| Framework contracts | `$env:PYTHONPATH='packages/contracts/src;apps/api/src'; py -3.12 -m pytest tests/contracts -q` — **31 passed** |
| Ruff check | `py -3.12 -m ruff check spike/T08/fact_extraction spike/T08/test_fact_extraction.py` — **passed** |
| Ruff format | `py -3.12 -m ruff format --check spike/T08/fact_extraction spike/T08/test_fact_extraction.py` — **passed** |
| Offline demo | `py -3.12 spike/T08/fact_extraction/offline_demo.py` — **exit 0**, no network |
| Contracts codegen | **Не выполнен в этой среде:** закреплённый `uv 0.13.0` отсутствует (есть `0.11.28`); прямой запуск codegen использовал несуществующий Python в старом worktree. OpenAPI/generated contracts не изменялись; contract tests прошли. |

Полный T08 suite и договорные тесты были реально повторены после изменений.
Codegen не засчитывается как PASS.

## Повторная проверка Polza и live-пилот после исправлений

Этот блок — актуальный результат и он **заменяет прежний статус только по
доступности API**. Старые попытки и их артефакты сохранены ниже/в `results/`.

Официальная документация Polza подтверждает endpoint
`https://polza.ai/api/v1/chat/completions`, Bearer-заголовок, переменную
`POLZA_API_KEY` и точный каталоговый ID `deepseek/deepseek-v4-flash`.
Дополнительно официальная документация DeepSeek описывает JSON Output через
`response_format: {"type":"json_object"}`. Ссылки: [Polza API](https://polza.ai/providers/deepseek),
[Polza model listing](https://polza.ai/models/deepseek/deepseek-v4-flash),
[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/).

В свежем бесплатном `GET /api/v1/models` получено HTTP 200; JSON корректный,
каталог содержал 409 моделей и требуемый ID. В коде официальное имя
`POLZA_API_KEY` приоритетное; прежнее `POLZA_AI_API_KEY` оставлено запасным,
чтобы не сломать локальную настройку. Значение ключа и тело GET-ответа не
сохранялись. В трёх успешных Chat Completions поле `model` совпало с требуемым
ID. Это подтверждает вызов именно этого alias через Polza, но не позволяет
проверить внутреннюю версию/checkpoint за маршрутизацией агрегатора.

Разбор первой серии выявил две проблемы integration-кода: модель не всегда
возвращала корректный JSON без JSON mode, а отдельные `company.quote` и
`event.quote` часто расходились. Включён JSON mode. Структуру также упростили:
теперь имя компании должно содержаться в той же единственной точной цитате,
что и формулировка события. Валидатор не ослабляли. Создана новая версия
точно-хешированного egress manifest `synthetic-live-allowlist-v2.json`; исходный
manifest оставлен без изменений. Runner теперь считает бюджет по всем
сохранённым попыткам и закрывает запуск, если нельзя доказать остаток.

Всего потрачено **10/10** разрешённых платных запросов; новых обращений к Jev не
было. В последних пяти вызовах с актуальной схемой все пять ответов прошли
JSON и внутреннюю Pydantic-схему; три прошли цитатные проверки и были преобразованы
в `ExtractionOutput`, два были безопасно отклонены проверкой связи компании и
события. Результаты:

| Пример | Результат | Задержка | Списание Polza |
|---|---|---:|---:|
| `nb-003` — сбой производства | `extracted` | 19,8 с | 0,06779016 ₽ |
| `nb-004` — изменение цены | `extracted` | 26,8 с | 0,06678776 ₽ |
| `nb-006` — санкции | `extracted` | 8,1 с | 0,07225474 ₽ |
| `nb-009` — трудовое событие | fail-closed: `company_event_relation_unverified` | 38,7 с | 0,05005711 ₽ |
| `nb-011` — инвестиции/мощность | fail-closed: `company_event_relation_unverified` | 38,0 с | 0,08434426 ₽ |

По всем 10 попыткам провайдер сообщил стоимость **0,56318761 ₽** для 8
запросов. Для 2 ранних попыток стоимость неизвестна (один timeout, один
невалидная schema-ответа до исправления сохранения usage); они могли тарифицироваться.
Полная таблица безопасных результатов и агрегированные показатели:
[summary JSON](results/deepseek-v4-flash-live-pilot-20261015-summary.json).
Пять последних артефактов сохраняют валидированные DTO, безопасные ошибки,
latency/token usage/cost и хеши prompt/schema, но не сохраняют ключ, сырой
ответ, prompt или полный текст новости.

**Реальный API работает; полностью надёжное извлечение не доказано.** Сейчас
система демонстрирует успешный структурированный результат на трёх
синтетических примерах и безопасно отказывает на двух. Это не метрики качества:
нет независимого human gold для извлечённых фактов, а `reported` не означает
подтверждение события. Повторить запросы нельзя: утверждённый бюджет исчерпан.
Для новой попытки нужен отдельный бюджет/разрешение и проверка причин двух
отказов человеком; текущие отказы нельзя обходить ослаблением проверки связи.

## Первичная live-попытка — исторический результат

По отдельному разрешению пользователя запущен один платный запрос к Polza для
первого утверждённого синтетического примера `nb-003` и сохранённого ответа Jev.
Транспорт ожидал ответ до таймаута примерно 25 секунд. HTTP-ответ не получен;
пилот остановлен после первой ошибки, повторов не было. Результат: **0 успешных
извлечений, 1 запрос предпринят, максимум 10 разрешённых, 9 не использованы**.

Так как провайдер не вернул ответ, token usage и стоимость неизвестны. Нельзя
исключить, что запрос был принят и тарифицирован до разрыва соединения; проверьте
историю запросов/расходов в кабинете Polza перед новым запуском. Причина
таймаута не установлена. Это **не HTTP 451**: HTTP-статус не был получен, поэтому
по этому запуску нельзя делать вывод о географическом ограничении, ключе или
доступности модели. Новых запросов к Jev не выполнялось.

Безопасные данные запуска находятся в
[`results/deepseek-v4-flash-live-pilot-20261015.json`](results/deepseek-v4-flash-live-pilot-20261015.json).
Исходный текст, ключ, prompt и сырой provider response не записывались.

## Реализованный поток

1. T08 загружает сохранённый ответ Jev и применяет Policy v2.1. Только уже
   выбранные Jev-кандидаты, прошедшие политику, передаются адаптеру извлечения.
2. Адаптер получает синтетический текст и фиксированный кандидат. DeepSeek не
   возвращает и не выбирает event code.
3. Строгая внутренняя схема извлекает event text, дату, место, участников,
   обстоятельства, assertion status и company role.
4. Значения и точные цитаты проверяются на уникальность и наличие в исходном
   тексте; проверяются offsets и SHA-256. Относительная дата не превращается в
   календарное время без достаточного якоря.
5. Результат отображается существующими `ExtractionOutput` / `EventMention`
   DTO. Никакой statement не объявляется `confirmed`.
6. Компания с ролью `reporter`, `mentioned` или `unknown` остаётся
   неразрешённой, получает `missing_data.company_relation` и не включается в
   actors/objects. Компания как `subject`, `actor` или `affected` — только
   извлечённый кандидат, основанный на model-reported роли и общей точной цитате.

Полная схема: [FLOW.md](FLOW.md). Офлайн-пример запускается командой из
[README.md](README.md).

## Пример, не являющийся ответом DeepSeek

Использован saved Jev result для `nb-003`: Jev выбрал
`production_operational_disruption`. Ручной офлайн fixture показывает результат
для новости о неработающей упаковочной линии:

- компания: «Ротор-Пром», роль `affected`;
- событие: «линия упаковки не работает»;
- дата: «со вчерашнего вечера», сохраняется как текст, `effective_at=null`;
- участник: ремонтная бригада;
- обстоятельства: повреждён привод конвейера, бригада ожидает запчасть;
- место: отсутствует;
- статус: `reported`, epistemic status не подтверждает истинность.

Компания и обстоятельства в этом примере заданы автором fixture. Результат
показывает контрактный mapping и проверки цитат, но **не качество модели**.

## Выполненные проверки

| Проверка | Команда / результат |
|---|---|
| Полный офлайн T08 suite | `py -3 -m pytest spike/T08 -q` — **205 passed, 0 failed, 0 skipped** |
| Extraction unit/integration tests | `py -3 -m pytest spike/T08/test_fact_extraction.py -q` — **33 passed** |
| Contracts | `py -3 -m pytest tests/contracts -q` — **31 passed** |
| Ruff | `py -3 -m ruff check spike/T08/fact_extraction spike/T08/test_fact_extraction.py` — passed |
| Ruff format | `py -3 -m ruff format --check spike/T08/fact_extraction spike/T08/test_fact_extraction.py` — passed |
| Contracts codegen | `UV_PROJECT_ENVIRONMENT=C:\\CodexData\\t08-fact-extraction-codegen-venv uv --no-config run --locked --all-groups python tools/contracts_codegen.py --check` — passed; generated contracts match OpenAPI |
| Offline demo | `py -3 spike/T08/fact_extraction/offline_demo.py` — exit 0; saved Jev + hand-authored fixture; no network |

В тестах адаптера использованы только fake transports. Проверяются default-off,
точный pinned endpoint/model ID, один запрос без retries, allowlist payload,
ограничение размера ответа, sanitized errors, отказ по redirect и запрет
публичной подмены transport. Проверки не выполняли HTTP-запросов к Jev или
DeepSeek.

## API и идентичность модели

- Каталог Polza показывает требуемый model ID
  `deepseek/deepseek-v4-flash`.
- Для OpenAI-compatible Chat Completions Polza указывает
  `https://polza.ai/api/v1/chat/completions` и Bearer authorization.
- В предыдущем исследовании журнал DeepSeek сообщал о возможной маршрутизации
  старого V4 Flash alias на V4.1 Flash. Последующий ответ Polza вернул
  запрошенный alias; внутренний checkpoint/версию весов агрегатора это всё ещё
  не доказывает. Код сохраняет согласованный с пользователем ID и не переключается.
- Источники: [Polza model listing](https://polza.ai/models/deepseek/deepseek-v4-flash),
  [Polza DeepSeek API instructions](https://polza.ai/providers/deepseek),
  [DeepSeek release log](https://api-docs.deepseek.com/updates/?release=deepseek-coder).

**Исторический live-результат первой попытки: TIMEOUT.** Этот единичный запуск не
получил HTTP-ответа; последующие запросы и их статус приведены в актуальном блоке
выше. Возможная стоимость этой попытки остаётся неизвестна.

## Независимое ревью

AI Factory reviewer провёл два read-only прохода без внешних вызовов.

1. Найден HIGH: конструктор live adapter принимал произвольный transport,
   который мог получить bearer key и текст, обойдя закреплённый host. Исправлено:
   live constructor всегда создаёт private pinned HTTPS transport, redirects и
   proxy discovery отключены; подмена оставлена только как private test seam.
2. Найден MEDIUM: совместное присутствие компании и события в цитате могло
   ошибочно связать компанию-репортёра с чужим событием. Исправлено:
   `company_role` выделена в строгой схеме; reporter/mentioned/unknown не
   становятся стороной события; добавлены проверки общей точной цитаты и
   границ предложения. Регрессионный тест проверяет фразу «Ротор-Пром сообщила,
   что у Северного Контура линия упаковки не работает».
3. Повторный review подтвердил закрытие обоих замечаний; блокирующих
   CRITICAL/HIGH/MEDIUM замечаний по текущему spike не осталось.

Остаётся модельный риск: DeepSeek может неверно определить `company_role`.
Цитата и валидатор этого не доказывают; такие результаты — только кандидаты для
проверки downstream.

## Ограничения и решение

- В репозитории нет runtime T09, зарегистрированного EventSchemaRegistry,
  Evidence owner и исполняемого `Events.propose_resolution`. Сейчас проверен
  только совместимый shape действующих DTO; фактическая передача владельцу
  данных ещё не реализована.
- External egress закрыт по умолчанию и ограничен exact-hash allowlist для
  synthetic Jev pilot. Реальные, public и unknown материалы этот spike не
  отправляет.
- Polza endpoint и каталоговый alias реально ответили; это доказывает
  доступность API и успешную работу extraction pipeline на трёх случаях, но не
  внутренний checkpoint провайдера.
- Нельзя объявлять точность/качество извлечения проверенными: нужны
  independently human-reviewed extraction labels и расширенная оценка ошибок.

Итог по последней проверке: **Polza API работает, extraction pipeline
продемонстрирован на трёх синтетических новостях; два результата безопасно
отклонены из-за неподтверждённой связи компании и события. Тестовый бюджет
исчерпан, модельное качество не измерено, runtime T09 integration по-прежнему
не проверялась.**
