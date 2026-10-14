# Независимый re-review T13 remediation

- Проверенная база: 2a65a5f37cb11f28f4fc33905b634ec6cec7c09b.
- Исходный review: spike/T13/results/INDEPENDENT_REVIEW.md, база 6309956355dd3fa78335474d8e278f56922288e0.
- Область: изменённые T13 matching/impact gates, regression tests, нормативные Matching.match / Impact.assess contracts, prepared Events.read / Evidence.read и независимый T11 v1.0.1 результат.
- Режим: implementation и fixtures не изменялись. Единственный создаваемый файл — этот отчёт.

## Итог

**CRITICAL: нет. HIGH: исходные два findings закрыты для нормативного contract пути.** Остались MEDIUM integration gaps, поэтому T13 пока **NOT INTEGRATION READY**. Они связаны с отсутствующим T11 handoff/policy provenance, caller-created owner confirmation в spike-local API и тем, что 30-case harness не материализует Events.read для всех сценариев.

| Исходный finding | Результат re-review |
|---|---|
| HIGH-01 — обычный Events.read confirmed превращался в confirmed Match/C/D вопреки T11 | **Закрыт для contract entry points.** from_record не выводит owner confirmation; Match/C/D отдают potential, а не confirmed, и фиксируют отсутствие trusted confirmation. Сохраняется MEDIUM handoff gap ниже. |
| HIGH-02 — Impact D/C не связывали полную Evidence ref и основания пути | **Закрыт.** Wrong hash, disputed path Evidence и пропуск path refs воспроизведены fail-closed. |
| MEDIUM-01 — inactive event получал confirmed Matching | **Закрыт в части confirmed.** Теперь результат potential с явным missing currentness; confirmed не возвращается. |
| MEDIUM-02 — потеря объяснения Business slice mismatch | **Закрыт.** Причина /graph/input_slices сохраняется в ответе. |
| MEDIUM-03 — 30-case harness обходил Events.read | **Остаётся.** 18/30 event IDs отсутствуют в материализованном Events.read; для всех строк harness строит EventContext из локальной матрицы. |
| MEDIUM-04 — терялся StatementRef/path lineage | **Закрыт.** Реализация возвращает event и использованные edge StatementRefs. |

## MEDIUM-01 — T11 результат и provenance не проходят через operation contract

Нормативный Events.read для event-export-x-mk7 содержит entity statement со статусом confirmed и Evidence ref ev-export-official (spike/_shared/fixtures/t09-t13-independent-v1/events-read.json:158-208). Независимый T11 результат exact-anchor для ev-export-official сообщает claim_status=supported_unconfirmed, final_status=not_confirmed, owner_policy_id=null (spike/T11/results/offline-v1.0.1.json:7-13,55). По правилу Framework verified_anchor подтверждает целостность anchor, но не истину; подтверждение требует разрешающей trusted owner policy (docs/specs/framework-v1/02-contracts.md:80).

Воспроизведение через нормативные модели дало:

    EventContext.from_record:
      factual_status=confirmed
      current=True
      target_entity_ids=('component-mk7', 'country-x')
      trust_claim_status=not_provided
      trust_final_status=not_confirmed
      owner_policy_ref=None
    Matching.match exposure=potential
    Impact C exposure=potential, mechanisms=['restricted_input_supply']
    Impact D exposure=potential, mechanisms=['restricted_input_supply']
    Impact D missing_data включает /event/trusted_confirmation

То есть remediation закрывает прежний ложный confirmed вывод. При явном claim_status=not_confirmed обе ветки C/D возвращают unknown без mechanisms. Поддержанное, но не подтверждённое состояние может оставаться только conditional potential; owner confirmation по-прежнему требуется для confirmed.

Открытая граница: EventContext.from_record не принимает независимый T11 результат и подставляет not_provided. Нормативные MatchingInput/ImpactInput также не содержат T11 result или policy ref. Поэтому операция не может связать EventRecord factual_status=confirmed с известным T11 final_status=not_confirmed, сохранить точный T11 policy provenance или отличить отсутствующий T11 результат от результата, реально переданного upstream. Текущий fail-closed gate не выдаёт confirmed, однако cross-module согласованность и provenance operation output не доказаны.

Сценарии offline harness не устраняют пробел: experiments/run_offline.py:97-112 вручную строит EventContext, используя factual_status, target_entity_ids и evidence IDs из scenario matrix. Контекст не получается вызовом EventContext.from_record.

Рекомендация для владельца интеграции: передавать материализованный T11 result в отдельный внутренний адаптер без изменения OpenAPI, зафиксировать отображение claim_status/final_status в EventContext, и добавить сквозной regression на точную пару supported_unconfirmed/not_confirmed. Условный potential должен содержать явное объяснение неопределённости и missing trust state; неподтверждённый итог не должен становиться confirmed. Это integration gap, а не воспроизведение исходного HIGH: ни обычный contract путь, ни текущая T11 пара не дают confirmed exposure.

### Точный contract repro

В worktree codex/review-t13-final:

    $env:PYTHONPATH='packages/contracts/src;spike/T13'
    @'
    from dataclasses import replace
    import json
    from pathlib import Path
    from alfalab_contracts._generated import Exposure, Mode
    from alfalab_contracts.models import MatchingInput, ImpactInput
    from experiments.run_offline import load_materialized_inputs
    from matching.core import EventContext, match_contract
    from impact.common import context_from_contract
    from impact.approach_c import assess_c, assess_c_contract, controlled_model_response
    from impact.approach_d import assess_d, assess_d_contract

    _, profiles, graph, evidence, events = load_materialized_inputs()
    event = events["event-export-x-mk7"]
    profile = profiles["company-b"]
    match_request = MatchingInput(event=event, graph=graph, profiles=[profile], mode=Mode.strict, limit=10)
    match = match_contract(match_request).matches[0]
    request = ImpactInput(event=event, profile=profile, match=match, graph=graph, evidence=list(evidence.values()), rules=None, as_of=profile.as_of)
    context = context_from_contract(request)
    c = assess_c_contract(request, controlled_model_response(context)).assessment
    d = assess_d_contract(request).assessment
    assert EventContext.from_record(event).factual_status == "confirmed"
    assert context.event.trust_claim_status == "not_provided"
    assert context.event.trust_final_status == "not_confirmed"
    assert c.exposure == d.exposure == Exposure.potential
    assert c.mechanisms and d.mechanisms
    print("contract:", c.exposure.value, [item.code for item in c.mechanisms], d.exposure.value, [item.code for item in d.mechanisms])

    t11 = json.loads(Path("spike/T11/results/offline-v1.0.1.json").read_text(encoding="utf-8"))
    row = next(item for item in t11["cases"] if item["case_id"] == "exact-anchor")
    assert (row["claim_status"], row["final_status"], row["owner_policy_id"]) == ("supported_unconfirmed", "not_confirmed", None)
    print("T11:", row["claim_status"], row["final_status"], row["owner_policy_id"])

    t11_supported = replace(
        context,
        event=replace(
            context.event,
            trust_claim_status="supported_unconfirmed",
            trust_final_status="not_confirmed",
            owner_policy_ref=None,
            owner_policy_decision=None,
        ),
    )
    c_supported = assess_c(t11_supported, controlled_model_response(t11_supported)).assessment
    d_supported = assess_d(t11_supported).assessment
    assert c_supported.exposure == d_supported.exposure == Exposure.potential
    assert c_supported.mechanisms and d_supported.mechanisms
    assert any(item.path == "/event/trusted_confirmation" for item in d_supported.missing_data)
    print("explicit supported_unconfirmed/not_confirmed:", c_supported.exposure.value, d_supported.exposure.value)

    explicit_no_confirmation = replace(
        context,
        event=replace(context.event, trust_claim_status="not_confirmed", trust_final_status="not_confirmed"),
    )
    c_blocked = assess_c(explicit_no_confirmation, controlled_model_response(explicit_no_confirmation)).assessment
    d_blocked = assess_d(explicit_no_confirmation).assessment
    assert c_blocked.exposure == d_blocked.exposure == Exposure.unknown
    assert not c_blocked.mechanisms and not d_blocked.mechanisms
    print("explicit claim_status=not_confirmed:", c_blocked.exposure.value, d_blocked.exposure.value)
    '@ | & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -

Вывод: contract: potential / restricted_input_supply для C и D; T11: supported_unconfirmed / not_confirmed / null; явный trust_claim_status=not_confirmed блокирует обе ветки. При паре T11 supported_unconfirmed/not_confirmed conditional potential сохраняется, но operation contract не передаёт эту пару, её policy provenance или explicit uncertainty в EventContext.

## MEDIUM-02 — synthetic owner pin не удостоверяет, кто принял решение

matching/core.py:29,61-72 считает owner confirmation истинным, когда EventContext содержит литерал owner-policy ref из T13, статусы confirmed и caller-provided строку explicit_owner_confirmation. Ни MatchingInput, ни ImpactInput не позволяют передать эти поля; from_record по умолчанию оставляет owner_confirmed=False. Поэтому обычный contract путь закрыт.

Однако прямой API spike можно вызвать с вручную сконструированным EventContext: в независимом probe присвоены TEST_OWNER_POLICY_REF, trust_claim_status=confirmed, trust_final_status=confirmed и owner_policy_decision=explicit_owner_confirmation. Результаты: owner_confirmed=True, Matching=confirmed, C=confirmed, D=confirmed. Это не подтверждается T11: подготовленный owner policy provisional и допускает только eligibility for review; фактический T11 exact-anchor возвращает owner_policy_id=null и final_status=not_confirmed. Spike не аутентифицирует caller-created owner decision.

Ограничение уже раскрыто в spike/T13/LIMITATIONS.md:9. Это не bypass нормативного request DTO, но до trusted owner registry/result и защищённой сборки EventContext такой direct API нельзя считать интеграционным подтверждением. Severity MEDIUM; production/runtime trust binding остаётся обязательным gate.

## HIGH-02 — регрессии точных Evidence refs закрыты

Независимые probes на неизменённых fixtures воспроизвели:

- Подмена hash event Evidence при сохранении owner/object_id/revision: D вернул unknown и ноль mechanisms; C отклонил claim с сообщением claim evidence is absent from the exact supplied event/path inputs.
- Evidence для использованных graph edges с source_reliability=disputed: D вернул unknown и ноль mechanisms; C отклонил claim как disputed source reliability.
- Удаление из C claim всех path-only Evidence refs: валидатор отклонил claim с claim omits graph path evidence.

Это соответствует impact/approach_c.py:99-130 и impact/approach_d.py:41-79. В коде путь должен существовать в переданном графе, проверяются полные owner/object/revision/hash refs, а unverified/disputed anchors и disputed path sources не дают пройти gate. Сам verified_anchor не приводит к confirmed: подтверждение требует отдельного owner gate.

## Остальные проверки и ограничения

- Inactive event с найденным путём теперь даёт potential и /event/currentness missing; confirmed не возвращается.
- При mismatch версии Business slice Matching сохраняет /graph/input_slices причину в output; search_complete_for_scope=False.
- StatementRef/path lineage присутствует в ImpactAssessment provenance для event и использованных graph edges.
- T13 harness содержит 30 строк, из которых 18 event IDs не находятся в prepared Events.read. Даже при наличии EventRecord make_context берёт targets, factual status и Evidence IDs из matrix. Harness измеряет локальные safety assertions, а не сквозную совместимость всех 30 кейсов с operation results.
- C остаётся controlled model-shaped offline adapter; live model quality, latency и cost не измерялись. Сетевых, database и внешних model вызовов в коде не обнаружено; модульный AST security test прошёл.
- Рекомендации остаются локальным informational allowlist без банковских или внешних side effects; изменения remediation commit их не затрагивали.

## Проверки

Команды выполнялись в worktree codex/review-t13-final, HEAD 2a65a5f37cb11f28f4fc33905b634ec6cec7c09b, с Python 3.12.15 и установленными зависимостями проекта.

    $env:PYTHONPATH='packages/contracts/src'
    & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T13/tests -q --tb=short
    # 63 passed, 0 failed, 0 skipped

    $env:PYTHONPATH='packages/contracts/src'
    & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider tests/contracts -q --tb=short
    # 31 passed, 0 failed, 0 skipped

    $env:PYTHONPATH='packages/contracts/src'
    & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/_shared/validation/validate.py
    # canonical dataset hash matched; 13 passed, 0 failed; five operation fixtures validated

    $env:PYTHONPATH='packages/contracts/src'
    & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T13/experiments/run_offline.py
    # 30 scenarios; all seven safety counters were 0

    git diff --check
    # passed

Module tests re-ran the offline comparison and changed only generated line endings in results/approach-comparison.json; that generated artifact was restored to its committed bytes before this report was written. No other file was modified.

## Статус качества

- **Engineering:** PASS для offline прототипа и contract suite.
- **Algorithm:** PRELIMINARY; provisional synthetic inputs only. Live model quality NOT MEASURED.
- **Integration:** NOT READY до решения и проверки T11 handoff/policy provenance, недоверенного caller-created owner decision и 30-case harness coverage.
- Контракты Framework v1 и shared dataset не изменялись.
