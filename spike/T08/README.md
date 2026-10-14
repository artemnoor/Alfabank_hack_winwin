# T08 — Jev classification spike

Изолированный эксперимент для русскоязычных synthetic business news через Jev на Polza AI. Jev остаётся единственным classifier. Spike не подключён к runtime, не меняет OpenAPI и не является production policy.

## Текущее состояние — 2026-10-15

- **Engineering quality:** PASS по текущим офлайн-проверкам, см. `TEST_REPORT.md` и `TEST_REPORT.json`.
- **API compatibility:** текущий клиент live не проверялся; BLOCKED для интеграционного решения. Исторические ответы через Polza — ограниченное свидетельство, не проверка нынешнего source revision.
- **Model quality:** не доказано для production. Сохранённые метрики описательные, синтетические и основаны на предварительной односторонней разметке.
- **Передача в T09:** подготовлена только для исследования неподтверждённых event-кандидатов; runtime-интеграции нет.
- **Причины review 93,3%:** у 42 из 45 сохранённых ответов сработал текущий rule gate. Активные причины перекрываются: Choice=5, event score в серой зоне=24, insufficient-evidence score >0.2=17, unlisted score >0.2=32. 28 review-кейсов имеют несколько причин.
- **Это не значит, что Jev ошибся в 93,3% случаев.** В среднем диапазоне Noul может означать abstain, а текущая логика превращает это в review. У всех 33 unlisted scores выше 0.2 состояние было `abstain`; positive ≥0.8 не было.
- **Сохранённые метрики остаются предварительными:** 45/49 ответов, topic accuracy 31/45 = 68,9%, event micro-F1 0,840, exact event-set 34/45 = 75,6%. Эталонные метки составлены одним автором, часть спорна; 4 ответа отсутствуют.
- **Интеграция:** T09 handoff готов только как экспериментальная заметка. Runtime, production code и контракты не менялись.
- **Live API:** в этой работе запросов не было. Известно 50 попыток пилота и 3 отдельные проверки, вернувшие HTTP 451; их причина неизвестна.

## Policy v2.1 и передача кандидатов

- Событие с оценкой ≥0,80 передаётся как неподтверждённый кандидат. Choice и `abstain` сохраняются, но не блокируют отдельного кандидата.
- `insufficient_evidence ≥0,80` удерживает уже найденные кандидаты. `unlisted_event ≥0,80` создаёт отдельную задачу проверки и не блокирует известные события.
- На тех же 45 ответах: 32 новости с 40 кандидатами; 0 review-задач по сигналам evidence/unlisted; 6 FP и 7 FN-расхождений с предварительными метками. В provisional risk group — 3 FP.
- Ноль review на этой выборке не доказывает безопасность. Кандидаты — не подтверждённые факты, а labels не утверждены человеком.
- Разбор причин — `ERROR_ANALYSIS_V2.1.md`/`.json`; граница передачи — `T09_HANDOFF.md`.
- Замороженные правила и hashes Policy v2.1 — `POLICY_V2.1.md` и `POLICY_V2.1.manifest.json`. Это локальный экспериментальный маршрут, не runtime.
- Спорная разметка предварительно проверена отдельно в `GOLD_LABEL_REVIEW_V2.1.md`/`.json`; AI reviewer не является human gold, исходные labels не менялись.

## Артефакты этого разбора

- `ERROR_ANALYSIS.md` — topic/event mismatches, локальные synthetic texts, гипотезы причин и gold caveats.
- `UNCERTAINTY_ANALYSIS.md` — полная матрица 45 ответов со всеми event scores и review triggers.
- `THRESHOLD_COMPARISON.md` — counterfactual coverage/risk и раздельные Choice, event, insufficient-evidence и unlisted gate sweeps.
- `QUALITY_ANALYSIS.json` — машинный подробный расчёт по pinned v4.
- `HUMAN_REVIEW_PACKET.md` — спорная разметка на ручную adjudication; AI review не является human gold.
- Latest taxonomy proposal — `experiments/taxonomy-v0.4.2-proposal/`; предыдущие 0.4.0/0.4.1 сохранены как родители. Proposal неутверждён, live не тестировался; базовая v0.3 и ответы Jev не менялись.
- `experiments/future-blind-candidate-v1/` — 40 новых синтетических inputs без labels и ответов Jev. Это candidate pool, пока не blind test: labels должны создать два человека, adjudicate третий, хранить их должен независимый custodian.
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
    python spike/T08/build_taxonomy_v042_proposal.py
    python spike/T08/build_future_blind_candidate.py
    python spike/T08/build_policy_v21_manifest.py

`run_spike.py` без `--live` выполняет только локальную проверку. Тесты также блокируют network entrypoints; тест исчерпанного ledger доказывает, что over-budget run не доходит до `classify`.

## Сохранённые данные

- `corpus.json`: SHA-256 `592ae6ad0ddfbe4b191a95a520887c7441157f72e48050ce9f2d4895099bb0d7`.
- `taxonomy.json` v0.3.0-spike: SHA-256 `855a61f9b6c199d8440b8b81bbd09234e376896576121ed163af2ed7f0c1455d`.
- Aggregate v4: `results/jev-live-aggregate-20261014-v4.json`; historical bytes and prior report copied to `results/archive/` before updates.

Не сохранять ключи, raw provider responses или prompts. Изменения ограничены `spike/T08`; main runtime и OpenAPI остаются без изменений.

## Подготовка к следующему этапу

- Разбор всех 6 FP-кандидатов и 7 FN-кандидатов Policy v2.1: `ERROR_ANALYSIS_V2.1.md` и `ERROR_ANALYSIS_V2.1.json`. Это расхождения с предварительными метками одного автора, не adjudicated model errors.
- `HUMAN_REVIEW_PACKET_V2.1.md` — нейтральный пакет по всем 49 непустым baseline-новостям, без исходных ID, draft labels и Jev scores. Он слеп к результатам модели, но не к владельцу репозитория; независимых человеческих разметчиков пока нет.
- Предложение taxonomy `0.4.1-spike`: `experiments/taxonomy-v0.4.1-proposal/` — сохранённая промежуточная версия.
- Latest taxonomy proposal `0.4.2-spike`: `experiments/taxonomy-v0.4.2-proposal/` и `TAXONOMY_PROPOSAL_V0.4.2.md`. Это неутверждённое офлайн-предложение: уточняет event boundaries и отделяет сомнение в событии от сомнения в теме. Кодовая схема и пороги не менялись; требуется новый разрешённый live-пилот, качество не доказано.
- Набор из 60 новых синтетических текстов: `experiments/visible-validation-v1/`. Это только visible validation: тексты уже видели авторы/разработчики, поэтому набор не может стать финальным blind test, даже если labels держать отдельно. Для blind evaluation нужен новый корпус от независимого custodian после фиксации taxonomy, prompt и policy.
- `T09_HANDOFF.md` описывает экспериментальную передачу неподтверждённых event-кандидатов. Это не DTO и не runtime-интеграция; T09 должен привязать свои утверждения к источнику и evidence spans.
- Проверка: `py -m unittest discover -s spike/T08 -p 'test*.py' -v`; Policy/Playwright: `py -m unittest spike.T08.visualization.test_policy_v2 spike.T08.visualization.test_visualization -v`.
- Пересобрать proposal, visible validation и error audit: `py spike/T08/build_t08_validation_assets.py`.
- Пересобрать TEST_REPORT после прогонов: `py spike/T08/build_t08_report.py --tests-passed 132 --browser-tests-passed 27 --ruff-check PASS --ruff-format-check PASS --offline-runner PASS --quality-analysis-reproducibility PASS --deep-corpus-audit-reproducibility PASS --validation-asset-builder PASS --javascript-syntax PASS --git-diff-checks PASS`; проверить воспроизводимость — добавить `--check`.
- SHA-256 текстовых входов считается после приведения CRLF/CR к LF, как в Git; те же проверки должны проходить в Windows и Linux checkout.
