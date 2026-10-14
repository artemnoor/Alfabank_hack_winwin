# T08 Jev classification spike — итоговый технический и экспериментальный отчёт

**Дата аудита:** 2026-10-14

**Ветка:** `codex/spike-t08-jev-news-classification`

**Базовый `main`, проверенный для spike:** `ce640214be7c5ff2fdb451b9e290135a11b512a6`

**Текущий HEAD:** см. head текущего PR #8; отчёт не записывает SHA собственного commit, чтобы не создавать самоссылку.
**Область:** только `spike/T08/`; production runtime, OpenAPI и generated contracts не изменялись.

## Краткое резюме

Реализация стала существенно строже: запрос соответствует опубликованной форме TypeSafe System One, использует нативные `Choice`/`Noul`, проверяет ответ и метаданные usage, ограничивает размер и время запроса, запрещает redirect, proxy discovery, повторную отправку одного запроса и обращения к неразрешённым данным. Новые offline-проверки покрывают ошибки транспорта, повреждённые ответы, пороги, метрики, хеши и структуру расширенного набора. Все 66 тестов прошли.

Это подтверждает качество локального harness, но **не качество Jev**. В сохранённых исторических попытках три обращения (один `GET /v1/models` и два одиночных synthetic `POST`) получили HTTP 451. Причина 451 не установлена. В этом аудите выполнено **0 live-запросов**. Нет успешного ответа модели, поэтому точность, precision/recall/F1, latency, token usage, стабильность, калибровка и стоимость реального пилота — **NOT MEASURED**.

Текущий corpus расширен до 160 synthetic кейсов (158 непустых), но gold labels — черновая разметка одного автора, а отдельный split D видим в репозитории и не является blind holdout. Один кейс B24 конфликтует с формулировкой категории и должен быть исключён из оценки до adjudication. Новый корпус пока проверяется на структуру и ожидаемые отношения; Jev его не классифицировал.

**Можно ли уже доверить Jev классификацию русскоязычных бизнес-новостей? Нет. Качество ещё не доказано.** Jev остаётся единственным предусмотренным классификатором; альтернативы не подключались. Рекомендация — оставить spike изолированным, запросить у TypeSafe/владельца аккаунта разбор 451, затем отдельным разрешённым малым synthetic-пилотом получить успешный ответ. До этого нельзя заявлять API compatibility или model quality PASS и нельзя интегрировать его в runtime.

## Четыре независимых заключения

| Область | Статус | Основание |
|---|---|---|
| **ENGINEERING QUALITY** | **PASS** | 66/66 offline tests, Ruff check/format, baseline offline runner и `git diff --check` прошли. Это оценка инженерного spike и тестового harness, не модели. |
| **API COMPATIBILITY** | **BLOCKED** | Request/response форма согласуется с опубликованной документацией TypeSafe, но endpoint не дал ни одного успешного ответа; три исторические попытки завершились 451. |
| **MODEL QUALITY** | **NOT MEASURED** | Нет результатов Jev, live latency или usage; все качество-метрики отсутствуют, а не равны нулю. |
| **INTEGRATION READINESS** | **NOT READY** | Нет измеренного качества и успешного API пилота; output spike не реализует полный нормативный DTO, provenance, policy, history или replay. |

## Что проверялось и как

Проведены независимые проверки реализации API, архитектуры/безопасности, таксономии и корпуса. Ревью опирались на код, нормативный документ `Understanding.classify`, официальный сайт TypeSafe и содержимое файлов, а не на заявления README. Структура API сверялась с [TypeSafe API](https://docs.typesafe.ai/api), [Models](https://docs.typesafe.ai/models), [Choice](https://docs.typesafe.ai/primitives/choice), [Noul](https://docs.typesafe.ai/primitives/noul) и [Confidence](https://docs.typesafe.ai/confidence). Также проверялись нормативные `docs/specs/framework-v1/03-operations.md` §05 и `docs/specs/framework-v1/contracts/openapi.json` `#/components/schemas/ClassificationInput` и `ClassificationOutput`.

Live-запросы не выполнялись: сохранённые 451 уже показывают отказ доступа, а повторные попытки или обход ограничений запрещены условиями аудита. Не читались и не печатались значения ключей. В сеть не отправлялись реальные новости. Расширенные синтетические корпуса не отправлялись.

### Последний воспроизводимый прогон

| Команда | Результат |
|---|---|
| `python -m unittest discover -s spike/T08 -p "test*.py" -v` | **66 passed, 0 failed, 0 skipped**, 0.393 s |
| `ruff check spike/T08` | Passed |
| `ruff format --check spike/T08` | Passed, 10 Python files already formatted |
| `python spike/T08/run_spike.py` | Passed; offline validation, 0 classifier calls, baseline 49 nonempty + 1 locally rejected empty input |
| `git diff --check` | Passed |

Live API, full Jev evaluation, latency/cost, provider-side prompt-injection and Russian-language quality были пропущены как недоступные/неразрешённые; они **не засчитываются** как pass. Offline suite запрещает обычные Python socket entrypoints во время тестов и проверяет сам guard. Это process-level защита теста, не OS/container firewall против произвольного native-кода.

Тесты используют контролируемые fake responses только для проверки валидации, транспорта и арифметики. Такие значения не включались в model-quality отчёт. Во время разработки одна ошибка в тестовом fixture была исправлена; приведённый выше результат относится к новому полному прогону после исправлений.

## Проверка официального Jev API

По актуальным на дату аудита официальным документам:

- System One: `POST https://api.typesafe.ai/v1/systemone`.
- Авторизация: `Authorization: Bearer <API_KEY>`; опубликованные примеры используют `TYPESAFE_API_KEY`.
- Запрос содержит top-level `state`, `model`, `questions`; прототип передаёт текст новости как данные в `state`, одну native `Choice` и 17 отдельных native `Noul` вопросов.
- `Choice` принимает именованные критерии/варианты, имеет лимит до 255 options и возвращает выбор, оценки вариантов и confidence.
- `Noul` возвращает yes-score в диапазоне `[0,1]`; официальная документация не описывает его как отдельно откалиброванную вероятность.
- По опубликованной справке confidence `Choice` вычисляется как `(pmax - 1/n) / (1 - 1/n)`. Прототип проверяет эту зависимость с малым допуском на округление опубликованного примера.
- Ожидаются `answers` и `usage.input_tokens`/`output_tokens`; прототип требует оба поля usage и проверяет целые неотрицательные значения.
- `jev-latest` на дату проверки документирован как alias версии `jev-1.13.0`. Изменение alias может менять модель; отчёты должны сохранять фактически возвращённую версию.
- Проверенные docs не задают общего лимита числа вопросов для System One. Ограничение 20 вопросов в прототипе — локальный spike budget guard, не официальное ограничение. Текущая конфигурация — 18 вопросов. Нет оснований приписывать TypeSafe лимит 18 или 20.
- Документация указывает, что английский — наиболее сильный язык Jev, остальные языки следует проверить. Это не доказывает и не опровергает пригодность русского.

**Вывод:** подготовленная форма запроса и ожидаемые поля ответа документально правдоподобны и покрыты regression tests. Но фактическая совместимость с живым API **не подтверждена успешным round-trip**. Неизвестны реальный ответ конкретной версии модели и доступность аккаунта.

## HTTP 451: известные факты и неизвестное

Сохранённые артефакты (`spike/T08/results/route-check.json:8`, `jev-live-pilot-20261014T080227Z.json:18`, `jev-live-pilot-20261014T080859Z.json:18`) подтверждают:

1. Одна аутентифицированная discovery-попытка `GET /v1/models` завершилась 451.
2. По одному одиночному synthetic POST на `/v1/systemone` для taxonomy 0.1 и 0.2 завершились 451.
3. Текущая taxonomy 0.3, расширенный corpus, реальные новости и batch не отправлялись.
4. Raw body и request ID не сохранены. Ни один ответ Jev не получен.
5. Проверенная таблица ошибок TypeSafe документирует стандартные ответы вроде 401/422/429/529, но не объясняет 451. Поэтому точная причина и источник статуса не установлены.

Подтверждён только факт HTTP 451 на тех попытках. **Не подтверждено**, пришёл ли статус от TypeSafe или посредника; связан ли он с ключом, аккаунтом, сетью, регионом, юридическим ограничением или инфраструктурой. Нельзя считать ключ проверенным или считать Jev протестированным. Не следует повторять запросы или менять сетевой маршрут для обхода статуса.

Для выяснения владелец аккаунта должен передать TypeSafe/официальной поддержке UTC timestamps и безопасные метаданные уже сохранённых попыток и запросить причину/корреляцию; секретный ключ отправлять в обращении не нужно. Если причина требует исправления аккаунта/доступа, выполнить его штатным способом. После подтверждения разрешённого доступа запросить отдельный бюджет на один synthetic smoke call; при успехе — до 10 synthetic запросов и только затем решить, разрешён ли пилот из исходных 49. Никакого автоматического retry.

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

**Все метрики Jev — NOT MEASURED.** Per-topic accuracy/confusion matrix; per-event precision/recall/F1, micro/macro F1; exact multi-label match; false positives/negatives; неопределённость/review доля; out-of-list и неподтверждённые сообщения; результаты по single/multi-event, negation, слухам и границам; latency mean/median/P95; usage; cost; calibration — отсутствуют, потому что успешного ответа модели нет. Их не заменяют offline fixtures, ручные support counts, веса/ответы других моделей или вымышленные scores.

Код evaluator реализует эти срезы и threshold sweeps, включая Choice selective accuracy/coverage; корректность математики проверена на синтетически контролируемых fixtures. Это проверка evaluator, не оценка Jev. Пороги Choice `<0.5`, Noul `<=0.2`/`>=0.8` — текущие экспериментальные правила без эмпирического обоснования. Sweep проверен математически, но его живые precision/recall, review burden и пропуски событий не измерены. Noul scores и Choice confidence нельзя объявлять откалиброванными вероятностями качества на русских новостях без отдельной calibration study.

TypeSafe models docs на дату аудита указывают опубликованную цену input `$0.042 / 1M tokens`, output в таблице указан бесплатно. Это справочная тарифная информация, **не стоимость эксперимента**: запросов, полученного usage и live расхода в этом аудите нет; тариф и billing нужно перепроверить перед будущим разрешённым пилотом.

## Offline проверки, ошибки и безопасность

Текущие tests проверяют:

- Типы и размер входа (10 000 символов), пустые данные, Unicode/строки, отсутствие отправки gold metadata и лишних полей.
- Native Choice/Noul форму, опции Choice, допустимые коды, совпадение выбора с максимальной оценкой, формулу confidence и округление, NaN/Infinity, отрицательные/выше единицы оценки, некорректные/пропущенные/лишние ответы и usage.
- HTTP 400/401/403/429/451/500/502/503/529, timeout, connection reset, повреждённый/не-JSON ответ, тело больше лимита, redirect, запрещённый host, отказ от env proxy, отсутствие retry, sanitized ошибки.
- Allowlist канонического request hash, разовый live-send на один одобренный request, отсутствие ключа в выдаче тестов, локальный отсев неразрешённого текста.
- Пустые/дублирующиеся/неизвестные result IDs, отсутствующие телеметрические поля, вычисление метрик/threshold sweep на fixtures.
- Пины исходных taxonomy/corpus, pины manifest и A/B/C/D split hashes, label codes/status, 15 категорий, boundary counts и объявленные связи C.

В транспорт добавлены фиксированный официальный HTTPS endpoint, Bearer auth, стандартный TLS context, redirect refusal, proxy-discovery off, bounded timeout/response body и sanitized exceptions. Клиент требует непустой allowlist request hash, не отправляет один hash дважды и не ретраит. Live runner ограничен закреплёнными 49 исходными synthetic новостями; расширенный корпус live allowlist не получает.

Security caveats:

- Socket guard — стандартные Python entrypoints; это не защита от произвольного native socket code или отдельный сетевой sandbox.
- Prompt injection проверен offline только на неизменность фиксированных критериев/категорий в request. Фактическая реакция Jev на инъекцию, правила provider isolation и утечка через реальную модель не измерялись.
- Canary на секреты/текст проверяется на fake transport/errors; реальный провайдерный ответ отсутствует. Live утечки в provider logs не исследованы.
- Live request неизбежно передаёт текст провайдеру. В этом аудите отправлялись бы только заранее утверждённые synthetic cases; никаких текстов или raw prompts не записывали.
- Исторические ошибки хранят только HTTP status и безопасные метаданные; response bodies/raw prompts/keys отсутствуют.
- Бounded response защищает чтение тела; текст ограничивается по символам, а не по токенам. Точные ограничения API по tokens/числу вопросов в docs не найдены.

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
| Работающий API round-trip, provider compatibility | Не проверено | 451 для всех сохранённых попыток; нет успешного ответа. |

**Ни одна полная end-to-end runtime совместимость не подтверждена.** Spike нельзя регистрировать как implementation `Understanding.classify`.

## Независимое ревью

- **API/реализация:** сверены схема запроса, авторизация, alias модели, primitives и ответы с официальной документацией; выявленные неполные проверки usage/confidence и путаница локального вопросного предохранителя с лимитом провайдера отражены в строгих проверках/документации.
- **Таксономия/данные:** проверены все темы, события, шесть заданных границ, примеры и статус gold labels. Серьёзное ограничение — однопользовательская draft annotation и неслепой D; B24 отложен.
- **Архитектура/безопасность:** подтверждено отсутствие связей с production runtime; reviewer попросил проверять единичность timeout/reset попытки и pin всего manifest/общее количество nonempty случаев. Эти регрессии добавлены; финальный suite прошёл.
- **Статистика:** evaluator и пороговая арифметика проверяются на fake fixtures. Это не evidence качества. Deep evaluator/live runner ещё не поддерживают отдельное сравнение A/B/C; D намеренно не используется в scoring.

Ни один reviewer не подтверждал качество живого Jev, поскольку успешных результатов нет. Открытый блокер — API доступ и независимая adjudication набора.

## Основные замечания с воспроизводимостью

### HIGH — HTTP 451 оставляет API доступ и причину неустановленными

- **Где:** `spike/T08/results/route-check.json:8`, два результата POST: строки 18; код запроса/валидации: `jev_spike.py:219-272,313-404,406-434`.
- **Воспроизведение:** только по уже сохранённым артефактам: authenticated discovery и два одиночных synthetic POST записали `http_status_451`; повтор не нужен.
- **Ожидалось:** официальный API возвращает документированный ответ с `answers` и `usage` для одобренного synthetic request.
- **Фактически:** все три исторические попытки вернули 451, body не сохранено; успешного ответа нет.
- **Действие:** получить объяснение у официального провайдера/владельца аккаунта. Не менять endpoint/маршрут и не выводить причину из статуса.

### HIGH — Качество Jev на русском не измерено

- **Где:** отчёты 451 выше; наборы A/B/C в `experiments/deep-v1/`.
- **Воспроизведение:** в этих артефактах нет model answer rows; текущий runner offline выдаёт `classifier_calls: 0`.
- **Ожидалось:** сопоставимые live outputs для утверждённых synthetic gold labels.
- **Фактически:** оценок Jev нет; все accuracy/P/R/F1, latency, usage, стоимость, стабильность и calibration `NOT MEASURED`.
- **Действие:** после подтверждения API доступа и бюджета провести сначала один запрос, затем разрешённые 10; не считать это production validation.

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

**Можно использовать сейчас:** offline harness как прототип проверки TypeSafe transport/ответов; strict validation; безопасный одиночный runner на pinned synthetic baseline после разрешения API; структуру корпуса как основу для независимой разметки; taxonomy review как документ предложений.

**Нельзя использовать сейчас:** Jev как доверенный русский news classifier; scores как калиброванные вероятности; threshold values как production policy; draft labels как статистически достоверный benchmark; D как blind holdout; output напрямую как Framework DTO; endpoint как доказанно доступный/совместимый; live prompt-injection/privacy claims; любая интеграция в основной runtime без policy/provenance/history/replay review.

## План дальнейших действий

1. Оставить T08 spike изолированным; не менять `main`, OpenAPI, generated contracts или runtime.
2. Через официальный канал выяснить источник HTTP 451 и проверить аккаунт/доступ; не передавать ключ и не обходить географические/юридические ограничения.
3. Отдельно утвердить taxonomy rubric и временные правила; adjudicate B24 и прочие спорные примеры.
4. Получить blind second annotation, пересчитать gold, зафиксировать новую версию корпуса. У D должен быть независимый владелец, который не видел tuning cases.
5. После явного разрешения на бюджет выполнить один synthetic smoke запрос к официальному endpoint. Если он успешен и данные корректны — небольшой пилот до 10 кейсов; остановиться при несовпадении schema/error.
6. Реализовать отдельный evaluator для A/B/C с понятным исключением спорных кейсов; D открывать только после фиксации prompt, taxonomy и thresholds.
7. Рассчитать метрики и uncertainty slices; повторить metamorphic pairs несколько раз только с отдельно утверждённым бюджетом. Не обещать стабильность и не подбирать production threshold на D.
8. Лишь после результатов и отдельного согласования предложить runtime adapter к `Understanding.classify` с approved policy/egress, allowed codes, provenance, sanitized history и record/replay. Ни один следующий этап автоматически не запускается.

## Артефакты и источники

- Основной код: [`jev_spike.py`](jev_spike.py), [`run_spike.py`](run_spike.py), [`test_spike.py`](test_spike.py).
- Исходные, не изменённые benchmark и taxonomy: [`corpus.json`](corpus.json), [`taxonomy.json`](taxonomy.json).
- Новый корпус и методика: [`experiments/deep-v1/`](experiments/deep-v1/README.md), [`TAXONOMY_REVIEW.md`](experiments/deep-v1/TAXONOMY_REVIEW.md).
- Нормативный контракт: [`03-operations.md`](../../docs/specs/framework-v1/03-operations.md), [`openapi.json`](../../docs/specs/framework-v1/contracts/openapi.json).
- Официальные источники: [API](https://docs.typesafe.ai/api), [Models](https://docs.typesafe.ai/models), [Choice](https://docs.typesafe.ai/primitives/choice), [Noul](https://docs.typesafe.ai/primitives/noul), [Confidence](https://docs.typesafe.ai/confidence), [Parallel questions](https://docs.typesafe.ai/cookbooks/parallel_questions).

---

**Финальный вердикт этого аудита:** инженерная реализация spike — PASS; API compatibility — BLOCKED; качество Jev — NOT MEASURED; интеграция — NOT READY. **Доверять Jev классификацию русскоязычных бизнес-новостей сейчас нельзя: качество ещё не доказано.**
