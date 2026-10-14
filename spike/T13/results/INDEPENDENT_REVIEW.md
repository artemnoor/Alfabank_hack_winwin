# Независимое ревью T13: Matching / Impact / Recommendations

- Проверенная база: `6309956355dd3fa78335474d8e278f56922288e0` (`codex/review-t13-impact`).
- Shared dataset: provisional v1.0.1, canonical hash `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
- Независимый T11 артефакт: worktree `C:\CodexData\worktrees\alfabank-review-t11-evidence`, HEAD `ea5bc15070e9877d21c21c6eaf6ade8ab691d867`, `spike/T11/results/offline-v1.0.1.json`.
- Область: нормативные карточки `Matching.match`, `Impact.assess`, `Recommendations.propose` (`docs/specs/framework-v1/03-operations.md:317-367`); правило `verified_anchor` и явной trusted owner policy (`docs/specs/framework-v1/02-contracts.md:76-82`); реализация, fixtures, offline experiment и тесты T13.
- Режим проверки: read-only review; реализации, общие DTO, датасет и результаты эксперимента не менялись.

## Итог

Есть **2 HIGH** и **4 MEDIUM** замечания. CRITICAL не обнаружено. Локальные тесты и contract suite проходят, но это не закрывает воспроизводимые дефекты provenance/status gates. Интеграционная готовность: **NOT READY** до устранения HIGH замечаний и повторного независимого ревью.

| Severity | Finding |
|---|---|
| HIGH | Подтверждённые Match/C/D расходятся с независимым T11 результатом `not_confirmed`; T13 не получает и не сохраняет policy provenance. |
| HIGH | Impact D проверяет Evidence по `object_id`, игнорирует hash/revision/owner и reliability доказательств графового пути; C принимает claims без цитирования доказательств пути. |
| MEDIUM | Matching выдаёт confirmed для неактуального EventContext. |
| MEDIUM | При несовпадающей версии Business slice ответ теряет объясняющий `missing_data`. |
| MEDIUM | Большая часть 30-case harness использует вручную заданные EventContext/targets, а не соответствующие Events.read records. |
| MEDIUM | ImpactAssessment теряет StatementRef/path lineage в выходной provenance. |

## HIGH-01 — Event status и trusted evidence policy не согласованы

**Доказательства.** В prepared `Events.read` запись `event-export-x-mk7` содержит statement `event-export-claim` со статусом `confirmed` и ссылку на `ev-export-official` (`spike/_shared/fixtures/t09-t13-independent-v1/events-read.json:158-208`). Связанный Evidence имеет `verification=verified_anchor`, `source_reliability=unassessed` (`evidence-read.json:724-740`). Однако независимый результат T11 для `exact-anchor` и `ev-export-official` фиксирует `claim_status=supported_unconfirmed`, `final_status=not_confirmed`, `owner_policy_id=null` (T11 worktree, `spike/T11/results/offline-v1.0.1.json:7-13,50`). Нормативные правила говорят, что anchor подтверждает целостность якоря, не истинность, и что `confirmed` требует разрешающей trusted owner policy (`02-contracts.md:76-82`, `03-operations.md:379`).

**Воспроизведение.** Из фактического Events.read `EventContext.from_record` выводит `factual_status=confirmed`, `current=True`, targets `('component-mk7', 'country-x')`. По сценарию `export-b-direct` получено:

```text
materialized event status/current/targets: confirmed True ('component-mk7', 'country-x')
base match exposure / C / D: confirmed confirmed confirmed
```

`matching/core.py:49-68` выводит status только из `epistemic_status` entity statements. В контексте нет результата T11, owner policy id или иной policy provenance. `matching/core.py:187-188` повышает exposure до confirmed по EventContext status, edge status и graph freshness. D аналогично доверяет `event.factual_status == "confirmed"` (`impact/approach_d.py:38-45,81-96`); C допускает claims при таком статусе (`impact/approach_c.py:141-168`). Получается противоречие между подготовленными операционными результатами: T11 говорит `not_confirmed`, каждый вариант T13 сообщает `confirmed`.

**Риск.** Проверенный anchor/статус DTO превращается в подтверждённую экспозицию без проверяемой связи с разрешающей trust policy. До интеграции нужно согласовать upstream статус с T11/policy и проверять эту согласованность перед тем, как считать воздействие confirmed; иначе результат должен сохранять неопределённость. Общие контракты этим review не менялись.

## HIGH-02 — Evidence path проверяется по ID, а не по точной ссылке и доверию

**Доказательства.** `ImpactContext.evidence_by_id` сводит записи к словарю по одному `record.ref.object_id` (`impact/common.py:64-65`). Approach D проверяет `object_id` и `verified_anchor`, но не равенство полного ObjectRef (owner/revision/hash); `source_reliability` проверяется только для event evidence, не для evidence графовых рёбер (`impact/approach_d.py:41-45,56-79`). Approach C проверяет статус только у явно переданных model-shaped claim refs и не требует включать доказательства фактического пути (`impact/approach_c.py:99-119`). Поэтому проверенный anchor для ID принимается как проверка другой/искажённой ссылки, а path provenance можно опустить в claim.

**Воспроизведение на `export-b-direct`.** Изменялся только in-memory тестовый контекст, fixtures не редактировались:

```text
base match exposure / C / D: confirmed confirmed confirmed
D with all graph-path Evidence.read sources disputed: confirmed
D with wrong event Evidence ObjectRef hash: confirmed True
C claims accepted after graph-path evidence omitted: 3 exposure: confirmed
```

Probe меняет `source_reliability` Evidence записей, относящихся к найденным path edges, на `disputed`; D по-прежнему возвращает confirmed. Затем у `ev-export-official` сохраняются owner/object_id/revision, но hash заменён на `sha256:` + 64 нуля; D всё равно возвращает confirmed, и assessment содержит подменённый hash. Наконец, из controlled C claims удаляются path-only Evidence refs, оставлены event refs; валидатор принимает 3 claims и assessment остаётся confirmed.

**Риск.** Основание не привязано к точной immutable Evidence версии и качеству path evidence. В частности, `verified_anchor` само по себе может привести к подтверждённому воздействию, хотя правила Framework запрещают считать anchor доказательством истины. Нужны сравнение полного ObjectRef, согласованная проверка reliability всех использованных path refs и adversarial regression, требующий достаточной provenance для каждого механизма. Это исследовательские правила, не изменение DTO.

**Как повторить.** Из корня T13 worktree установить `$env:PYTHONPATH='packages/contracts/src'`, импортировать `load_materialized_inputs`, `load_json`, `make_context` из `spike/T13/experiments/run_offline.py`, выбрать строку `case_id == 'export-b-direct'` из `scenario_matrix.json`. Передать результат `make_context` в `assess_d` и `assess_c` с `controlled_model_response`. Для первого probe скопировать Evidence rows, используемые рёбрами `ctx.match.edge_paths`, заменив их `source_reliability` на enum `SourceReliability.disputed`. Для второго заменить hash event ref `ev-export-official` на `sha256:` + `64*'0'`. Для третьего удалить из каждой claim refs все refs, кроме `ctx.event.evidence_refs`. Наблюдаемые значения приведены выше; реализации и fixture остаются нетронутыми.

## MEDIUM-01 — Неактуальное событие остаётся confirmed в Matching

`EventContext.current` есть в структуре, но `_make_match` не учитывает его при вычислении exposure (`matching/core.py:38-46,187-205`). `replace(event, current=False)` для того же реального export record и сбалансированного режима всё равно даёт `Exposure.confirmed`. Impact D позже блокирует `current=False`, но `Matching.match` сам возвращает confirmed. Нужен negative regression для inactive event и консервативный Matching status.

## MEDIUM-02 — При несовпадающем Business slice теряется объяснение unknown

`_make_match` добавляет `/graph/input_slices` в missing при несовпадении точной версии (`matching/core.py:153-166`), но ветка `none_found` не проверяет `slice_aligned` (`:193-201`). `match_context` затем удаляет `none_found` строки, после чего собирает missing только из оставшихся matches (`:246-252`). Repro на том же актуальном graph с profile slice revision `99` (и очищенными profile missing/contradictions): `matches=[]`, `search_complete_for_scope=False`, `missing_data=[]`. Ответ показывает неполноту scope, но скрывает точную причину.

## MEDIUM-03 — Offline 30-case harness частично обходит Events.read

`build_scenario_matrix.py:14-48,60-94` вручную задаёт TARGETS/FACTUAL_STATUS/CURRENT. `run_offline.py:91-115` загружает реальную EventRecord только для ref, но собирает новые EventContext из матрицы и news catalog; отсутствие EventRecord заменяет синтетической ссылкой `hash_ref`. В данных лишь 3 из 15 уникальных event IDs присутствуют в текущем prepared Events.read, то есть 18 из 30 сценариев не проверяют фактический Events.read status/targets/refs. Даже для export-сценария матрица задаёт свои evidence refs. Поэтому `same_inputs=true` и 30 safety counters подтверждают одинаковость двух вариантов на одном ручном synthetic context, но не end-to-end совместимость с Events.read/T11. Текущие авторские ограничения это частично раскрывают; отдельный integration regression всё ещё нужен.

## MEDIUM-04 — ImpactAssessment не сохраняет StatementRef/path lineage

`build_assessment` заполняет `Provenance.input_statement_refs=[]` независимо от фактически использованных event statements и graph edge inputs (`impact/common.py:178-235`). C валидирует edge path и D проверяет его, но assessment сериализует только механизм/общие evidence refs, а generic trace остаётся вне operation DTO (`approach_c.py:152-181`, `approach_d.py:81-109`). Это мешает независимо восстановить, какие точные statements образовали причинную цепочку, хотя входной Match отдельно содержит edge IDs. Нужны исполнимая provenance проверка и документирование ограничений; контракты в рамках spike не расширять.

## Проверки, которые прошли

Команды выполнялись в worktree review с `$env:PYTHONPATH='packages/contracts/src'`:

```powershell
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T13/tests -q --tb=short
```

**55 passed**. Дополнительно:

```powershell
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider tests/contracts -q --tb=short
```

**31 passed**.

```powershell
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
```

Shared validator: canonical hash v1.0.1 совпал; **13 passed, 0 failed**, все пять prepared operation fixtures.

```powershell
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T13/experiments/run_offline.py
```

Offline harness: 30 сценариев. Счётчики его локальных safety-инвариантов равны нулю (`C` claims without graph path / unavailable evidence / unsupported quantity; `D` mechanisms without path / sector-only mechanisms; non-null contract financial quantities; recommendations outside local safe catalog). Это не измерение качества живой модели и не снимает HIGH-02: counters не мутируют refs/reliability adversarially. Model quality, latency и cost помечены NOT MEASURED.

Также просмотрены `spike/T13/recommendations/propose.py` и тесты: action allowlist, audience, approval floor, evidence refs; побочных banking/external effects не найдено. Вызовов сетевых сервисов, модели или БД в модуле не обнаружено; C реализован как controlled model-shaped offline adapter, а не live LLM. `git diff --check` проходит.

## Заключение для интеграции

Engineering tests: **PASS локально**. Algorithm quality: **PRELIMINARY / live model NOT MEASURED**. Contract DTO suite/shared fixtures: **PASS по форме**. Integration readiness: **NOT READY** из-за HIGH-01/HIGH-02 и cross-operation Event/T11 несогласованности. Рекомендации остаются информационными, ограничены переданным каталогом; внешних действий не найдено. Исправления реализации намеренно не вносились.
