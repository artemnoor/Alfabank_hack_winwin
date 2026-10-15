# T08 — итоговый технический и экспериментальный отчёт

**Срез:** 2026-10-14. Работа выполнена только в spike/T08, ветка codex/spike-t08-jev-news-classification. Runtime/OpenAPI не изменялись. Этот итоговый срез заменяет прежний отчёт; исходные TEST_REPORT.md и JSON 1.2.0 сохранены копиями в results/archive/.

## Статусы

| Область | Статус | Основание |
|---|---|---|
| Engineering quality | **PASS** | Финальный повтор офлайн-тестов, Ruff, форматирования, offline runner и агрегатора прошёл. |
| API compatibility | **PASS, ограниченная область** | 44 staged ответа Polza и один исторический smoke подтверждают endpoint/request-response path. После live-прогона добавлена проверка официальной Choice confidence формулы; все 45 сохранённых ответов повторно прошли её офлайн. Текущая ревизия клиента не вызывала сеть. |
| Model quality | **NOT MEASURED для принятия решения** | Есть частичные описательные метрики на 45/49 ответах и черновых single-author labels; этого недостаточно для доверия. |
| Integration readiness | **NOT READY** | Это изолированный spike без нормативного DTO adapter, runtime policy, provenance, history и replay интеграции. |

**Рекомендация:** не доверять Jev автоматическую классификацию русскоязычных бизнес-новостей. Пока допустим только изолированный исследовательский прототип с обязательной ручной проверкой.

## Объём и входные данные

Проверены jev_spike.py, run_spike.py, aggregate_pilot.py, live_ledger.py, transport, response validation, thresholds, metrics, corpus, taxonomy, security и соответствие Understanding.classify.

- Исходный корпус: 50 строк, 49 непустых новостей и один локально отклоняемый пустой кейс. SHA-256: 592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d.
- Taxonomy 0.3.0-spike: 11 Choice вариантов, 15 event types. SHA-256: 855a61f9b6c199d8440b8b81bbd09234e376896121ed163af2ed7f0c1455d.
- Deep corpus: 160 синтетических примеров (A=76, B=36, C=24, D=24; 158 непустых). Jev на нём не запускался. Gold labels односторонние; B24 спорный; D видим и не является blind holdout. Хэши находятся в experiments/deep-v1/manifest.json.
- Исходные corpus.json и taxonomy.json не изменялись. Разметка и результаты Jev не смешивались.
- Используется один native Choice для темы и 17 независимых native Noul вопросов (15 событий + unlisted + insufficient evidence). Другие классификаторы не подключались.

Текущие команды проверки:

    python -m unittest discover -s spike/T08 -p "test*.py" -v
    ruff check spike/T08
    ruff format --check spike/T08
    python spike/T08/run_spike.py

Агрегат v4 заново построен из исторического smoke и восьми staged JSON в results/jev-live-aggregate-20261014-v4.json; его валидатор проверяет формулу Choice confidence у каждого сохранённого результата. Предыдущие агрегаты и result artifacts не перезаписывались. Во время этой corrective pass новых live запросов не было.

## Официальный API и HTTP 451

По официальным материалам Polza проверен endpoint POST https://polza.ai/api/v1/systemone, Bearer auth через POLZA_AI_API_KEY, поля state/model/questions и optional provider. Jev guide указывает model ID typesafe/jev. Документация указывает до 255 Choice options и 1–256 вопросов; spike отправляет 11 options и 18 questions. Проверяются resolved Jev version, структура Choice/Noul answers и usage поля input_tokens/output_tokens/cost_rub. Официальная документация TypeSafe задаёт для Choice формулу `(p_max - 1/n) / (1 - 1/n)`. Валидация применяет допуск 0,02 к сохранённым значениям с округлением: среди 45 сохранённых ответов максимальное наблюдаемое расхождение — 0,005. Оценки Noul не считаются калиброванными вероятностями именно для нашего корпуса.

- Путь Polza реально дал 44 staged schema-valid ответа и один более ранний pinned smoke. Успешные ответы указывают Jev 1.13.0.
- SHA клиента в staged artifacts: c37a15f076baf791b1683d1c1c0555b7aedd8bdbbf75cb6ab41b6f15b40fa791. Текущая ревизия `jev_spike.py` отличается: после live-прогона добавлена сверка confidence с официальной формулой. Запросы не менялись: все 49 current baseline request hashes совпадают с зафиксированным aggregate. Новая валидация офлайн пропущена по всем 45 сохранённым ответам; повторных live вызовов не было.
- Current `jev_spike.py` SHA-256: `47505feb083e6c34f1e3621b67cbf8e8ca2425c288cf3f83589e4f9f5444fb82`.
- Runner SHA staged запусков: 8bd0851f7f18f9da323d647697ffa60aac50a052b0b34e19f8e5c98437520754; текущий run_spike.py: 3134f30321a28a9b71612f1c86afb2226f4dcec1f8728bc3a8ed68001e120120. Поэтому финальные runner/ledger изменения проверены офлайн, а не повторным live запуском.
- provider.allow_fallbacks=false указан, однако ответ не подписан Polza и фактический upstream/fallback не attested.
- API key проверялся только на наличие. Значение не показывалось и не сохранялось.

Старые GET /v1/models и два POST на api.typesafe.ai с taxonomy 0.1/0.2 получили HTTP 451. Raw body/request id нет; точный источник и причина 451 неизвестны. Это не проверка Polza. Ещё одна старая TypeSafe попытка с taxonomy 0.3 записана как sanitized_request_error, причина тоже неизвестна. VPN, proxy, альтернативные host и обход ограничений не использовались.

## Live-пилот и бюджет

Срез пилота: 50 попыток, 45 валидных ответов, 5 ошибок. Счёт включает один исторический успешный Polza smoke, 48 staged Polza попыток и отдельный неуспешный legacy TypeSafe POST. В staged партии 44 ответа и 4 sanitized_request_error: e23-recall-battery, e35-multi-labor-investment, e41-uncertain-sanctions-talk, e43-uncertain-vague-delivery. Ошибки не повторялись; причины неизвестны, и они не превращались в false negatives. Они могут создавать selection bias.

Три прежних HTTP 451 route-check запроса (GET models и два POST с taxonomy 0.1/0.2) находятся вне пилотного ledger. Поэтому известный исторический след проекта — 53 API-вызова, если учитывать их вместе с 50 попытками пилота. Это превышает лимит 50, если он распространяется на весь T08, а не только на отдельный пилот; это расхождение нельзя исправить задним числом. Новых запросов при этой проверке не было и дальнейшие live-вызовы остаются запрещёнными без нового бюджета. Локальный ledger reconciled к 50 попыткам пилота и блокирует добавление к нему; его можно изменить или удалить, он не является tamper-proof ограничителем.

### Частичные описательные результаты Jev

Метрики ниже рассчитаны по 45 успешным ответам из 49 непустых исходных кейсов против односторонней draft разметки. Они не являются независимой оценкой модели.

| Метрика | Значение |
|---|---:|
| Покрытие | 45/49 = 91,84% |
| Accuracy главной темы | 31/45 = 68,89% |
| Event micro precision / recall / F1 | 0,850 / 0,829 / 0,840 |
| Event macro F1 | 0,808; 15 классов, малые поддержки |
| Multi-label exact match | 34/45 = 75,56% |
| uncertain/review | 42/45 = 93,33% |
| Unlisted event | recall 0/1; единственный gold случай не распознан |
| insufficient-evidence signal | precision 0,235; recall 1,0 при 4 gold positives |

Per-event результаты:

| Event | P | R | F1 | Support |
|---|---:|---:|---:|---:|
| supply_chain_disruption | 1,000 | 1,000 | 1,000 | 5 |
| shortage_capacity_constraint | 1,000 | 0,333 | 0,500 | 3 |
| production_operational_disruption | 0,667 | 1,000 | 0,800 | 4 |
| price_cost_change | 1,000 | 1,000 | 1,000 | 3 |
| trade_restriction | 1,000 | 1,000 | 1,000 | 3 |
| sanctions | 0,750 | 1,000 | 0,857 | 3 |
| regulation_tax_change | 0,500 | 1,000 | 0,667 | 2 |
| cyber_security_incident | 1,000 | 1,000 | 1,000 | 2 |
| labor_workforce_event | 1,000 | 1,000 | 1,000 | 2 |
| insolvency_default | 1,000 | 1,000 | 1,000 | 3 |
| corporate_transaction_restructuring | 1,000 | 0,667 | 0,800 | 3 |
| product_recall_quality_safety | 1,000 | 1,000 | 1,000 | 1 |
| legal_enforcement | — | 0,000 | 0,000 | 3 |
| environment_disaster_impact | 0,500 | 0,500 | 0,500 | 2 |
| investment_capacity_change | 1,000 | 1,000 | 1,000 | 2 |

Высокие значения на категориях с support 1–5 не означают стабильную точность. legal_enforcement не был предсказан ни разу, поэтому precision не определён.

14 ошибок Choice: e06 industry_trade_supply→business_companies; e07 economy_finance→business_companies; e09 politics_government→industry_trade_supply; e10 law_regulation→industry_trade_supply; e12 politics_government→law_regulation; e14 economy_finance→law_regulation; e18 business_companies→labor_employment; e24 health→law_regulation; e28 energy_resources→environment_disasters; e29 industry_trade_supply→business_companies; e33 economy_finance→industry_trade_supply; e42 economy_finance→energy_resources; e45 industry_trade_supply→business_companies; e47 business_companies→politics_government.

По событиям: 34 TP, 6 FP и 7 FN при текущем пороге. FP: production_operational_disruption на e03/e27; sanctions на e25; regulation_tax_change на e09/e10; environment_disaster_impact на e32. FN: shortage_capacity_constraint на e03/e33; corporate_transaction_restructuring на e18; legal_enforcement на e25/e26/e34; environment_disaster_impact на e28.

Срезы: одиночные события n=25 — topic accuracy 0,680, event micro-F1 0,863, exact set 0,800; multi-event n=8 — 0,625/0,800/0,250; no-listed-event n=5 — topic accuracy/exact set 1,0; negation/rumor n=2 — topic accuracy 0,5; ambiguous/speculative n=3 — topic accuracy 0,667. Размеры слишком малы для обобщения.

Latency успешных ответов n=45: mean 1298,58 ms, median 860 ms, nearest-rank p95 1313 ms. P95 неустойчив на такой выборке. Успешные usage: 263 276 input + 22 167 output = 285 443 tokens. Сумма cost_rub по успешным ответам — 4,63313107 ₽. Стоимость пяти ошибок неизвестна и могла быть списана; эта сумма не является гарантированными общими расходами.

## Threshold sweep и стабильность

При фиксированном event negative cutoff 0,2:

| Positive cutoff | Precision | Recall | F1 | review cells |
|---:|---:|---:|---:|---:|
| 0,3 | 0,574 | 0,951 | 0,716 | 15 |
| 0,4 | 0,661 | 0,951 | 0,780 | 24 |
| 0,5 | 0,696 | 0,951 | 0,804 | 27 |
| 0,6 | 0,717 | 0,927 | 0,809 | 30 |
| 0,7 | 0,766 | 0,878 | 0,818 | 36 |
| 0,8 | 0,850 | 0,829 | 0,840 | 43 |
| 0,9 | 0,939 | 0,756 | 0,838 | 50 |

Choice cutoff 0,5 отправил бы в review 5/45 тем (11,1%), accuracy среди auto-кейсов 0,75; cutoff 0,7 — 14/45 review и auto accuracy 0,839. Combined runtime status отправил в review 42/45 из-за Noul uncertainty, unlisted и границ. Это описательная чувствительность порогов на малой неполной выборке, не production calibration. D не использовался для tuning.

Live stability не проверялась: нет повторов и metamorphic live запросов. C split проверяет только заданные авторами gold relationships офлайн. e45 — одиночное наблюдение, не доказательство устойчивости к prompt injection. Provider-side поведение не измерено.

## Таксономия, gold и независимый аудит

Taxonomy v0.3 не менялась. Подробный разбор каждой темы и события с положительными/отрицательными примерами, пограничными случаями и отдельными v0.4 предложениями находится в experiments/deep-v1/TAXONOMY_REVIEW.md.

Независимые reviewers разошлись по e33: спорно, подтверждает ли текст `shortage_capacity_constraint` помимо `price_cost_change`. Отдельные event-label границы есть у e34 (`legal_enforcement`) и e35 (`labor_workforce_event`); тему требуют adjudicate e10, e14, e18, e28, e30 и e45. Пары e09/e10 и e13/e14 оставлены как contrasts; в подтверждённом reviewer-проходе неоднозначны e10 и e14. e28 также может допускать `regulation_tax_change`. Gold не меняли. Отдельный sensitivity пересчёт по альтернативной метке e33 меняет event micro-F1 примерно 0,840→0,850; это модельная метрика, вынесенная сюда отдельно, и не была использована в model-blind label review. Требуется human adjudication с evidence spans до новых quality claims. Детали — experiments/2026-10-14-independent-review.md.

Для отдельного обсуждения следующей версии не хватает fraud/corruption, крупного contract/order award/loss и partnership/JV. Это не автоматическое изменение taxonomy и не утверждение о распространённости реальных событий. IPTC/GDELT/Event Registry/RavenPack использованы только как справочные ориентиры, ни один из них не запускается классификатором.

## Финальный офлайн-прогон

| Проверка | Результат |
|---|---|
| unittest discover spike/T08 | **86 passed, 0 failed, 0 skipped** |
| ruff check spike/T08 | **PASS** |
| ruff format --check spike/T08 | **PASS**, 16 Python files |
| python spike/T08/run_spike.py | **PASS**, 0 classifier calls, 49 non-empty + local empty validation |
| git diff --check | **PASS** |
| aggregate v4 | **PASS**, 45 validated results, 50 pilot attempts; output matches v3 metrics |
| Choice formula audit | **PASS**, 45/45 сохранённых ответов согласуются с официальной формулой в допуске; max observed delta 0,005 |

Офлайн suite покрывает Choice/Noul schema and range validation, missing/extra/malformed ответы, Unicode/size input checks, thresholds/metrics, timeout/reset/HTTP statuses, no retry, redirects, proxy/host controls, canary/error sanitization, fixed corpus/taxonomy hashes, request allowlist и отсутствие сетевого fallback. Новый test делает 24 параллельных локальных ledger reservation и проверяет уникальную последовательную нумерацию. Offline socket guard блокирует стандартные Python socket entrypoints процесса, но не заменяет OS/container egress firewall.

## Безопасность

- Только фиксированный HTTPS Polza endpoint, redirects запрещены, proxy discovery от окружения отключён.
- Live cases требуют точные pinned synthetic request hashes; пустые/изменённые/неутверждённые тексты отклоняются до отправки. Автоматических retries нет.
- HTTP error body, произвольная provider metadata и raw exception text отбрасываются; в файл не попадают article text, prompts, credentials или raw response.
- API key не выводился/не сохранялся. Изученные live artifacts не содержат payload.
- provider.allow_fallbacks=false задан, но upstream не подтверждён подписью.
- Ledger предотвращает случайные повторы в текущем окружении, но пользователь может удалить/изменить файл или сменить LOCALAPPDATA/XDG_STATE_HOME. Это best-effort guard, не security boundary.

## Совместимость с Framework v1

Нормативный ориентир — Understanding.classify в docs/specs/framework-v1/03-operations.md и OpenAPI ClassificationInput/ClassificationOutput.

| Компонент | Статус | Минимальное требование к будущему adapter |
|---|---|---|
| Jev — единственный классификатор | Частично | В runtime вызывать только через разрешённый dependency adapter и policy. |
| Native Choice + independent Noul, конечные коды | Частично | Передавать taxonomy id/version и normative allowed_codes; fail closed на неизвестных кодах. |
| ClassificationInput/material/taxonomy/allowed_codes/multi_label | Не совместимо | Проверенный маппер DTO → Jev request без смены OpenAPI. |
| ClassificationOutput/topics/event_hints/status/missing_data | Не совместимо | Маппер output с проверкой каждого normative инварианта. |
| Policy, trusted provenance, history, replay | Не совместимо/не реализовано | Отдельная интеграция через approved runtime boundaries, не внутри spike. |
| Реальные model stability/provider-side injection | Не проверено | Нужен отдельный, разрешённый live протокол. |

Полностью совместимых runtime interfaces нет. Это намеренно изолированный spike; никаких OpenAPI/generated contract изменений.

## Серьёзные находки и действия

| Severity | Файл / строки | Воспроизведение и фактическое поведение | Статус / действие |
|---|---|---|---|
| HIGH | `aggregate_pilot.py:506-515`; regression `test_spike.py:936-990` | Aggregate custom transport раньше выдавал mock метрики как результаты Jev. | Исправлено: custom transport → `NOT_MEASURED_CUSTOM_TRANSPORT`, metrics=null; regression test есть. |
| HIGH | `live_ledger.py:81-112`; regression `test_spike.py:298-345` | Чистый ledger seed раньше не отражал все 50 попыток пилота. | Исправлено: 49 baseline hashes + legacy TypeSafe POST; seed закрыт. Локальную запись можно изменить или удалить. |
| MEDIUM | `aggregate_pilot.py:523`; regression `test_spike.py:964-979` | Source metadata могла перезаписать aggregate mode. | Исправлено: v4 сохраняет `live_synthetic_pilot_aggregate`. |
| MEDIUM | `aggregate_pilot.py:554-566` | Успешная стоимость могла выглядеть как сумма всех попыток. | Исправлено: known successful response cost отделена от неизвестной возможной оплаты неуспешных запросов. |
| HIGH | `jev_spike.py:315-328,372-373`; `aggregate_pilot.py:194-195`; regressions `test_spike.py:433-463,1094-1110` | `confidence=0.47` при one-hot probabilities раньше принимался. | Исправлено: проверяется официальная формула и округлительный допуск; 45 сохранённых ответов прошли перепроверку. |
| HIGH, открыт | `results/jev-live-aggregate-20261014-v4.json:24-53` | Четыре staged Polza call содержат только `sanitized_request_error`; причина неизвестна. | Не повторять без нового разрешённого бюджета; пропуски не считать ошибками модели. |
| HIGH, открыт | `experiments/2026-10-14-independent-review.md:15-54` | Gold e33/e34/e35 и topic boundaries требуют adjudication; разметка односторонняя. | Исправлена категоризация замечаний; taxonomy/corpus/gold оставлены как есть. Требуется human adjudication. |
| HIGH, открыт | `results/jev-live-aggregate-20261014-v4.json:2643-2648,3523-3552` | 45/49 outputs, 42/45 review, малые поддержки и single-author labels. | Качество не доказано; не подключать к runtime. |
| HIGH, открытый учёт | `results/route-check.json:1-14`; `TEST_REPORT.md:48-52` | 50 пилотных попыток + 3 ранних route-check = 53 известных вызова, если один общий бюджет. | Дальше не вызывать без отдельного разрешения; исторический превышающий лимит счёт открыт и указан явно. |
| MEDIUM, ограничение | `jev_spike.py:315-328`; `run_spike.py:160-228`; `TEST_REPORT.md:39-43` | Клиент и runner изменились после live-партии; полная текущая ревизия не вызывала сеть. | Все request hashes совпадают, 45 ответов перепроверены офлайн; повтор live запрещён до нового бюджета. |
| MEDIUM, открыт | `results/route-check.json:1-14` | Для прежних TypeSafe HTTP 451 нет raw body/request id. | Причина неизвестна; не спекулировать и не обходить ограничения. |

## Независимое ревью и решение

API reviewer подтвердил исторический Polza request/response path, отметил четыре неизвестных отказа, несовпадение client/runner revisions, не-attested upstream и cost только по успешным ответам. После проверки замечания добавлена regression validation Choice confidence. Security reviewer нашёл недосчёт ledger, mock-metrics и ошибочный mode; они закрыты с тестами. Модель-слепой label review не использовал Jev outputs и оставил e33/e34/e35 boundary вопросы открытыми. Архитектурное ревью подтвердило отсутствие runtime/OpenAPI изменений. Ревью не заменяет live-проверку текущей ревизии и не доказывает качество.

**Что пригодно:** исследовательский Polza/JeV client, строгая JSON валидация, immutable baseline для дальнейшей человеческой adjudication, предварительные описательные цифры.

**Что не пригодно:** автоматическая production-разметка, production thresholds, обещание стабильности, вывод о причине HTTP 451, или заявления о подтверждённом upstream/fallback.

**Нужно перед интеграцией:** adjudicate labels независимыми annotators; собрать новую versioned gold set с blind control; согласовать отдельный live budget/protocol; реализовать DTO adapter и policy/provenance/history/replay checks без изменения утверждённого OpenAPI.

**Можно ли уже доверить Jev классификацию русскоязычных бизнес-новостей? Нет.** API path технически работал, однако надёжность качества не доказана. Частичные метрики на малом synthetic наборе и высокая доля review не меняют этот вывод.

## Источники

- Polza System One: https://polza.ai/docs/api-reference/systemone/create
- Polza Jev guide (endpoint, Bearer auth, request/response examples): https://polza.ai/docs/gaidy/jev
- Jev guide: https://polza.ai/jev
- Jev model page: https://polza.ai/models/typesafe/jev
- TypeSafe official Choice confidence formula: https://docs.typesafe.ai/confidence
- Machine report: TEST_REPORT.json
- Final aggregate: results/jev-live-aggregate-20261014-v4.json
- Taxonomy audit: experiments/deep-v1/TAXONOMY_REVIEW.md
- Independent label audit: experiments/2026-10-14-independent-review.md
- Preserved previous report: results/archive/TEST_REPORT-pre-pilot-final.md
