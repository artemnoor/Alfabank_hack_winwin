# T08 — Jev classification spike

Изолированный эксперимент для русскоязычных synthetic business news через Jev на Polza AI. Jev остаётся единственным classifier. Spike не подключён к runtime, не меняет OpenAPI и не является production policy.

## Последний offline quality pass — 2026-10-14

- **Engineering quality:** см. актуальные результаты в `TEST_REPORT.md` и `TEST_REPORT.json`. Тесты анализируют сохранённые ответы v4; live запросов в этой работе не было.
- **Причины review 93,3%:** у 42 из 45 сохранённых ответов сработал текущий rule gate. Активные причины перекрываются: Choice=5, event score в серой зоне=24, insufficient-evidence score >0.2=17, unlisted score >0.2=32. 28 review-кейсов имеют несколько причин.
- **Это не значит, что Jev ошибся в 93,3% случаев.** В среднем диапазоне Noul может означать abstain, а текущая логика превращает это в review. У всех 33 unlisted scores выше 0.2 состояние было `abstain`; positive ≥0.8 не было.
- **Сохранённые метрики остаются предварительными:** 45/49 ответов, topic accuracy 31/45 = 68,9%, event micro-F1 0,840, exact event-set 34/45 = 75,6%. Эталонные метки составлены одним автором, часть спорна; 4 ответа отсутствуют.
- **Model quality:** NOT MEASURED для интеграционного решения. На малом черновом synthetic set нельзя безопасно обещать снижение ручных проверок.
- **Интеграция:** NOT READY. Runtime, production code и контракты не менялись.
- **Live API:** исторический отчёт описывает 45 сохранённых успешных ответов через Polza. В текущем quality pass запросов не было. Общий известный исторический след — до 53 вызовов, если три прежних HTTP 451 проверки считать с 50 попытками пилота; новые запросы требуют отдельного решения.

## Артефакты этого разбора

- `ERROR_ANALYSIS.md` — topic/event mismatches, локальные synthetic texts, гипотезы причин и gold caveats.
- `UNCERTAINTY_ANALYSIS.md` — полная матрица 45 ответов со всеми event scores и review triggers.
- `THRESHOLD_COMPARISON.md` — counterfactual coverage/risk и раздельные Choice, event, insufficient-evidence и unlisted gate sweeps.
- `QUALITY_ANALYSIS.json` — машинный подробный расчёт по pinned v4.
- `HUMAN_REVIEW_PACKET.md` — спорная разметка на ручную adjudication; AI review не является human gold.
- `experiments/taxonomy-v0.4-proposal/` и `TAXONOMY_PROPOSAL.md` — отдельная неутверждённая и непроверенная taxonomy proposal. Исходная v0.3 не менялась.
- `DEEP_CORPUS_AUDIT.json` и `BENCHMARK_PLAN.md` — аудит 160 примеров и план настоящего blind set. D видим и не является blind.
- `NEXT_STEPS.md` — следующий эксперимент; предложение на 20 matched calls требует отдельного бюджета и здесь не запускалось.
- `AI_REVIEW_LOG.md` — роли субагентов и ограничения ревью.

## Повторяемые offline команды

    python -m unittest discover -s spike/T08 -p "test*.py" -v
    ruff check spike/T08
    ruff format --check spike/T08
    python spike/T08/run_spike.py
    python spike/T08/quality_analysis.py --check
    python spike/T08/deep_corpus_audit.py --check

`run_spike.py` без `--live` выполняет только локальную проверку. Тесты также блокируют network entrypoints; тест исчерпанного ledger доказывает, что over-budget run не доходит до `classify`.

## Сохранённые данные

- `corpus.json`: SHA-256 `592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d7`.
- `taxonomy.json` v0.3.0-spike: SHA-256 `855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d`.
- Aggregate v4: `results/jev-live-aggregate-20261014-v4.json`; historical bytes and prior report copied to `results/archive/` before updates.

Не сохранять ключи, raw provider responses или prompts. Изменения ограничены `spike/T08`; main runtime и OpenAPI остаются без изменений.

## Подготовка к следующему этапу

- Разбор всех 6 FP-кандидатов и 7 FN-кандидатов Policy v2.1: `ERROR_ANALYSIS_V2.1.md` и `ERROR_ANALYSIS_V2.1.json`. Это расхождения с предварительными метками одного автора, не adjudicated model errors.
- `HUMAN_REVIEW_PACKET_V2.1.md` — отдельный model-blind первичный лист для e03/e09/e10/e18/e25/e26/e27/e28/e32/e33/e34/e35. В нём нет draft labels и Jev scores; e35 отмечен как кейс без сохранённого ответа.
- Предложение taxonomy `0.4.1-spike`: `experiments/taxonomy-v0.4.1-proposal/`. Оно уточняет только границы и правила разметки, сохраняет коды и вопросы, не меняет v0.3/v0.4, не тестировалось live и ждёт решения владельца.
- Candidate holdout из 60 новых синтетических текстов: `experiments/blind-candidate-v1/`. В корпусе нет model outputs и gold labels, он исключён из текущих отчётов и sweeps. Он ждёт независимой разметки и пока не является завершённым blind benchmark.
- `T09_HANDOFF.md` описывает экспериментальную передачу неподтверждённых event-кандидатов. Это не DTO и не runtime-интеграция; T09 должен привязать свои утверждения к источнику и evidence spans.
- Проверка материалов: `python -m unittest discover -s spike/T08 -p "test*.py" -v`; сборка proposal/report: `python spike/T08/build_t08_validation_assets.py`.
