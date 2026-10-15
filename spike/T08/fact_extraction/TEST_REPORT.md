# T08 → DeepSeek → T09: итог технической проверки

Дата: 2026-10-15. Статус: **offline prototype verified; live pilot attempted but provider timed out; T09 runtime integration unavailable**.

## Live pilot: результат

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
- Но журнал DeepSeek от 2026-09-10 сообщает, что старый V4 Flash снят с
  обслуживания, а его прежний alias временно маршрутизируется на V4.1 Flash.
  Код сохраняет требуемый ID и не переключается на другой. Фактический
  checkpoint за Polza alias не подтверждён.
- Источники: [Polza model listing](https://polza.ai/models/deepseek/deepseek-v4-flash),
  [Polza DeepSeek API instructions](https://polza.ai/providers/deepseek),
  [DeepSeek release log](https://api-docs.deepseek.com/updates/?release=deepseek-coder).

**Live API: FAILED WITH TIMEOUT.** Один реальный POST был предпринят к
закреплённому endpoint/model ID; провайдер не вернул HTTP-ответ за отведённое
время. Модель не выдала проверяемого результата. Provider token usage, сумма
списания, точный checkpoint за alias и качество русского извлечения не измерены.
Реальная интеграция и качество DeepSeek остаются **не подтверждены**.

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
- Нельзя заявлять, что API работает или что DeepSeek V4 Flash действительно
  ответил: live запрос запрещён без отдельного согласия и checkpoint alias
  неоднозначен.
- Нельзя объявлять точность/качество извлечения проверенными. Для этого нужны
  разрешённый минимальный live pilot, human-reviewed extraction labels и
  подтверждение Polza по фактическому checkpoint.

Итог: **офлайн-прототип и безопасный контрактный адаптер прошли проверки.
Live-пилот заблокирован таймаутом провайдера; перед новым платным запуском
нужно проверить состояние запроса/расходов в кабинете Polza и устранить причину
сетевой недоступности. Runtime T09 integration по-прежнему не проверялась.**
