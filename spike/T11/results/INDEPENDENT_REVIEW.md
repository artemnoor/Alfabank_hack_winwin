# Независимое ревью T11 Evidence

- **Worktree / branch:** `C:\CodexData\worktrees\alfabank-review-t11-evidence` / `codex/review-t11-evidence`
- **Reviewed HEAD:** `66832de6d4b53237e6bb66e508e4641c27092efe` (T11 integration state; shared dataset v1.0.1)
- **Scope:** только read-only аудит T11 и нормативных Evidence DTO/семантики. Реализация не менялась.
- **Независимость:** ревьюер не является автором T11. Дополнительные Standards/Spec subagent-ревью не запущены: все четыре слота были заняты. Это ограничение процесса; основной аудит и воспроизведения выполнены.

## Итог по severity

| Severity | Количество | Итог |
|---|---:|---|
| CRITICAL | 0 | — |
| HIGH | 1 | Нарушена point-in-time семантика: `known_as_of` фильтрует публикацию, но пропускает позднее поступление источника. |
| MEDIUM | 1 | Входная policy map не привязана к неизменяемой доверенной версии; можно расширить allow-list и получить `eligible_for_owner_review`. |
| LOW | 0 | — |

T11 **не готов к интеграции** до устранения HIGH и отдельного согласования владельцем политики. Прототип не устанавливает `confirmed` и не пишет production-состояние.

## HIGH — исторический срез пропускает сведения, ещё не полученные системой

**Файлы:** `spike/T11/src/evidence_trust.py:326–340, 357`; нормативные правила: `docs/specs/framework-v1/02-contracts.md:34`, `docs/specs/framework-v1/03-operations.md:107`.

`assess_claim(..., as_of=...)` сравнивает только `source.published_at` с одной временной точкой (строки 326–340). `source.collected_at` сохраняется в observation (строка 357), но не участвует в решении. При этом offline runner передаёт `manifest.as_of.known_as_of` в этот единственный аргумент. Framework v1 различает `valid_as_of` и `known_as_of`; утверждение, записанное после `known_as_of`, исключается из исторического среза. В текущем алгоритме публикация, вышедшая до среза, но загруженная в систему после него, считается известной на срезе. Одновременно не передаётся отдельный `valid_as_of`, поэтому время публикации и момент знания смешаны.

**Воспроизведение:** в зафиксированном синтетическом `exact-anchor` изменены только времена: `published_at=2026-10-13T08:00:00Z`, `collected_at=2026-10-15T08:00:00Z`; `as_of=2026-10-14T00:00:00Z`. Запущен inline Python через Python 3.12 `-B`, с теми же закреплёнными fixtures и алгоритмом:

```python
source["published_at"] = "2026-10-13T08:00:00Z"
source["collected_at"] = "2026-10-15T08:00:00Z"
result = assess_claim(claim_id, assertions, records, {source_id: source},
                      as_of="2026-10-14T00:00:00Z")
assert result.status is ClaimStatus.SUPPORTED_UNCONFIRMED
assert result.observations[0].applicable_as_of is True
```

Результат запуска: `status=supported_unconfirmed applicable_as_of=True collected_at=2026-10-15T08:00:00Z as_of=2026-10-14T00:00:00Z`. Это подтверждает использование будущего относительно knowledge snapshot материала. Ручные аннотации не нужны для этого эффекта; те же синтетические положительные данные просто перенесены за границу известности.

**Требуемое исправление автору:** разделить valid-time и knowledge-time входы, либо явно отказаться от заявления point-in-time knowledge semantics. Добавить regression case с `published_at <= valid_as_of`, но `collected_at/recorded_at > known_as_of`; такой источник не должен влиять на статус или policy eligibility. Отсутствующий/невалидный момент регистрации должен оставаться unknown, а не подменяться временем публикации.

## MEDIUM — проверка policy не подтверждает, что это доверенная версия policy

**Файл:** `spike/T11/src/evidence_trust.py:487–538`, в частности проверки метаданных и текстовых фрагментов правил (505–533).

`evaluate_owner_policy` получает произвольный `Mapping`. Он проверяет имя/schema/version/dataset/scope и наличие подстрок в правилах, но не сверяет полный content hash, подпись или версию из доверенного реестра. `authorized_statement_ids` принимается из той же изменяемой map. Поэтому тот, кто контролирует аргумент `policy`, может оставить все проверяемые метаданные неизменными и поменять только список авторизованных утверждений. Это не повышает `final_status` выше `not_confirmed`, однако функция начнёт выдавать положительный результат `eligible_for_owner_review`, хотя это уже не заявленная политика.

**Воспроизведение:** для материала `independent-roots` подготовлена та же `SUPPORTED_UNCONFIRMED` оценка. Неизменённая shared policy отклоняет новый ID `not-authorized-claim`; копия policy, где заменён только `authorized_statement_ids`, возвращает `eligible_for_explicit_owner_review` при тех же двух проверенных источниках/root IDs. Выполнены assertions; результат: `unchanged policy => not_eligible; caller-edited authorization list => eligible_for_explicit_owner_review (final_status=not_confirmed)`.

**Рекомендация:** для эксперимента загружать policy только из указанного immutable fixture и проверять его pinned hash/полную schema; для production-перехода принимать policy только из trusted owner registry/configuration, не от caller. Сохранить отдельное имя результата review-eligibility; не использовать его как подтверждение факта.

## Проверенные требования и положительные результаты

- **Anchor vs source assertion vs truth:** разделение корректное по границе текущего прототипа. `check_anchor` проверяет identity/revision/source hash/span quote hash и прямо не утверждает истинность (строки 182–187, 227–283). `assess_claim` получает связь `supports/contradicts/mentions_only/unknown` только как явную предварительную аннотацию (строки 57–63 и 286–294); это не extraction или независимая верификация содержания. Результат остаётся `supported_unconfirmed`; `final_status` зафиксирован как `not_confirmed`.
- **`verified_anchor`:** reliability-поле не продвигает статус; тест `test_reliability_label_does_not_promote_claim` прошёл. Исправность цитаты не объявляется правдивостью источника.
- **Перепечатки:** десять копий с одним `publisher_root_id` сворачиваются до одного root в policy count. `publisher_root_id` и независимость сами не проверяются — идентификаторы являются входами; это честно указано в `LIMITATIONS.md`.
- **Конфликты / unknown / unavailable:** разные current значения дают `disputed`; mentions-only, missing evidence, unavailable anchors и отсутствие основания не превращаются в positive fact. Исторический scope не считается current.
- **Source hash/version/anchor:** source ID, revision, whole-source hash, source_ref hash и quote hash проверяются; out-of-range/empty span и unavailable source закрываются fail-closed. Валидация `EvidenceRecord` вызывает pinned Pydantic contract, включая семантический owner check.
- **Контракт:** `Evidence.read` материализованный request/response проходит `validate_operation_exchange`; `Evidence.register` input DTO проходит строгую валидацию формы/семантики, но owner не вызывается. Это логический spike, не реализация обеих операций; Business/Runs `WholeArtifact` намеренно возвращаются как unavailable при отсутствии materialized owner snapshot. Output алгоритма — экспериментальные dataclasses, не нормативный `EvidenceResult`.
- **Security / reproducibility:** не обнаружены сетевые/LLM импорты и вывод текста источника в debug-лог; no-network тест и logging redaction тест прошли. Fixtures имеют зафиксированные версии/hash и остаются provisional.

## Запущенные проверки

Из корня worktree, Python 3.12 venv, `-B`, без pytest cache:

```powershell
$env:PYTHONPATH='spike/T11/src;packages/contracts/src'
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest spike/T11/tests -p no:cacheprovider -q
& 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B spike/T11/experiments/run_offline.py
Remove-Item Env:\PYTHONPATH
```

- pytest: **43 passed, 0 failed, 0 skipped** (`43 passed in 0.57s`).
- Offline runner: exit code 0; emitted all **12** fixture cases on shared dataset v1.0.1.
- Два finding reproductions выше исполнены отдельными assertion-based Python stdin runs; оба воспроизвелись. Они пока не сохранены как regression tests, так как разрешённый файл правки — только этот отчёт.
- Coverage не измерялось. Live model quality **NOT MEASURED**; алгоритмическое качество **PRELIMINARY** из-за синтетических и ручных аннотаций.

## Ограничения ревью

Тесты в основном подтверждают заранее заданные fixture properties и не проверяют два воспроизведённых adversarial случая. Source assertion является доверенным входом-аннотацией конкретного эксперимента: код не сверяет, следует ли утверждение из цитаты, и не должен описываться как верификатор entailment. Дополнительные независимые Standards/Spec subagent axes не запускались из-за полного лимита параллелизма; это не заменяет обнаруженные дефекты и не меняет результаты воспроизведения.

## Повторное выполнение findings

Из корня review worktree обе проверки ниже запускались через PowerShell here-string, переданный Python 3.12 `-B -` с `$env:PYTHONPATH='spike/T11/src;packages/contracts/src'`. Код не записывал файлы.

### HIGH: поздняя загрузка попадает в историческую оценку

```python
import copy, json
from pathlib import Path
from evidence_trust import ClaimStatus, SourceAssertion, assess_claim, project_catalog_record
root = Path(".")
data = json.loads((root / "spike/_shared/datasets/t09-t13-independent-v1/data.json").read_text(encoding="utf-8"))
fixture = json.loads((root / "spike/T11/fixtures/trust-cases-v1.0.0.json").read_text(encoding="utf-8"))
records = {r["ref"]["object_id"]: r for r in data["evidence_catalog"]}
sources = {r["document_id"]: copy.deepcopy(r) for r in data["source_documents"]}
case = next(c for c in fixture["cases"] if c["case_id"] == "exact-anchor")
assertions = [SourceAssertion.from_mapping(r) for r in fixture["source_assertions"] if r["evidence_ref"] in case["evidence_refs"]]
projected = {key: project_catalog_record(records[key]) for key in case["evidence_refs"]}
source = sources["doc-export-official"]
source["published_at"] = "2026-10-13T08:00:00Z"
source["collected_at"] = "2026-10-15T08:00:00Z"
result = assess_claim(case["claim_id"], assertions, projected, {"doc-export-official": source}, as_of="2026-10-14T00:00:00Z")
assert result.status is ClaimStatus.SUPPORTED_UNCONFIRMED
assert result.observations[0].applicable_as_of is True
print("reproduced:", result.status.value, result.observations[0].applicable_as_of, result.observations[0].source_collected_at)
```

Вывод: `reproduced: supported_unconfirmed True 2026-10-15T08:00:00Z`.

### MEDIUM: изменённый allow-list принимается как named policy

```python
import copy, json
from pathlib import Path
from evidence_trust import ClaimStatus, SourceAssertion, assess_claim, evaluate_owner_policy, project_catalog_record
root = Path(".")
data = json.loads((root / "spike/_shared/datasets/t09-t13-independent-v1/data.json").read_text(encoding="utf-8"))
fixture = json.loads((root / "spike/T11/fixtures/trust-cases-v1.0.0.json").read_text(encoding="utf-8"))
policy = json.loads((root / "spike/_shared/contracts/t09-t13-independent-v1/synthetic-owner-policy.json").read_text(encoding="utf-8"))
records = {r["ref"]["object_id"]: r for r in data["evidence_catalog"]}
sources = {r["document_id"]: copy.deepcopy(r) for r in data["source_documents"]}
case = next(c for c in fixture["cases"] if c["case_id"] == "independent-roots")
claim = "not-authorized-claim"
assertions = [SourceAssertion.from_mapping({**r, "claim_id": claim}) for r in fixture["source_assertions"] if r["evidence_ref"] in case["evidence_refs"]]
projected = {key: project_catalog_record(records[key]) for key in case["evidence_refs"]}
assessment = assess_claim(claim, assertions, projected, sources, as_of="2026-10-14T00:00:00Z")
assert assessment.status is ClaimStatus.SUPPORTED_UNCONFIRMED
unchanged = evaluate_owner_policy(claim, assessment, assertions, projected, sources, policy, dataset_id=policy["dataset_id"])
assert unchanged.eligible_for_owner_review is False
modified = copy.deepcopy(policy)
modified["authorized_statement_ids"] = [claim]
changed = evaluate_owner_policy(claim, assessment, assertions, projected, sources, modified, dataset_id=policy["dataset_id"])
assert changed.eligible_for_owner_review is True
assert changed.final_status == "not_confirmed"
print("reproduced:", unchanged.decision, "=>", changed.decision, changed.final_status)
```

Вывод: `reproduced: not_eligible => eligible_for_explicit_owner_review not_confirmed`.
