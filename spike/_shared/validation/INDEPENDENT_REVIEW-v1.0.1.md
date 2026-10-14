# Независимое ревью общего synthetic dataset v1.0.1

- Результат: **PASS для использования как provisional offline corpus**.
- Severity: **CRITICAL — 0; HIGH — 0; MEDIUM — 0; LOW — 1 документированное ограничение**.
- Dataset: `t09-t13-independent-v1` / `1.0.1`.
- Проверенная ветка: `codex/review-shared-dataset-v101`; checkout чистый на `a5e2d2cd5f9df8fe72fc4c7c41683640eca69623` до создания этого отчёта.
- База, указанная в provenance: `ce640214be7c5ff2fdb451b9e290135a11b512a6`.
- Проверка выполнялась независимо от автора датасета. Данные, контрактные файлы и approved fixtures не исправлялись.

## Выполненные проверки

1. **Свежий checkout и переносимость hash.** Ветка была проверена без локальных изменений; `core.autocrlf=true`. Независимо пересчитал SHA-256 для файлов из `manifest.json` и всех пяти operation fixtures, применив LF-нормализацию (`CRLF` и одиночный `CR` → `LF`) для текстовых JSON, как описывает validator. Все 10 проверенных файлов совпали с манифестом. Canonical JSON hash `data.json`: `sha256:f8a8a275a61e894ccb9dc1d9e3eaae46745467d6630db2a085466ad7e8372725`.
2. **Общий validator и нормативные DTO.** Команда `& $python -B spike/_shared/validation/validate.py`, где `$python` — закреплённый Python workspace `.venv\Scripts\python.exe`. Среда: Python `3.12.15`, Pydantic `2.14.1`. Результат: **13 passed, 0 failed**, все пять strict operation exchanges прошли: `Understanding.extract`, `Events.read`, `Business.read`, `Evidence.read`, `Graph.query`. Validator использует operation registry/OpenAPI текущего checkout и `validate_operation_exchange` с strict Pydantic DTO/semantic validation. Сгенерированный validator-ом общий `VALIDATION_REPORT.md` восстановлен к исходному состоянию; в diff оставлен только этот независимый review report.
3. **T12 гипотетические, inferred и отрицательные входы.** Запустил `executable T12 hypothetical/inferred/negative graph inputs` в validator и отдельно проверил cases/input refs и payloads:
   - `hypothetical-only` указывает на материализованный `Statement` со статусом `hypothetical`, без source/evidence refs; case требует не публиковать из него factual positive edge.
   - `inferred-relation-grounding` разрешается в `inferred-company-country-x`. У candidate сохранены `origin=derived`, method `spike.graph.rule.company-supplier-location` и две `input_statement_refs`; каждая ссылка разрешается по aggregate ref, statement revision и canonical content hash к подтверждённым premise statements. Candidate остаётся `inferred`, а ограничения явно запрещают трактовать его как независимо подтверждённый факт.
   - `explicit-negative-not-positive-dependency` разрешается в materialized `user_declared` Statement с predicate `does_not_source_from_country`; он ссылается на `ev-a-source-denial`. Текст source anchor и его quote hash совпадают. Limitations прямо отделяют наличие проверенной цитаты от истинности заявленного.
4. **Версия, происхождение и статус.** `manifest.json` и `data.json` согласованы по ID/version и canonical hash. Corpus и каждый operation fixture имеют `origin=synthetic`, `manual_approval=provisional`; dataset status — `provisional_not_gold_not_approved`. Provenance фиксирует `model_outputs_used_as_labels=false` в данных, а manifest фиксирует `external_facts_used=false` и dataset provenance — `external_sources_used_for_facts=false`; подготовленные operation fixtures помечены как ручные deterministic offline inputs, не как выходы T08/T09–T13 или модели. Case counts: T09 `32`, T10 `22`, T11 `12`, T12 `15`, T13 `30`.
5. **Approved fixtures и checkout чистота.** Validator пересверил read-only approved index и указанные fixture/dataset hashes. Дополнительно `git diff --name-status ce640214be7c5ff2fdb451b9e290135a11b512a6 HEAD -- fixtures/approved` не вывел изменений; `git diff --check` чистый. До записи этого отчёта `git status` был чистым.
6. **Воспроизводимость.** Validator повторно построил `data.json` и все пять fixtures через frozen builder; результат идентичен committed payloads.

## Замечание низкой severity

- **LOW — ограничение уже зафиксировано, не блокирует provisional dataset.** Predicate `depends_on_country` и правило `spike.graph.rule.company-supplier-location` имеют экспериментальную семантику. Dataset корректно помечает результат как inferred, передаёт метод и premise refs, а `COMPATIBILITY_GAPS.md` предупреждает, что semantic mapping predicates не утверждён владельцем ontology. До такого согласования этот пример проверяет сохранение основания и статуса; он не разрешает публиковать confirmed dependency или использовать её как production fact.

## Итог

Найденных CRITICAL/HIGH/MEDIUM дефектов не обнаружено. Версия v1.0.1 устраняет заявленные проблемы v1.0.0 в проверенных областях: hashes стабильны при Windows LF/CRLF checkout, а три T12 случая ссылаются на исполняемые материализованные inputs. Успешная DTO-валидация подтверждает форму и семантические ограничения контрактов; она **не** подтверждает истинность synthetic facts и не делает provisional ожидания gold labels или мерой качества алгоритмов.

## Основные команды

```powershell
git status --short --branch
git rev-parse HEAD
$python = 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe'
& $python --version
& $python -c "import pydantic; print(pydantic.__version__)"
& $python -B spike/_shared/validation/validate.py
git diff --check
git diff --name-status ce640214be7c5ff2fdb451b9e290135a11b512a6 HEAD -- fixtures/approved
```