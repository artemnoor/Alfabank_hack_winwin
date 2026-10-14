# Независимое ревью T10 Business

- Worktree/branch: C:\CodexData\worktrees\alfabank-review-t10-business / codex/review-t10-business.
- HEAD: ff24cc398b248bdc284f328e0385129952131192; база модуля: 6498182.
- Рабочее дерево было чистым до создания отчёта; код/тесты не изменялись.
- Итоги: CRITICAL — 0; HIGH — 2; MEDIUM — 2; LOW — 0.
- Статус алгоритма: experimental, integration not ready; качество на реальных данных preliminary, live-model quality NOT MEASURED.

## Выполненные проверки

Сверил код с Business cards Business.propose_profile, Business.propose_questions, Business.apply, Business.read в docs/specs/framework-v1/03-operations.md и общими правилами docs/specs/framework-v1/02-contracts.md. Модульный набор: 79 passed, 0 failed, 0 skipped. Дополнительно провёл offline probes для временной видимости, supersede refs, конфликтов, unknown, hypothetical, declined, порядка вопросов, provenance и скрытого I/O.

AST import scan spike/T10/src/t10_business.py нашёл только stdlib и alfalab_contracts; сетевых, DB и model SDK imports/adapters нет. apply_profile/read_profile работают на явно переданных in-memory объектах. Двухагентный review process из навыка code-review не запускался: все доступные concurrency slots были заняты. Reviewer сам проверил spec и implementation; subagent review не заявляю.

## Findings

### HIGH — T10-R1: future-dated statement очищает unknown и скрывает вопрос

docs/specs/framework-v1/02-contracts.md:34 требует исключать statement с recorded_at > known_as_of. Но _valid_at в spike/T10/src/t10_business.py:335 проверяет только valid_from/valid_to. _fact_paths получает только valid_as_of (строки 521, 587); _field_known тоже вызывается только с valid_as_of (строки 644, 697). known_as_of не учитывается.

Воспроизведение: latest Company A имеет known_as_of=2026-10-01 и missing_data /dependencies/suppliers. Добавил user_declared purchases_from statement с valid_from=2026-01-01 и recorded_at=2026-10-14T01:00Z. propose_profile на исходном as_of удалил supplier path из missing_data: supplier missing path retained=False, хотя утверждение тогда не было известно. Это утечка будущего в исторический срез и может скрыть уточняющий вопрос.

Повтор: из shared data загрузить latest A и statement b-buys-microkaskad из latest B; создать его Statement-копию с subject=A.company, ID probe-future-supplier, status=user_declared, valid_from 2026-01-01, recorded_at 2026-10-14T01:00Z, без evidence/source refs; передать только эту statement через A.model_copy(update={"statements":[statement]}) в propose_profile(ProfileInput(... existing=A, as_of=A.as_of)). Полученный вывод: known_as_of=2026-10-01T00:00Z, recorded_at=2026-10-14T01:00Z, supplier missing path retained=False.

### HIGH — T10-R2: apply принимает foreign/stale supersede ref и закрывает локальную запись

docs/specs/framework-v1/02-contracts.md:36,43 требуют разрешать StatementRef внутри правильной immutable версии компании; Business.apply fixture foreign-statement: rollback указана в docs/specs/framework-v1/03-operations.md:244. Однако apply_profile в spike/T10/src/t10_business.py:812-816 учитывает только пару (statement_id, revision), игнорируя aggregate_ref и hash.

Воспроизведение: для Company A взял local a-activity-v2 (revision 2); сделал supersede ref с тем же ID/revision, aggregate_ref=Company B и hash из 64 нулей. Применил proposal к явно переданному snapshot Company A на 2026-10-14. apply_profile вернул snapshot, где local statement закрыт revision 3, valid_to=2026-10-14T00:00Z. Такой request должен быть отклонён до изменения состояния; сейчас нарушена scope/hash integrity.

Повтор: загрузить latest A/B; получить proposal пустого description с existing=A; добавить supersede_refs=[StatementRef(aggregate_ref=B.ref, statement_id="a-activity-v2", revision=2, hash="sha256:"+"0"*64)]; вызвать apply_profile с current=A и ApplyContext на 2026-10-14; проверить, что revision 3 local statement создана.

### MEDIUM — T10-R3: conflicts внутри новых входов остаются незамеченными

_contradictions_for (spike/T10/src/t10_business.py:527) сравнивает новые statements только с previous. propose_profile вызывает _contradictions_for(proposed, existing_statements) (строка 583), так что proposed claims не сравниваются между собой. apply_profile добавляет answer statements (строки 824-825), но не сверяет их с текущими statements.

Воспроизведение A: description «Запас сырья составляет 8 дней; Запас сырья составляет 12 дней.», existing=None. Предложение содержит inventory_cover values 8 и 12, contradictions=[].
Воспроизведение B: snapshot имеет inventory 8, Business.apply получает answered inventory value 12. Новый snapshot содержит оба значения, contradictions=[].
Ranker выявляет reconciliation через contradiction list, поэтому не предлагает сверку новых конфликтов. Тесты покрывают новый факт против уже сохранённого конфликта, но пропускают обе эти формы.

Короткий повтор A: задать PYTHONPATH=packages/contracts/src;spike/T10/src, создать тестовый EntityRef и TimeSlice на 2026-10-14, вызвать propose_profile(ProfileInput(company=company, description="Запас сырья составляет 8 дней; Запас сырья составляет 12 дней.", documents=[], answers=[], existing=None, as_of=as_of)); вывести inventory_cover values и proposal.contradictions. Фактический вывод: [8, 12] и [].

### MEDIUM — T10-R4: нет поддержки складов и услуг в профиле

Задача требует представлять, среди прочего, услуги и склады. В _EXTRACTOR_RULES (:297), _PATH_PREDICATES (:283) и _MISSING (:269) нет отдельных warehouse/service predicates, fields или questions. Набор покрывает лишь выбранные прямые фразы про торговлю, производство, компоненты, suppliers/countries, routes, processes, buyers и несколько scalar fields. Warehouse/service нельзя извлечь, сохранить как unknown или запросить. Узость упомянута в LIMITATIONS, но этот scope gap отдельно не обозначен; 22 shared cases не проверяют полноту по заявленным категориям.

## Подтверждённые поведения и границы

- «Мы продаём радиодетали» не генерирует supplier/country/volume/import-share claims; supplier остаётся unknown.
- «Мы можем закупать…» остаётся hypothetical.
- declined не становится отрицательным фактом и подавляет повторный supplier_names вопрос.
- На одном sparse-профиле export restriction поднимает supplier_names, port closure — route/inventory вопросы. Это ручная порядковая эвристика, не измеренный information gain.
- Answer с client origin_verified=true остаётся user_declared без evidence_refs, но флаг копируется. Статус не повышается; downstream обязан считать client flag недоверенным согласно 02-contracts.md:38.
- read_profile принимает только snapshots; ReceiptQuery возвращает receipt=null (строки 879-882). Реального receipt lookup нет. Это documented gap, однако Business.read поддержан не полностью.
- Несмотря на 79 passing tests, findings не позволяют объявить T10 integration ready.

## Команды

Тесты:

    $env:PYTHONPATH = 'packages/contracts/src;spike/T10/src;spike/T10/tests'
    & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T10/tests -q

Фактический результат: 79 passed in 0.18s.

Whitespace:

    git diff --check 6498182...ff24cc3

Результат: без замечаний.
