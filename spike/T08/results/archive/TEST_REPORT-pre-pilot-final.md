# T08 Jev classification spike — итоговый технический и экспериментальный отчёт

**Дата аудита:** 2026-10-14

**Ветка:** `codex/spike-t08-jev-news-classification`

**Базовый `main`, проверенный для spike:** `ce640214be7c5ff2fdb451b9e290135a11b512a6`

**Текущий HEAD:** см. head текущего PR #8; отчёт не записывает SHA собственного commit, чтобы не создавать самоссылку.
**Область:** только `spike/T08/`; production runtime, OpenAPI и generated contracts не изменялись.

## Краткое резюме

После уточнения пользователя транспорт исправлен на официальный Polza AI System One endpoint, с `POLZA_AI_API_KEY` и Jev model ID `typesafe/jev`. Запрос устанавливает `provider.allow_fallbacks=false`; фактическое поведение маршрутизации у провайдера отдельно не проверено. Ответы строго проверяются, включая `usage.cost_rub`. Клиент ограничивает размер/время запроса, запрещает redirects/proxy discovery/retries и отправку неразрешённых данных. Текущий offline suite: **70 passed, 0 failed, 0 skipped**.

Выполнен один live smoke на закреплённом синтетическом кейсе `e01-supply-rail`: Polza вернула schema-valid ответ Jev `jev-1.13.0`. Наблюдение: тема `industry_trade_supply`, `supply_chain_disruption=0.90`, unlisted score `0.53`, поэтому harness направил запись на review. Затраты: 5,905 входных токенов, 492 выходных, **0.10391619 ₽**, latency **844 ms**. Это один случай, не benchmark. Он выполнен предыдущей версией client/runner (SHA-256 `5ef1c6c7…` / `3a4ed49c…`). SHA запроса совпадает с повторно сгенерированным запросом текущего клиента (`a5d7356b…`), однако после последующих изменений текущая ревизия не вызывала API. Артефакт содержит только результат отдельного наблюдения; агрегированные quality-метрики не вычислялись, точность и все quality-метрики остаются **NOT MEASURED**.

Три исторических HTTP 451 получены при прежней прямой маршрутизации на `api.typesafe.ai`; они не являются результатом проверки Polza и не устанавливают причину отказа. Во время фикса один регрессионный тест случайно инициировал дополнительный запрос на старый TypeSafe endpoint с pinned synthetic кейсом, поскольку тестовая legacy-переменная была непустой. Для него сохранён только `sanitized_request_error`; тело ответа, ключ и детали исключения не сохранены. Тест исправлен: он проверяет, что без `POLZA_AI_API_KEY` сетевой вызов невозможен даже при legacy `TYPESAFE_API_KEY`.

Текущий corpus расширен до 160 synthetic кейсов (158 непустых), но gold labels — черновая разметка одного автора, а отдельный split D видим в репозитории и не является blind holdout. Один кейс B24 конфликтует с формулировкой категории и должен быть исключён из оценки до adjudication. Новый корпус пока проверяется на структуру и ожидаемые отношения; Jev его не классифицировал.

**Можно ли уже доверить Jev классификацию русскоязычных бизнес-новостей? Нет. Качество ещё не доказано.** Jev остаётся единственным классификатором. Один успешный round-trip подтверждает проверенную базовую Polza API-схему, но не качество по категориям, надёжность, calibration или устойчивость. Оставить spike изолированным; запрашивать отдельное разрешение/бюджет перед дополнительной платной партией.

## Четыре независимых заключения

| Область | Статус | Основание |
|---|---|---|
| **ENGINEERING QUALITY** | **PASS** | 70/70 offline tests, Ruff check/format, offline runner и `git diff --check` прошли. Это оценка harness, не модели. |
| **API COMPATIBILITY** | **PASS (historical tested path/schema)** | Один фактический Polza `System One` round-trip с `typesafe/jev` прошёл на предыдущей ревизии. Текущий request hash совпадает; текущий transport revision повторно live не запускался. Это подтверждает лишь исторически проверенную конфигурацию, не все ошибки/режимы API. |
| **MODEL QUALITY** | **NOT MEASURED** | Один smoke-response наблюдался, но выборки недостаточно для quality метрик; latency и стоимость измерены только для этого запроса. |
| **INTEGRATION READINESS** | **NOT READY** | Нет репрезентативного quality evaluation; labels не adjudicated, а spike не реализует normative DTO, provenance, policy, history или replay. |

## Что проверялось и как

Проведены независимые проверки API, архитектуры/безопасности, таксономии и корпуса. Реализация сверена с [официальной документацией Polza System One](https://polza.ai/docs/api-reference/systemone/create), [гайдом Polza Jev](https://polza.ai/jev) и [моделью Polza `typesafe/jev`](https://polza.ai/models/typesafe/jev), а также нормативным `Understanding.classify` и содержимым кода. Отчёт не полагается на прежние заявления README. Проверены `docs/specs/framework-v1/03-operations.md` §05 и OpenAPI `#/components/schemas/ClassificationInput` / `ClassificationOutput`.

Отправлен один синтетический запрос через Polza, как указано в live-артефакте. Значение ключа не читалось в вывод и не записывалось; реальные новости и расширенный корпус не отправлялись. Других Polza live-запросов не выполнялось. Прямой TypeSafe запрос из legacy regression test описан отдельно выше и не использовался для обхода ограничений.

### Последний воспроизводимый прогон

| Команда | Результат |
|---|---|
| `python -m unittest discover -s spike/T08 -p "test*.py" -v` | **70 passed, 0 failed, 0 skipped** |
| `ruff check spike/T08` | Passed |
| `ruff format --check spike/T08` | Passed, 12 Python files already formatted |
| `python spike/T08/run_spike.py` | Passed; offline validation, 0 classifier calls, baseline 49 nonempty + 1 locally rejected empty input |
| `python spike/T08/run_spike.py --live --max-calls 1` (recorded earlier) | **1 Polza request succeeded on the recorded earlier revision**; cost 0.10391619 ₽, 5,905 input / 492 output tokens, 844 ms; not a quality benchmark |
| `git diff --check` | Passed |

Полное Jev evaluation, per-category quality, calibration, стабильность, provider-side prompt-injection и Russian-language quality остаются **NOT MEASURED**. Фактические latency/cost доступны только для одного smoke-запроса и не обобщаются. Offline suite запрещает обычные Python socket entrypoints во время тестов и проверяет сам guard. Это process-level защита теста, не OS/container firewall против произвольного native-кода.

Тесты используют контролируемые fake responses только для проверки валидации, транспорта и арифметики. Такие значения не включались в model-quality отчёт. Во время разработки одна ошибка в тестовом fixture была исправлена; приведённый выше результат относится к новому полному прогону после исправлений.

## Проверка официального Jev API

По актуальным на дату аудита официальным документам Polza:

- Jev System One: `POST https://polza.ai/api/v1/systemone`; `Authorization: Bearer <POLZA_AI_API_KEY>`.
- Polza Jev guide/catalog specifies model ID `typesafe/jev`; generic API examples also use `jev-latest`. Spike pins the catalog ID used by the Jev-specific guide and records the returned model version.
- Request fields are `state`, `model`, `questions`, and optional `provider`. The live request used the native `Choice` + 17 independent `Noul` questions and `provider.allow_fallbacks=false`.
- Polza docs say System One accepts 1–256 questions, and Choice accepts up to 255 options. This spike applies a stricter local 20-question budget cap; current request has 18 questions.
- Choice returns `choice`, probabilities and confidence; Noul returns a yes score in `[0,1]`. The checked Polza docs do **not** specify an arithmetic formula for Choice confidence, so the harness checks its type/range but does not infer consistency from probabilities.
- Response requires `model`, `answers`, `usage`; `usage` documents `input_tokens`, `output_tokens`, `cost_rub`. The response validator checks all three usage values.
- One successful Polza round-trip on the recorded earlier client/runner revision returned model `jev-1.13.0`. The regenerated current request has the same hash; the current transport/parser changes have only offline verification.

**Вывод:** API compatibility статуса PASS только для исторически проверенного request/response path. Запрос включает `provider.allow_fallbacks=false`, однако фактический выбор upstream provider и соблюдение настройки на стороне Polza по одному ответу проверить нельзя. Текущий клиент совпадает по request hash, но новые проверки отказов/error sanitization проверялись офлайн. Не проверены все provider error modes, другие вопросы/кейсы и качество на статистически значимой выборке.

## HTTP 451: известные факты и неизвестное

Сохранённые старые артефакты (`spike/T08/results/route-check.json:8`, `jev-live-pilot-20261014T080227Z.json:18`, `jev-live-pilot-20261014T080859Z.json:18`) относятся к прежнему прямому host `api.typesafe.ai`, который был неверным для настроенного в проекте Polza доступа. Они подтверждают:

1. Одна аутентифицированная discovery-попытка `GET /v1/models` завершилась 451.
2. По одному одиночному synthetic POST на `/v1/systemone` для taxonomy 0.1 и 0.2 завершились 451.
3. В этих исторических попытках taxonomy 0.3, расширенный corpus, реальные новости и batch не отправлялись.
4. Raw body и request ID не сохранены. Ни один ответ Jev не получен.
5. Проверенная таблица ошибок TypeSafe документирует стандартные ответы вроде 401/422/429/529, но не объясняет 451. Поэтому точная причина и источник статуса не установлены.

Подтверждён только факт HTTP 451 на прежнем прямом TypeSafe route; источник и причина по сохранённым данным неизвестны. Этот статус не является проверкой Polza и не говорит о доступности или качестве через Polza. Не было попыток обходить ограничения: по уточнению пользователя штатный проектный путь — Polza AI. Один дополнительный вызов на старом host из регрессионного теста завершился `sanitized_request_error` без сохранения тела/причины; исправленный тест не отправляет запрос без `POLZA_AI_API_KEY`.

## Таксономия 0.3.0-spike

Текущие исходные `taxonomy.json` и `corpus.json` сохранены без изменений. Таксономия содержит 11 Choice вариантов: 10 тем и `other_uncertain`; 15 отдельных бизнес-событий; отдельные Noul для события вне списка и недостаточности свидетельств. Один вопрос на тему и отдельный Noul на каждый event подходят для независимой multi-label постановки на уровне конструкции. Это не доказывает, что реальные Noul оценки статистически независимы.

### Межкатегорийные границы

| Граница | Рабочее различие v0.3 | Риск/что уточнить |
|---|---|---|
| sanctions / trade_restriction | Санкции требуют названной санкционной меры/цели; ограничение торговли — явного запрета/квоты/тарифа на cross-border goods. Обе метки допустимы только если отдельно подтверждены оба факта. | Слова «санкции» и «ограничение» часто соседствуют; модель может выводить одно из другого. Добавить парные примеры только одного режима и обоих режимов. |
| insolvency_default / legal_enforcement | Insolvency требует формальной процедуры/дефолта/пропуска платежа. Enforcement — отдельный иск, штраф, расследование, взыскание или решение, а не просто обычная судебная форма банкротства. | Текущая русская метка `legal_enforcement` звучит уже определения и включает расследования. Формализовать самостоятельность юридического события и термин метки. |
| supply_chain_disruption / shortage_capacity_constraint | Нарушен поток поставок против явно недостаточного запаса/мощности, ограничивающего операцию. Обе метки — если текст явно сообщает оба факта. | Задержку часто ошибочно принимают за shortage; отсутствие товара — за доказанную причину сбоя поставки. |
| production_operational_disruption / investment_capacity_change | Фактическая остановка/снижение работы против инвестиции, запуска или изменения заявленной мощности. | Будущий план и завершившийся факт смешиваются; нужно решить, считаются ли утверждённые будущие планы event, и как трактовать отмену. |
| regulation_tax_change / legal_enforcement | Изменение нормы/налога/режима против отдельного расследования, судебного решения или enforcement action. | Официальный акт может быть и политическим, и регулирующим; нужны main-subject правила и пары тариф/налог/санкции/штраф. |
| price_cost_change / regulation_tax_change | Фактическое/официально вступившее изменение цены/затрат против изменения политики/налога. | B24 описывает объявленный будущий рост цены: текущая дефиниция и инструкция расходятся. Этот кейс нельзя оценивать до решения о временном критерии. |

Дополнительные тематические пересечения: `business_companies` рискует быть остаточной меткой при любом упоминании компании; `industry_trade_supply` широко охватывает физические операции; `energy_resources` включает спорный случай водных ограничений; `politics_government` и `law_regulation` расходятся на официальных мерах; `other_uncertain` сводит разные случаи «неизвестной темы» и «недостаточных свидетельств». Два статуса `uncertain` в baseline имеют разные основания: ясное событие вне списка и неполное/неподтверждённое сообщение.

Предложения только для будущей **отдельной** версии v0.4, не применены к v0.3:

1. Сформулировать правило основной темы: subject/framing, а не любой упомянутый актор или денежный термин; добавить matched pairs для `politics_government`/`law_regulation`/`economy_finance`/`business_companies`.
2. Развести «категория вне словаря» и «данных недостаточно» на две причины/сигнала в допустимой проектной схеме, если это совместимо с публичным DTO; до этого зафиксировать их в ручной инструкции.
3. Определить, считаются ли будущие объявленные, но ещё не вступившие в силу события; пересмотреть B24 и labor case с будущим наймом после решения.
4. Проверить смысл русской метки `legal_enforcement` против покрытия расследований/исков/штрафов.
5. Добавить в справочник обсуждаемые, но ещё не введённые меры, слухи/опровержения, формальное банкротство vs стресс, задержку vs shortage, промышленный пожар vs экологический ущерб, тариф, меняющий затраты без явного запрета импорта.
6. Рассмотреть fraud/corruption, крупный контракт/потерю заказа, стратегическое партнёрство/JV как кандидатов в event list. Их частота и бизнес-ценность этим синтетическим аудитом не измерены.

Подробное описание каждой из 11 тем и 15 event категорий с позитивными/негативными примерами, hard boundaries и вероятными источниками ошибок — [`experiments/deep-v1/TAXONOMY_REVIEW.md`](experiments/deep-v1/TAXONOMY_REVIEW.md). Позитивный/негативный пример там характеризует текущие ручные gold labels, а не модель.

## Расширенный synthetic корпус и gold labels

Новый dataset: `experiments/deep-v1/`, version `1.0.0`, taxonomy `0.3.0-spike`, всего **160 кейсов / 158 непустых**. SHA-256 manifest закреплён в тесте; manifest закрепляет точные байты split-файлов и hashes исходных taxonomy/corpus.

| Split | Кейс(ов) | Непустых | Назначение | Состояние |
|---|---:|---:|---|---|
| A | 76 | 75 | широкий фиксированный benchmark | Не прогонялся через Jev; каждый из 15 event codes представлен минимум четырьмя положительными gold-примерами. |
| B | 36 | 36 | спорные границы и сложные кейсы | 6 названных границ × 4 примера; B24 исключить до adjudication. |
| C | 24 | 24 | 12 пар metamorphic stimuli | 7 пар с ожидаемой инвариантностью и 5 с ожидаемым изменением gold; проверяется только объявленная связь labels, не реакция модели. |
| D | 24 | 23 | отдельный контрольный split | Не использовался для tuning; файл и labels видимы и были доступны автору. **Это не слепой holdout.** |

Примеры синтетические и не являются реальными публикациями. Набор включает короткий/длинный текст, multi-event, не-события, неподтверждённые/отменённые/будущие/противоречивые утверждения, несколько сущностей, цены, санкции, поставки, банкротство, киберинциденты, аварии, изменения норм, числа, цитаты, misleading headline, шум, out-of-list, prompt-injection stimulus и Unicode. `language:ru-en` метка в A/B/C отсутствует; есть только один bilingual-quote stimulus в C, поэтому широкая многоязычная устойчивость не покрыта.

Gold labels написаны без ответов Jev, однако это **single-annotator draft**: независимая double annotation и adjudication не проводились. Одного структурного review недостаточно для утверждения объективной разметки. Набор не использовался для вывода Jev качества и не может служить blind prospective benchmark в текущем виде. После заморозки rubric нужно получить вторую слепую разметку, adjudicate все расхождения и сохранить отдельную версию.

### Ручной охват benchmark A (не метрики Jev)

Число положительных ручных примеров по каждому event code в A: `supply_chain_disruption` 8; `production_operational_disruption` 5; `environment_disaster_impact` 5; `cyber_security_incident` 5; `labor_workforce_event` 5; `shortage_capacity_constraint` 4; `price_cost_change` 4; `trade_restriction` 4; `sanctions` 4; `regulation_tax_change` 4; `insolvency_default` 4; `corporate_transaction_restructuring` 4; `product_recall_quality_safety` 4; `legal_enforcement` 4; `investment_capacity_change` 4. Это только support в draft labels; полноценные независимые negative challenge examples и распределение production prevalence из этого не следуют.

Все строки ниже означают ручную разметку split A. Jev не запускался, поэтому качество каждого кода отдельно **NOT MEASURED**.

| Общая тема | Gold support A | Jev accuracy |
|---|---:|---|
| `industry_trade_supply` | 15 | NOT MEASURED |
| `business_companies` | 11 | NOT MEASURED |
| `law_regulation` | 11 | NOT MEASURED |
| `technology_telecom` | 8 | NOT MEASURED |
| `politics_government` | 8 | NOT MEASURED |
| `energy_resources` | 5 | NOT MEASURED |
| `labor_employment` | 5 | NOT MEASURED |
| `environment_disasters` | 4 | NOT MEASURED |
| `economy_finance` | 3 | NOT MEASURED |
| `health` | 3 | NOT MEASURED |
| `other_uncertain` | 2 | NOT MEASURED |

| Бизнес-событие | Gold positives A | Jev precision / recall / F1 |
|---|---:|---|
| `supply_chain_disruption` | 8 | NOT MEASURED |
| `production_operational_disruption` | 5 | NOT MEASURED |
| `environment_disaster_impact` | 5 | NOT MEASURED |
| `cyber_security_incident` | 5 | NOT MEASURED |
| `labor_workforce_event` | 5 | NOT MEASURED |
| `shortage_capacity_constraint` | 4 | NOT MEASURED |
| `price_cost_change` | 4 | NOT MEASURED |
| `trade_restriction` | 4 | NOT MEASURED |
| `sanctions` | 4 | NOT MEASURED |
| `regulation_tax_change` | 4 | NOT MEASURED |
| `insolvency_default` | 4 | NOT MEASURED |
| `corporate_transaction_restructuring` | 4 | NOT MEASURED |
| `product_recall_quality_safety` | 4 | NOT MEASURED |
| `legal_enforcement` | 4 | NOT MEASURED |
| `investment_capacity_change` | 4 | NOT MEASURED |

## Метрики качества, сложность, стабильность, latency и стоимость

**Метрики качества Jev — NOT MEASURED.** Нет осмысленных per-topic accuracy/confusion matrix; per-event precision/recall/F1, micro/macro F1; exact multi-label match; false positives/negatives; review rates; out-of-list/unconfirmed detection; category slices; calibration; stability; prompt-injection metrics. Есть только один live observation: latency 844 ms и usage 5,905 input/492 output tokens, cost 0.10391619 ₽. n=1 не поддерживает обобщённую оценку; эти цифры описывают только этот запрос.

Код evaluator реализует эти срезы и threshold sweeps, включая Choice selective accuracy/coverage; корректность математики проверена на синтетически контролируемых fixtures. Это проверка evaluator, не оценка Jev. Пороги Choice `<0.5`, Noul `<=0.2`/`>=0.8` — текущие экспериментальные правила без эмпирического обоснования. Sweep проверен математически, но его живые precision/recall, review burden и пропуски событий не измерены. Noul scores и Choice confidence нельзя объявлять откалиброванными вероятностями качества на русских новостях без отдельной calibration study.

`usage.cost_rub` зафиксировал стоимость smoke-запроса 0.10391619 ₽. Это фактическая стоимость одного запроса, не оценка средней цены статьи или batch; цена/usage могут изменяться с размером текста, набором вопросов и тарифом.

## Offline проверки, ошибки и безопасность

Текущие tests проверяют:

- Типы и размер входа (10 000 символов), пустые данные, Unicode/строки, отсутствие отправки gold metadata и лишних полей.
- Native Choice/Noul форму, опции Choice, допустимые коды, совпадение выбора с максимальной оценкой, numeric range `confidence`, NaN/Infinity, отрицательные/выше единицы оценки, некорректные/пропущенные/лишние ответы, token usage и `cost_rub`.
- HTTP 400/401/403/429/451/500/502/503/529, timeout, connection reset, повреждённый/не-JSON ответ, тело больше лимита, redirect, запрещённый host, отказ от env proxy, отсутствие retry, sanitized ошибки.
- Allowlist канонического request hash и блокировка повтора в одном процессе; текущий live default — один запрос, `--max-calls` действует на один запуск, cumulative budget между запусками не хранится. Проверяются pinned model и флаг `provider.allow_fallbacks=false` в запросе; внешнее соблюдение флага не проверено.
- Пустые/дублирующиеся/неизвестные result IDs, отсутствующие телеметрические поля, вычисление метрик/threshold sweep на fixtures.
- Пины исходных taxonomy/corpus, pины manifest и A/B/C/D split hashes, label codes/status, 15 категорий, boundary counts и объявленные связи C.

Транспорт использует фиксированный официальный Polza HTTPS endpoint, Bearer auth через `POLZA_AI_API_KEY`, Jev ID `typesafe/jev`, request flag `provider.allow_fallbacks=false`, стандартный TLS context, redirect refusal, proxy-discovery off, bounded timeout/response body и sanitized exceptions. HTTP errors сохраняют только статус; тело и все provider-supplied metadata отбрасываются. Клиент требует непустой allowlist request hash, не отправляет один hash дважды в рамках одного процесса и не ретраит. Live runner по умолчанию ограничен одним запросом; `--max-calls` и дубликатный guard не являются cumulative между запусками. Live allowlist содержит только закреплённые 49 исходных synthetic новостей.

Security caveats:

- Socket guard — стандартные Python entrypoints; это не защита от произвольного native socket code или отдельный сетевой sandbox.
- Prompt injection проверен offline только на неизменность фиксированных критериев/категорий в request. Фактическая реакция Jev на инъекцию, правила provider isolation и утечка через реальную модель не измерялись.
- Canary на секреты/текст проверяется на fake transport/errors; сохранённый live artifact не содержит текст/ключ. Внешние provider logs не исследовались; Polza заявляет в своей документации, что не хранит текст запросов/ответов, но это vendor statement, не независимая проверка.
- Live request неизбежно передаёт текст провайдеру. Отправлен только один закреплённый synthetic case; текст и raw prompt не записывались в артефакт.
- Исторические ошибки хранят только HTTP status; response bodies, provider metadata, raw prompts и keys отсутствуют.
- Гарантия synthetic-only обеспечена CLI-путём загрузки закреплённого корпуса. `JevClient` сам принимает переданный вызывающим кодом набор request hashes и не является самостоятельной безопасной границей для повторного использования с произвольными импортами.
- Gitleaks в окружении не установлен. Целевой high-confidence pattern scan spike-файлов и read-only scan security reviewer не нашли совпадений; это ограниченная проверка, не универсальный secret scanner.
- Bounded response защищает чтение тела; текст ограничивается по символам, а не по токенам. Polza docs разрешают 1–256 вопросов, но spike локально ограничивает их числом 20 для сдерживания расходов.

Итоговая оценка безопасности spike transport: **offline controls PASS; provider-side behavior NOT MEASURED**.

## Совместимость с Framework v1 `Understanding.classify`

Нормативные вход/выход находятся в `03-operations.md` §05 и OpenAPI `#/components/schemas/ClassificationInput` / `ClassificationOutput`. OpenAPI/generated contracts не менялись.

| Проверка | Статус | Наблюдение / минимально необходимое изменение |
|---|---|---|
| Jev выбран единственным классификатором spike | Частично совместимо | В spike Jev единственный; runtime integration не существует. |
| Одна тема плюс независимые event labels | Частично совместимо | Choice + 15 Noul соответствуют общей идее; `multi_label` не является входным параметром runtime, taxonomy фиксирована внутри spike. |
| `ClassificationInput.material`, taxonomy `VersionedRef`, `allowed_codes`, `multi_label` | Не совместимо | Spike принимает собственные title/text case и использует встроенную таксономию. Адаптер должен валидировать нормативный DTO и применять разрешённый набор кодов. |
| Output `topics`, `event_hints`, `classification_status`, `missing_data` | Не совместимо | Spike выводит собственное решение (`topic`, scores, predicted events/status). Нужен явный типизированный mapper с сохранением границ DTO; не менять OpenAPI. |
| Произвольные коды запрещены | Частично совместимо | Spike ограничивает ответы зарегистрированными кодами. Runtime policy/allowed_codes matching не реализован. |
| Unknown/uncertain, provenance, trusted policy, dependency gateway, history, replay | Не совместимо | Это изолированный experiment runner без owner/runtime интеграции. Перед интеграцией требуются policy-before-egress, approved taxonomy reference, provenance, sanitized Run History и record/replay через утверждённые ports. |
| Работающий API round-trip, provider compatibility | Проверено частично | Один запрос прошёл через Polza и был строго провалидирован; это не подтверждает все API режимы. |

**Ни одна полная end-to-end runtime совместимость не подтверждена.** Spike нельзя регистрировать как implementation `Understanding.classify`.

## Независимое ревью

- **API/реализация:** после смены целевого route по уточнению пользователя проверены Polza endpoint, auth, model ID, request/provider flags, primitives и usage schema. Исправлены неверный direct host/key name, необработанный `cost_rub`, предположение о confidence formula и ошибочная трактовка вопросного лимита. Один успешный Polza round-trip наблюдался.
- **Таксономия/данные:** проверены все темы, события, шесть заданных границ, примеры и статус gold labels. Серьёзное ограничение — однопользовательская draft annotation и неслепой D; B24 отложен.
- **Архитектура/безопасность:** подтверждено отсутствие связей с production runtime; добавлены проверки единичности timeout/reset попытки и pin всего manifest/общее количество nonempty случаев. Финальный security review выявил, что regex-shaped `error.code`/UUID могли содержать переданные canary-данные; исправлено: тело и любые provider error metadata полностью отброшены, оставляется только HTTP status, тест проверяет valid-shaped canaries. Пост-fix reviewer blocker не обнаружил; отдельно указал, что reusable `JevClient` сам по себе не гарантирует synthetic-only allowlist.
- **Статистика:** evaluator и пороговая арифметика проверяются на fake fixtures. Это не evidence качества. Deep evaluator/live runner ещё не поддерживают отдельное сравнение A/B/C; D намеренно не используется в scoring.

Ревьюеры не подтверждают качество Jev: одного live-примера недостаточно. API block по Polza снят для проверенного пути; открыты adjudication labels и разрешение на больший оплачиваемый pilot.

## Основные замечания с воспроизводимостью

### RESOLVED — Provider error metadata могла содержать canary-текст

- **Где:** `jev_spike.py:421-423` (`https_transport` HTTPError handling), `run_spike.py:44-65` (`_safe_failure`), `test_spike.py:702-750` (`test_http_error_body_is_suppressed`).
- **Воспроизведение до исправления:** fake HTTP error возвращал форматно допустимые `error.code=ARTICLE_SECRET` и UUID-shaped canary; прежний код сохранял их в sanitized report.
- **Ожидалось:** ни тело provider error, ни произвольные provider fields не сохраняются.
- **Фактически до исправления:** проверка формы метаданных не доказывала, что их значение не происходит из переданного текста или секрета.
- **Исправление:** provider error body не читается/не разбирается; сохраняется только HTTP status. Регрессионный тест проверяет, что оба shaped-canary отсутствуют в serialized failure.

### LOW — Live-call cap действует на один запуск

- **Где:** `run_spike.py:94-105,207-212` и `jev_spike.py` `JevClient` hash ledger.
- **Воспроизведение:** повторить live CLI несколько раз; in-memory guard и cap сбрасываются между процессами.
- **Ожидается:** cumulative spending budget был бы ограничен между вызовами.
- **Фактически:** максимум 50 live calls и блокировка повтора hash действуют на один invocation; default снижен до одного вызова. Persistent cumulative ledger нет.
- **Действие:** не повторять платные вызовы без отдельного согласованного бюджета; runner documentation явно описывает границу guard.

### RESOLVED — Spike использовал неправильный direct TypeSafe endpoint

- **Где:** прежние версии `jev_spike.py` / `run_spike.py`; исторические артефакты в `results/`.
- **Воспроизведение:** сохранённые обращения к `api.typesafe.ai` завершились HTTP 451; ещё одна ошибочная регрессионная попытка имеет только `sanitized_request_error`.
- **Ожидалось:** использовать проектный Polza route и credential.
- **Фактически:** предыдущая реализация ходила напрямую в TypeSafe и читала неправильную переменную ключа.
- **Исправление:** фиксированный Polza endpoint, только `POLZA_AI_API_KEY`, exact model `typesafe/jev`, запрос устанавливает `provider.allow_fallbacks=false` (эффективность настройки upstream не подтверждена); один исторический Polza round-trip прошёл на предыдущей ревизии. Точная причина старого 451 всё ещё неизвестна, но активный путь его не использует.

### HIGH — Качество Jev на русском не измерено

- **Где:** `results/jev-live-pilot-20261014T094655Z.json:26-79`; partial-run gate в `run_spike.py:155-164`; наборы A/B/C в `experiments/deep-v1/`.
- **Воспроизведение:** сохранён только один answer row `e01-supply-rail`; runner маркирует partial run без aggregate quality metrics.
- **Ожидалось:** сопоставимые live outputs для утверждённых synthetic gold labels.
- **Фактически:** один ответ наблюдался; accuracy/P/R/F1, calibration/stability и slice metrics не измерены. Latency, token usage и cost имеют только одно case observation.
- **Действие:** после отдельного согласования тарифицируемого бюджета провести небольшой набор и затем независимую blind оценку; не считать это production validation.

### HIGH — Расширенные gold labels и D не дают независимого blind evaluation

- **Где:** `experiments/deep-v1/manifest.json:18-24,56`; `experiments/deep-v1/README.md`.
- **Воспроизведение:** manifest явно указывает single annotator, видимый D и автора, знакомого с его labels.
- **Ожидалось:** независимые gold labels и закрытый контрольный split.
- **Фактически:** labels — draft одного автора, D не blind; B24 имеет неразрешённую annotation ambiguity.
- **Действие:** зафиксировать rubric, получить вторую независимую разметку вслепую, adjudicate disagreements и выпустить новую версию; B24 исключить до этого.

### MEDIUM — Таксономия имеет неоднозначные границы и неполный event coverage

- **Где:** `experiments/deep-v1/TAXONOMY_REVIEW.md:11-44,264+` и `taxonomy.json`.
- **Воспроизведение:** рассмотреть шесть boundary-пар и примеры B; конфликт B24 отмечен в manifest.
- **Ожидалось:** согласованные определения, временная семантика и приоритеты категорий.
- **Фактически:** будущие объявления и `legal_enforcement` требуют уточнения; `other_uncertain` смешивает unknown label/evidence uncertainty; есть кандидаты вне списка.
- **Действие:** отдельное предложение v0.4 и повторное adjudication, не менять v0.3 автоматически.

### MEDIUM — Совместимость с нормативным runtime неполная

- **Где:** `docs/specs/framework-v1/03-operations.md:113-124`; OpenAPI строки 6982–7053; реализация spike `jev_spike.py:219+`.
- **Воспроизведение:** сравнить spike request/result с нормативными DTO.
- **Ожидалось:** `material`, taxonomy ref, allowed codes, multi_label, normative topics/event_hints/status/missing_data и provenance/policy boundaries.
- **Фактически:** отдельный case-based runner с собственной taxonomy и output shape; runtime интеграции нет.
- **Действие:** перед отдельной согласованной интеграцией реализовать адаптер, policy gate до egress и явный DTO mapper; не менять OpenAPI.

## Ограничения и что можно использовать

**Можно использовать сейчас:** offline harness как прототип проверки Polza System One transport/ответов; strict validation; безопасный runner на pinned synthetic baseline после разрешения бюджета; структуру корпуса как основу для независимой разметки; taxonomy review как документ предложений.

**Нельзя использовать сейчас:** Jev как доверенный русский news classifier; один smoke-row как evidence качества; scores как калиброванные вероятности; threshold values как production policy; draft labels как статистически достоверный benchmark; D как blind holdout; output напрямую как Framework DTO; live prompt-injection/privacy claims; любая интеграция в основной runtime без policy/provenance/history/replay review.

## План дальнейших действий

1. Оставить T08 spike изолированным; не менять `main`, OpenAPI, generated contracts или runtime.
2. Не повторять старый direct TypeSafe route и не пытаться выяснять 451 обходом ограничений; проектный live путь через Polza уже дал один валидный round-trip.
3. Отдельно утвердить taxonomy rubric и временные правила; adjudicate B24 и прочие спорные примеры.
4. Получить blind second annotation, пересчитать gold, зафиксировать новую версию корпуса. У D должен быть независимый владелец, который не видел tuning cases.
5. После отдельного одобрения оплачиваемого бюджета выполнить до 10 закреплённых synthetic кейсов через Polza; остановиться при несовпадении schema/error и сохранить `cost_rub`.
6. Реализовать отдельный evaluator для A/B/C с понятным исключением спорных кейсов; D открывать только после фиксации prompt, taxonomy и thresholds.
7. Рассчитать метрики и uncertainty slices; повторить metamorphic pairs несколько раз только с отдельно утверждённым бюджетом. Не обещать стабильность и не подбирать production threshold на D.
8. Лишь после результатов и отдельного согласования предложить runtime adapter к `Understanding.classify` с approved policy/egress, allowed codes, provenance, sanitized history и record/replay. Ни один следующий этап автоматически не запускается.

## Артефакты и источники

- Основной код: [`jev_spike.py`](jev_spike.py), [`run_spike.py`](run_spike.py), [`test_spike.py`](test_spike.py).
- Исходные, не изменённые benchmark и taxonomy: [`corpus.json`](corpus.json), [`taxonomy.json`](taxonomy.json).
- Новый корпус и методика: [`experiments/deep-v1/`](experiments/deep-v1/README.md), [`TAXONOMY_REVIEW.md`](experiments/deep-v1/TAXONOMY_REVIEW.md).
- Нормативный контракт: [`03-operations.md`](../../docs/specs/framework-v1/03-operations.md), [`openapi.json`](../../docs/specs/framework-v1/contracts/openapi.json).
- Официальные источники: [Polza System One API](https://polza.ai/docs/api-reference/systemone/create), [Polza Jev guide](https://polza.ai/jev), [Polza Jev model ID](https://polza.ai/models/typesafe/jev).

---

**Финальный вердикт:** ENGINEERING QUALITY — PASS; API COMPATIBILITY — PASS for the tested Polza request/response path; MODEL QUALITY — NOT MEASURED; INTEGRATION READINESS — NOT READY. **Доверять Jev классификацию русскоязычных бизнес-новостей пока нельзя: качество ещё не доказано.**
