# Независимое ревью T12 Knowledge Graph

Дата: 2026-10-14
Проверенный HEAD: a0d4333bc7052e5359d79a473cdc65c1fe434d7a
Ветка: codex/review-t12-graph
Датасет: t09-t13-independent-v1 v1.0.1, provisional / not gold
Ревьюер не участвовал в реализации T12. Проверены исходники T12, Graph operation cards и DTO, тесты/отчёты, frozen dataset lock. Реализацию и fixtures не менял.

## Итог

Обнаружены два HIGH и три MEDIUM. Все HIGH воспроизведены локальными offline probes. Полный suite T12 проходит: 31 passed, 0 failed, 0 skipped. Это подтверждает выполнение имеющихся тестов, но не снимает найденные дефекты: текущие тесты не покрывают описанные случаи.

## HIGH

### T12-R1 — current_required пропускает свежесть всего графа при пустом required_slices

Места: spike/T12/src/t12_graph_spike/query.py:67-85, 161-165; нормативные правила: docs/specs/framework-v1/03-operations.md, Graph.query, правило current_required при stale/unknown; docs/specs/framework-v1/05-storage.md, правило scoped freshness.

Алгоритм сравнивает manifest/current только по ключам selection.required_slices. Если запрос требует пустой список и переданный materialized current_slices тоже пуст, changed остаётся пустым и результат помечается current. При этом запрос с seed_ids=[] возвращает узлы всего snapshot, а его manifest в общем fixture содержит три source slices. Отсутствующие source reads не отмечаются ни как missing, ни как unknown.

Воспроизведение: с build_shared_request() собрать candidate, выставить revision=1; вызвать query_graph с freshness_policy=current_required, required_slices=[], current_slices=[] и тем же as_of. Наблюдение: freshness=current, manifest.input_slices содержит 3 записи, подграф вернул весь snapshot. Ожидается fail closed как минимум со статусом unknown/VERSION_CONFLICT, пока current состояние зависимостей не проверено.

Минимальный исполняемый probe с теми же локальными зависимостями:

    $env:PYTHONPATH='spike/T12/src;packages/contracts/src;spike/T12/tests'
    @'
    import json
    from alfalab_contracts.models import QueryGraphInput
    from helpers import build_shared_request
    from t12_graph_spike import build_graph, default_graph_rules, query_graph
    request, refs, aggregates = build_shared_request()
    graph = build_graph(request, statement_ref_index=refs, aggregate_refs=aggregates,
                       rules=default_graph_rules(request.ontology)).output.candidate
    graph = graph.model_copy(update={"revision": 1})
    payload = {"query": {"kind": "subgraph", "graph_id": graph.graph_id,
        "revision": 1, "seed_ids": [], "relations": [], "max_depth": 5,
        "max_nodes": 100, "required_slices": [], "freshness_policy": "current_required",
        "as_of": graph.manifest.as_of.model_dump(mode="json")}}
    query = QueryGraphInput.model_validate_json(json.dumps(payload), strict=True)
    result = query_graph(query, snapshots={(graph.graph_id, 1): graph}, current_slices=[])
    print(result.subgraph.freshness, len(graph.manifest.input_slices),
          len(result.subgraph.snapshot.edges))
    '@ | & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -

    Вывод: current 3 15

### T12-R2 — Graph.publish принимает statement refs вне manifest.input_slices

Места: spike/T12/src/t12_graph_spike/store.py:72-84; operation contract: docs/specs/framework-v1/03-operations.md, Graph.publish, правило “Нельзя публиковать candidate с нарушенным manifest или references”; docs/specs/framework-v1/05-storage.md, Graph.publish валидирует manifest и references.

Publish сравнивает каждый candidate StatementRef с переданным source_statement_refs, но не проверяет, что его aggregate_ref включён в candidate.manifest.input_slices. Воспроизведённый кандидат получен штатным build_graph с 15 grounded edges, после чего у его manifest удалены все input_slices. publish принимает его с исходным точным source ref index: опубликованная revision содержит 15 edges и 0 объявленных source slices. Это теряет связь между используемыми утверждениями и freshness selection; query не может корректно проверить эти зависимости.

Воспроизведение: собрать штатный candidate, заменить manifest.input_slices на [], сформировать строгий Graph_publishRequest из approved Graph.publish envelope и вызвать IsolatedGraphStore.publish(request, source_statement_refs=refs). Наблюдение: публикация успешна; snapshot содержит 0 slices и 15 edge StatementRefs. Требуется отвергать candidate либо проверить все aggregate_ref относительно declared source slices и их точных immutable refs.

## MEDIUM

### T12-R3 — опубликованная immutable revision меняется через readback

Места: spike/T12/src/t12_graph_spike/store.py:101-105, 127-146; нормативная основа: docs/specs/framework-v1/03-operations.md, Graph.publish; docs/specs/framework-v1/05-storage.md, graph.projections immutable, replace by new version.

Внутренний GraphSnapshot хранится как изменяемый Pydantic object; snapshot() и snapshots() возвращают ту же ссылку. После publish изменение returned_snapshot.nodes[0].entity.display_name изменило сохранённую историю при следующем snapshot() чтении. При этом исходный projection_ref.hash уже не соответствует содержимому revision. Это локальная модель, не production DB, но она должна проверять заявленную immutable revision семантику.

Воспроизведение: после успешного publish выполнить saved = store.snapshot(graph_id, 1); saved.nodes[0].entity.display_name = "REVIEW-MUTATED"; повторный store.snapshot(graph_id, 1) возвращает REVIEW-MUTATED.

### T12-R4 — Statement со статусом disproved входит в графовый путь

Места: spike/T12/src/t12_graph_spike/core.py:339-363, 425-435; spike/T12/src/t12_graph_spike/query.py:92-128, 169-175.

Проекция отдельно отсеивает одну настроенную negative predicate, hypothetical и unknown, но не статус disproved. Statement с allowlisted положительным predicate и epistemic_status=disproved создаёт GraphEdge; bounded BFS учитывает edge без фильтра по статусу и возвращает его в подграфе как связанный путь. Статус остаётся видимым в DTO, поэтому это не безусловная потеря provenance, но downstream matching может ошибочно считать наличие пути exposure, если не добавит собственное gate-правило. Требуется явно согласовать/проверить семантику disproved, чтобы этот статус не участвовал как действующая зависимость.

Воспроизведение: в shared statement b-buys-microkaskad установить disproved, обновить точный StatementRef hash, собрать candidate и выполнить query от node-company-b на глубину 1. Наблюдение: edge-b-buys-microkaskad присутствует в GraphSubgraph.snapshot.edges со статусом disproved.

### T12-R5 — идентификатор edge не учитывает revision утверждения

Места: spike/T12/src/t12_graph_spike/core.py:282-300, 426; contracts: docs/specs/framework-v1/02-contracts.md, StatementRef содержит aggregate_ref, statement_id, revision и hash.

Ключи statement map используют statement_id/revision, а edge_id формируется только из statement_id. Две версии одного Statement ID допустимы формой Statement/StatementRef, но при включении обеих в один KnowledgeSnapshot дают одинаковые edge IDs; GraphSnapshot semantic validator отклоняет результат с “graph edge IDs must be unique”. В отдельном probe добавлена revision 2 для b-buys-microkaskad к revision 1 с корректным новым hash/ref: build завершился Pydantic ValidationError из-за повторного edge ID. Аналогично statement_ref_index не включает aggregate_ref в identity, хотя нормативный StatementRef идентифицируется внутри aggregate; одинаковые локальные ID/revision из разных owner aggregates нельзя адресовать раздельно. Контракт не задаёт глобальную уникальность statement_id и не запрещает несколько ревизий в KnowledgeSnapshot.

## Проверки, прошедшие без замечаний

- Положительный прямой edge создаётся только для allowlisted entity-valued assertion с точным StatementRef; hash statement и aggregate-to-slice membership проверяются при build.
- Near-name, parent и subsidiary IDs не сливаются и связи по сходству не создаются.
- Unknown, hypothetical и известная explicit-negative predicate не превращаются в положительное ребро; отрицание остаётся в sidecar с MissingDatum.
- Inferred edge сохраняет derivation method и входные StatementRefs; отсутствующие входные refs блокируют edge.
- valid_as_of и known_as_of применяются раздельно; late-recorded данные не попадают в историческую проекцию. Срез истории требует rebuild, что задокументировано как ограничение из-за GraphEdge DTO без validity interval.
- BFS ограничен max_depth/max_nodes, сортирует результаты и сохраняет направление edge. Отсутствие пути не записывается как отрицательная зависимость.
- Ревизии/идемпотентность store покрыты тестами на повтор receipt, ключ-конфликт и expected_revision conflict.
- T12 fixture lock и helper проверяют версию 1.0.1 и canonical dataset hash; fixture expectations остаются provisional/not gold. 15 T12 shared cases перечислены в TEST_REPORT.md.
- Импортный scan показал только stdlib и packages/contracts; в T12 src/tests/experiment нет HTTP/network, SQL/DB или model client imports. Core/query работают по явно переданным данным. Логируются graph_id и агрегированные counts, не source text.
- Framework contracts/OpenAPI/shared fixtures не менялись. Известные gaps для точной материализации StatementRef/ObjectRef, polarity и valid-time sidecar перечислены в spike/T12/LIMITATIONS.md; интеграционная готовность корректно отмечена NOT READY.

## Команды проверки

    $env:PYTHONPATH='spike/T12/src;packages/contracts/src;spike/T12/tests'
    & 'C:\Users\Артём\Documents\ChatGPT\Хакатон Альфабанк\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider spike/T12/tests -q --tb=short

Фактический результат: 31 passed, 0 failed, 0 skipped. Coverage не измерялось. Отдельные тесты выполняют строгую проверку обменов Graph.build, Graph.publish и Graph.query против pinned operation registry. Shared validator в рамках этого T12 review повторно не запускался; dataset v1.0.1 уже прошёл отдельный независимый review.

Код review-skill обычно запускает standards/spec оси двумя параллельными субагентами. Второго reviewer-agent не запускал: общий лимит в 4 активных слота занят координатором, агентом T11/T13, владельцем frozen dataset и этим reviewer. Это ограничение процесса, а не автора T12.

## Оценка качества

- Engineering: suite и контрактные exchange checks проходят; локальные HIGH/MEDIUM probes выявили пропуски вне существующих тестов.
- Algorithm: PRELIMINARY. Синтетические проверки подтверждают только эти свойства; gold labels и реальная сеть поставок не использовались.
- Integration readiness: NOT READY. Нужно исправить или согласовать HIGH/MEDIUM findings, а также закрыть уже задокументированные DTO/reference/time/polarity gaps.
- Live model quality: NOT MEASURED; модельных вызовов нет.
