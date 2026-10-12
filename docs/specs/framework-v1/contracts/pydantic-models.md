# Декларативные Pydantic-модели v1.0

Это декларация ожидаемого отображения OpenAPI schemas в исполняемые Pydantic-типы; исходным нормативным источником остаётся `openapi.json`. T01 реализует Object schema отдельной моделью с `extra=forbid`. Scalar coercion запрещён; JSON timestamps валидируются как UTC strings, datetime conversion внутри implementation явно. Nullable поле обязательно, если входит в required. oneOf с kind/mode → discriminated union. Остальные oneOf требуют эксклюзивных вариантов. Межполевые validators — в 02-contracts.md и карточках операций; их код находится в `packages/contracts`.

## Identifier

Тип: `str`. Ограничения: minLength=1; maxLength=120; pattern="^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,119}$".

## Version

Тип: `str`. Ограничения: minLength=1; maxLength=40; pattern="^[0-9]+\\.[0-9]+\\.[0-9]+$".

## Hash

Тип: `str`. Ограничения: minLength=71; maxLength=71; pattern="^sha256:[0-9a-f]{64}$".

## Timestamp

Тип: `str`. Ограничения: minLength=1; maxLength=40; format="date-time"; pattern="(Z|\\+00:00)$".

## DecimalString

Тип: `str`. Ограничения: minLength=1; maxLength=80; pattern="^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$".

## SafeText

Тип: `str`. Ограничения: minLength=0; maxLength=2000.

## VersionedRef

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| id | Identifier | да | — |
| version | Version | да | — |
| hash | Hash | да | — |

## ObjectRef

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| owner | Literal['Documents', 'Events', 'Business', 'Graph', 'Evidence', 'Runs', 'Cases'] | да | — |
| object_id | Identifier | да | — |
| revision | StrictInt | да | minimum=1; maximum=2147483647 |
| hash | Hash | да | — |

## StatementRef

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| aggregate_ref | ObjectRef | да | — |
| statement_id | Identifier | да | — |
| revision | StrictInt | да | minimum=1; maximum=2147483647 |
| hash | Hash | да | — |

## EntityRef

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| entity_id | Identifier | да | — |
| kind | VersionedRef | да | — |
| display_name | str | да | minLength=1; maxLength=300 |

## CodeRef

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| namespace | Identifier | да | — |
| version | Version | да | — |
| code | Identifier | да | — |

## TimeSlice

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| valid_as_of | Timestamp | да | — |
| known_as_of | Timestamp | да | — |

## Validity

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| valid_from | Timestamp \| None | да | — |
| valid_to | Timestamp \| None | да | — |
| recorded_at | Timestamp | да | — |

## MissingDatum

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| path | str | да | minLength=1; maxLength=300 |
| reason | Literal['not_provided', 'not_observed', 'contradictory', 'unsupported', 'unavailable'] | да | — |
| detail | SafeText | да | — |

## Provenance

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| origin | Literal['public_source', 'user_declared', 'synthetic', 'derived', 'unknown'] | да | — |
| source_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| input_statement_refs | list[StatementRef] | да | minItems=0; maxItems=1000 |
| producer_run_id | Identifier \| None | да | — |
| derivation_method | VersionedRef \| None | да | — |
| evidence_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| origin_verified | StrictBool | да | — |

## LineageSummary

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| synthetic_source | StrictBool | да | — |
| mock_derivation | StrictBool | да | — |
| unknown_origin | StrictBool | да | — |
| source_refs | list[ObjectRef] | да | minItems=0; maxItems=1000 |

## TextValue

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['text'] | да | — |
| value | str | да | minLength=0; maxLength=5000 |

## NumberValue

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['number'] | да | — |
| value | DecimalString | да | — |
| unit | CodeRef \| None | да | — |

## BooleanValue

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['boolean'] | да | — |
| value | StrictBool | да | — |

## EntityValue

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['entity'] | да | — |
| value | EntityRef | да | — |

## TimeValue

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['time'] | да | — |
| value | Timestamp | да | — |

## UnknownValue

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['unknown'] | да | — |
| reason | SafeText | да | — |

## TypedValue

Тип: `TextValue | NumberValue | BooleanValue | EntityValue | TimeValue | UnknownValue`. Ограничения: —.

## Statement

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| statement_id | Identifier | да | — |
| revision | StrictInt | да | minimum=1; maximum=2147483647 |
| subject | EntityRef | да | — |
| predicate | CodeRef | да | — |
| value | TypedValue | да | — |
| epistemic_status | Literal['confirmed', 'user_declared', 'observed', 'inferred', 'hypothetical', 'disputed', 'disproved', 'unknown'] | да | — |
| validity | Validity | да | — |
| provenance | Provenance | да | — |

## Contradiction

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| statement_ids | list[Identifier] | да | minItems=2; maxItems=100 |
| reason | SafeText | да | — |

## KnowledgeSlice

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| owner | Literal['Events', 'Business', 'Documents', 'Reference'] | да | — |
| partition_id | Identifier | да | — |
| revision | StrictInt | да | minimum=0; maximum=2147483647 |
| selection_key | Identifier | да | — |

## ArtifactRef

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| artifact_id | Identifier | да | — |
| hash | Hash | да | — |
| schema_id | Identifier | да | — |
| schema_version | Version | да | — |
| size_bytes | StrictInt | да | minimum=0; maximum=2097152 |
| classification | Literal['synthetic', 'public', 'unknown'] | да | — |
| media_type | Literal['application/json', 'text/plain'] | да | — |

## ArtifactView

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| ref | ArtifactRef | да | — |
| content_json | str \| None | да | — |
| availability | Literal['available', 'metadata_only', 'missing', 'policy_denied'] | да | — |

## RawMaterial

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| material_id | Identifier | да | — |
| source_id | Identifier \| None | да | — |
| source_url | str \| None | да | — |
| title | str | да | minLength=0; maxLength=500 |
| text | str | да | minLength=0; maxLength=200000 |
| published_at | Timestamp \| None | да | — |
| collected_at | Timestamp | да | — |
| content_hash | Hash | да | — |
| language | Literal['ru', 'en', 'other', 'unknown'] | да | — |
| provenance | Provenance | да | — |

## SpanMap

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| prepared_start | StrictInt | да | minimum=0; maximum=200000 |
| prepared_end | StrictInt | да | minimum=0; maximum=200000 |
| raw_start | StrictInt | да | minimum=0; maximum=200000 |
| raw_end | StrictInt | да | minimum=0; maximum=200000 |

## PreparedMaterial

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| material | RawMaterial | да | — |
| raw_hash | Hash | да | — |
| prepared_hash | Hash | да | — |
| quality | Literal['valid', 'review', 'rejected'] | да | — |
| span_map | list[SpanMap] | да | minItems=0; maxItems=200000 |
| warnings | list[SafeText] | да | minItems=0; maxItems=100 |

## DocumentVersion

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| ref | ObjectRef | да | — |
| kind | Literal['raw', 'prepared'] | да | — |
| raw | RawMaterial | да | — |
| prepared | PreparedMaterial \| None | да | — |
| parent_ref | ObjectRef \| None | да | — |

## TextSpan

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['text_span'] | да | — |
| start | StrictInt | да | minimum=0; maximum=200000 |
| end | StrictInt | да | minimum=0; maximum=200000 |
| quote_hash | Hash | да | — |

## WholeArtifact

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['whole_artifact'] | да | — |

## EvidenceLocator

Тип: `TextSpan | WholeArtifact`. Ограничения: —.

## EvidenceRecord

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| ref | ObjectRef | да | — |
| source_ref | ObjectRef | да | — |
| locator | EvidenceLocator | да | — |
| source_hash | Hash | да | — |
| verification | Literal['verified_anchor', 'unverified'] | да | — |
| source_reliability | Literal['unassessed', 'low', 'medium', 'high', 'disputed'] | да | — |
| reliability_method | VersionedRef \| None | да | — |

## EvidenceSpan

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| local_id | Identifier | да | — |
| material_hash | Hash | да | — |
| locator | TextSpan | да | — |
| claim_ids | list[Identifier] | да | minItems=0; maxItems=100 |

## TopicScore

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| code | CodeRef | да | — |
| raw_score | float (finite) \| None | да | — |
| score_method | VersionedRef \| None | да | — |
| calibrated | StrictBool | да | — |

## EventMention

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| mention_id | Identifier | да | — |
| event_type | CodeRef | да | — |
| actors | list[EntityRef] | да | minItems=0; maxItems=100 |
| objects | list[EntityRef] | да | minItems=0; maxItems=100 |
| statements | list[Statement] | да | minItems=0; maxItems=1000 |
| effective_at | Timestamp \| None | да | — |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=100 |
| provenance | Provenance | да | — |

## EventRecord

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| ref | ObjectRef | да | — |
| event_type | CodeRef | да | — |
| lifecycle | Literal['active', 'merged', 'split'] | да | — |
| statements | list[Statement] | да | minItems=0; maxItems=1000 |
| mention_ids | list[Identifier] | да | minItems=0; maxItems=1000 |
| lineage_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=100 |

## EventSnapshot

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| events | list[EventRecord] | да | minItems=0; maxItems=1000 |
| slice | KnowledgeSlice | да | — |
| as_of | TimeSlice | да | — |

## EventDecision

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| action | Literal['create', 'attach', 'correct', 'merge', 'split', 'defer'] | да | — |
| mention_ids | list[Identifier] | да | minItems=0; maxItems=1000 |
| target_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| proposed_events | list[EventRecord] | да | minItems=0; maxItems=100 |
| reason | SafeText | да | — |
| evidence_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |

## EventChangeProposal

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| proposal_id | Identifier | да | — |
| source_snapshot | KnowledgeSlice | да | — |
| decisions | list[EventDecision] | да | minItems=0; maxItems=1000 |
| unresolved_mentions | list[Identifier] | да | minItems=0; maxItems=1000 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=100 |
| provenance | Provenance | да | — |

## QuestionPreferences

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| max_questions | StrictInt | да | minimum=0; maximum=10 |
| allow_event_prompts | StrictBool | да | — |
| suppressed_targets | list[Identifier] | да | minItems=0; maxItems=100 |

## QuestionProposal

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| question_id | Identifier | да | — |
| target | CodeRef | да | — |
| text | str | да | minLength=1; maxLength=1000 |
| why | SafeText | да | — |
| options | list[TextValue] | да | minItems=0; maxItems=20 |
| can_skip | StrictBool | да | — |
| priority | Literal['low', 'medium', 'high'] | да | — |

## QuestionAnswer

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| question_id | Identifier | да | — |
| status | Literal['answered', 'skipped', 'declined', 'unknown'] | да | — |
| value | TypedValue \| None | да | — |
| provenance | Provenance | да | — |

## BusinessSnapshot

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| ref | ObjectRef | да | — |
| company | EntityRef | да | — |
| statements | list[Statement] | да | minItems=0; maxItems=10000 |
| contradictions | list[Contradiction] | да | minItems=0; maxItems=1000 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=1000 |
| answers | list[QuestionAnswer] | да | minItems=0; maxItems=1000 |
| preferences | QuestionPreferences | да | — |
| slice | KnowledgeSlice | да | — |
| as_of | TimeSlice | да | — |

## ProfileChangeProposal

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| proposal_id | Identifier | да | — |
| company | EntityRef | да | — |
| expected_revision | StrictInt | да | minimum=0; maximum=2147483647 |
| add_statements | list[Statement] | да | minItems=0; maxItems=10000 |
| supersede_refs | list[StatementRef] | да | minItems=0; maxItems=1000 |
| contradictions | list[Contradiction] | да | minItems=0; maxItems=1000 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=1000 |
| provenance | Provenance | да | — |

## GraphNode

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| node_id | Identifier | да | — |
| entity | EntityRef | да | — |
| statement_refs | list[StatementRef] | да | minItems=0; maxItems=1000 |
| provenance | Provenance | да | — |

## GraphEdge

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| edge_id | Identifier | да | — |
| source_node_id | Identifier | да | — |
| target_node_id | Identifier | да | — |
| relation | CodeRef | да | — |
| epistemic_status | Literal['confirmed', 'user_declared', 'observed', 'inferred', 'hypothetical', 'disputed', 'disproved', 'unknown'] | да | — |
| statement_refs | list[StatementRef] | да | minItems=0; maxItems=1000 |
| evidence_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| provenance | Provenance | да | — |

## ProjectionManifest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| ontology | VersionedRef | да | — |
| rules | VersionedRef | да | — |
| input_slices | list[KnowledgeSlice] | да | minItems=0; maxItems=1000 |
| as_of | TimeSlice | да | — |
| builder | VersionedRef | да | — |
| config_hash | Hash | да | — |

## GraphSnapshot

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| graph_id | Identifier | да | — |
| revision | StrictInt | да | minimum=0; maximum=2147483647 |
| nodes | list[GraphNode] | да | minItems=0; maxItems=10000 |
| edges | list[GraphEdge] | да | minItems=0; maxItems=20000 |
| manifest | ProjectionManifest | да | — |
| completeness | Literal['complete_for_declared_slice', 'partial', 'unknown'] | да | — |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=1000 |

## GraphSubgraph

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| snapshot | GraphSnapshot | да | — |
| freshness | Literal['current', 'stale', 'historical', 'unknown'] | да | — |
| missing_slices | list[KnowledgeSlice] | да | minItems=0; maxItems=1000 |
| traversal_truncated | StrictBool | да | — |
| query_scope | list[Identifier] | да | minItems=0; maxItems=1000 |

## KnowledgeSnapshot

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| statements | list[Statement] | да | minItems=0; maxItems=10000 |
| entities | list[EntityRef] | да | minItems=0; maxItems=10000 |
| slices | list[KnowledgeSlice] | да | minItems=0; maxItems=1000 |
| evidence | list[EvidenceRecord] | да | minItems=0; maxItems=10000 |
| as_of | TimeSlice | да | — |

## Match

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| match_id | Identifier | да | — |
| event_ref | ObjectRef | да | — |
| company | EntityRef | да | — |
| exposure | Literal['confirmed', 'potential', 'none_found', 'unknown'] | да | — |
| affected_components | list[Identifier] | да | minItems=0; maxItems=1000 |
| edge_paths | list[list[Identifier]] | да | minItems=0; maxItems=100 |
| evidence_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=100 |
| provenance | Provenance | да | — |

## AnalyticalConfidence

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| level | Literal['low', 'medium', 'high', 'unknown'] | да | — |
| method | VersionedRef \| None | да | — |
| limitations | list[SafeText] | да | minItems=0; maxItems=100 |

## FinancialScenario

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| scenario_id | Identifier | да | — |
| quantity | NumberValue \| None | да | — |
| assumptions | list[Statement] | да | minItems=0; maxItems=100 |
| calculation_method | VersionedRef | да | — |
| input_refs | list[StatementRef] | да | minItems=0; maxItems=100 |

## ImpactAssessment

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| assessment_id | Identifier | да | — |
| event_ref | ObjectRef | да | — |
| company | EntityRef | да | — |
| graph_manifest | ProjectionManifest | да | — |
| exposure | Literal['confirmed', 'potential', 'none_found', 'unknown'] | да | — |
| likelihood | Literal['likely', 'possible', 'unlikely', 'unknown'] | да | — |
| direction | Literal['negative', 'positive', 'mixed', 'neutral', 'unknown'] | да | — |
| materiality | Literal['high', 'medium', 'low', 'unknown'] | да | — |
| mechanisms | list[CodeRef] | да | minItems=0; maxItems=100 |
| assumptions | list[Statement] | да | minItems=0; maxItems=100 |
| scenarios | list[FinancialScenario] | да | minItems=0; maxItems=100 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=1000 |
| evidence_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| confidence | AnalyticalConfidence | да | — |
| provenance | Provenance | да | — |

## Recommendation

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| recommendation_id | Identifier | да | — |
| assessment_id | Identifier | да | — |
| action_type | CodeRef | да | — |
| title | str | да | minLength=1; maxLength=300 |
| why | SafeText | да | — |
| priority | Literal['low', 'medium', 'high'] | да | — |
| conditions | list[SafeText] | да | minItems=0; maxItems=100 |
| requires_approval | StrictBool | да | — |
| evidence_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |
| provenance | Provenance | да | — |

## TargetRevision

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| object_id | Identifier | да | — |
| expected_revision | StrictInt | да | minimum=0; maximum=2147483647 |

## CommandReceipt

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| operation_id | Identifier | да | — |
| idempotency_key | Identifier | да | — |
| command_hash | Hash | да | — |
| applied | StrictBool | да | — |
| changed_refs | list[ObjectRef] | да | minItems=0; maxItems=1000 |
| audit_id | Identifier | да | — |
| committed_at | Timestamp | да | — |
| original_run_id | Identifier | да | — |

## ReceiptQuery

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['receipt'] | да | — |
| operation_id | Identifier | да | — |
| idempotency_key | Identifier | да | — |

## ReceiptResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['receipt'] | да | — |
| receipt | CommandReceipt \| None | да | — |

## DependencyRecord

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| sequence | StrictInt | да | minimum=0; maximum=2147483647 |
| port_id | Identifier | да | — |
| kind | Literal['model', 'source', 'owner_read', 'clock', 'random'] | да | — |
| request | ArtifactView | да | — |
| response | ArtifactView \| None | да | — |
| error | ErrorInfo \| None | да | — |
| duration_ms | StrictInt | да | minimum=0; maximum=2147483647 |
| request_hash | Hash | да | — |
| substitution | Literal['live', 'replay'] | да | — |
| original_run_id | Identifier \| None | да | — |

## SpanRecord

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| sequence | StrictInt | да | minimum=0; maximum=2147483647 |
| span_id | Identifier | да | — |
| parent_span_id | Identifier \| None | да | — |
| name | Identifier | да | — |
| kind | Literal['operation', 'dependency', 'validation', 'policy', 'storage', 'binding'] | да | — |
| started_at | Timestamp | да | — |
| duration_ms | StrictInt | да | minimum=0; maximum=2147483647 |
| status | Literal['success', 'partial', 'error', 'cancelled', 'unknown'] | да | — |
| safe_detail | SafeText | да | — |

## Measurement

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| name | Identifier | да | — |
| value | DecimalString \| None | да | — |
| unit | str | да | minLength=1; maxLength=40 |
| basis | Literal['measured', 'estimated', 'unknown'] | да | — |

## ModelIdentity

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| provider_id | Identifier | да | — |
| model_id | Identifier | да | — |
| provider_revision | str \| None | да | — |
| unknown_revision_reason | SafeText \| None | да | — |
| configuration_hash | Hash | да | — |
| prompt | VersionedRef \| None | да | — |

## StateCapture

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| owner | Literal['Documents', 'Events', 'Business', 'Graph', 'Evidence', 'Cases'] | да | — |
| before | ArtifactRef | да | — |
| after | ArtifactRef \| None | да | — |
| before_hash | Hash | да | — |
| after_hash | Hash \| None | да | — |

## DataPolicyDecision

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| policy | VersionedRef | да | — |
| classification | Literal['synthetic', 'public', 'unknown'] | да | — |
| processing_allowed | StrictBool | да | — |
| egress_allowed | StrictBool | да | — |
| recording | Literal['full', 'metadata_only'] | да | — |
| export_allowed | StrictBool | да | — |
| reason_codes | list[Identifier] | да | minItems=0; maxItems=100 |

## RunManifest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_hash | Hash | да | — |
| envelope_version | Version | да | — |
| hash_format | Literal['canonical-json-v1'] | да | — |
| implementation | VersionedRef | да | — |
| configuration | ArtifactView | да | — |
| models | list[ModelIdentity] | да | minItems=0; maxItems=100 |
| prompts | list[VersionedRef] | да | minItems=0; maxItems=100 |
| taxonomies | list[VersionedRef] | да | minItems=0; maxItems=100 |
| ontologies | list[VersionedRef] | да | minItems=0; maxItems=100 |
| rules | list[VersionedRef] | да | minItems=0; maxItems=100 |
| bindings | list[VersionedRef] | да | minItems=0; maxItems=100 |
| scenario | VersionedRef \| None | да | — |
| runtime_lock_hash | Hash | да | — |
| runtime_build_hash | Hash | да | — |
| platform | str | да | minLength=1; maxLength=120 |
| analytical_time | Timestamp | да | — |
| random_seed | StrictInt | да | minimum=0; maximum=2147483647 |
| recording | Literal['full', 'metadata_only'] | да | — |
| state_capture | StateCapture \| None | да | — |
| replay_of | Identifier \| None | да | — |
| data_classification | Literal['synthetic', 'public', 'unknown'] | да | — |
| data_policy | DataPolicyDecision | да | — |

## StepCheckpoint

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| scenario | VersionedRef | да | — |
| scenario_run_id | Identifier | да | — |
| step_id | Identifier | да | — |
| run_id | Identifier | да | — |
| input_hash | Hash | да | — |
| output_hash | Hash \| None | да | — |
| binding | VersionedRef | да | — |
| implementation | VersionedRef | да | — |
| configuration_hash | Hash | да | — |
| source_slices | list[KnowledgeSlice] | да | minItems=0; maxItems=1000 |
| receipt | CommandReceipt \| None | да | — |
| status | Literal['completed', 'skipped', 'failed', 'unknown'] | да | — |

## RunRecord

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| run_id | Identifier | да | — |
| operation_id | Identifier | да | — |
| contract_version | Version | да | — |
| implementation | VersionedRef | да | — |
| configuration_hash | Hash | да | — |
| manifest | RunManifest | да | — |
| scenario | VersionedRef \| None | да | — |
| parent_run_id | Identifier \| None | да | — |
| status | Literal['running', 'success', 'partial', 'abstained', 'failed', 'cancelled', 'unknown'] | да | — |
| input | ArtifactView \| None | да | — |
| output | ArtifactView \| None | да | — |
| dependencies | list[DependencyRecord] | да | minItems=0; maxItems=10000 |
| spans | list[SpanRecord] | да | minItems=0; maxItems=10000 |
| measurements | list[Measurement] | да | minItems=0; maxItems=100 |
| lineage | LineageSummary | да | — |
| trace_status | Literal['complete', 'partial', 'metadata_only'] | да | — |
| replay_status | Literal['available', 'incomplete', 'unavailable'] | да | — |
| analytical_time | Timestamp | да | — |
| random_seed | StrictInt | да | minimum=0; maximum=2147483647 |
| runtime_build_hash | Hash | да | — |

## CaseRecord

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| ref | ObjectRef | да | — |
| title | str | да | minLength=1; maxLength=300 |
| source_run_id | Identifier | да | — |
| run | RunRecord | да | — |
| tags | list[Identifier] | да | minItems=0; maxItems=50 |
| approval | Literal['draft'] | да | — |

## ObservedResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| run_id | Identifier | да | — |
| input_hash | Hash | да | — |
| implementation | VersionedRef | да | — |
| output | ArtifactView | да | — |

## ExactExpectation

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['exact'] | да | — |
| expected | ArtifactView | да | — |
| ignored_paths | list[str] | да | minItems=0; maxItems=100 |

## PropertyExpectation

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['property'] | да | — |
| path | str | да | minLength=1; maxLength=300 |
| operator | Literal['exists', 'equals', 'contains', 'nonempty'] | да | — |
| expected | TypedValue \| None | да | — |

## FactExpectation

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['facts'] | да | — |
| required_fact_ids | list[Identifier] | да | minItems=0; maxItems=1000 |
| forbidden_fact_ids | list[Identifier] | да | minItems=0; maxItems=1000 |
| minimum_f1 | float (finite) | да | minimum=0; maximum=1 |

## Expectation

Тип: `ExactExpectation | PropertyExpectation | FactExpectation`. Ограничения: —.

## MetricResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| name | Identifier | да | — |
| value | DecimalString \| None | да | — |
| passed | StrictBool \| None | да | — |
| method | VersionedRef | да | — |
| detail | SafeText | да | — |

## EvaluationReport

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| evaluation_id | Identifier | да | — |
| run_ids | list[Identifier] | да | minItems=0; maxItems=100 |
| comparable | StrictBool | да | — |
| metrics | list[MetricResult] | да | minItems=0; maxItems=1000 |
| limitations | list[SafeText] | да | minItems=0; maxItems=100 |

## FetchInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| source_id | Identifier | да | — |
| cursor | str \| None | да | — |
| since | Timestamp \| None | да | — |
| limit | StrictInt | да | minimum=1; maximum=100 |

## FetchOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| materials | list[RawMaterial] | да | minItems=0; maxItems=100 |
| next_cursor | str \| None | да | — |
| warnings | list[SafeText] | да | minItems=0; maxItems=100 |

## PrepareInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| material | RawMaterial | да | — |
| normalize_newlines | StrictBool | да | — |
| trim_outer_whitespace | StrictBool | да | — |

## PrepareOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| prepared | PreparedMaterial | да | — |

## RegisterDocumentInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| document_id | Identifier | да | — |
| expected_revision | StrictInt | да | minimum=0; maximum=2147483647 |
| raw | RawMaterial | да | — |
| prepared | PreparedMaterial \| None | да | — |

## RegisterDocumentOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| version | DocumentVersion | да | — |
| receipt | CommandReceipt | да | — |

## DocumentSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['documents'] | да | — |
| document_ids | list[Identifier] | да | minItems=1; maxItems=100 |
| revision | StrictInt \| None | да | — |
| as_of | TimeSlice \| None | да | — |

## DocumentQuery

Тип: `DocumentSelection | ReceiptQuery`. Ограничения: —.

## ReadDocumentsInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| query | DocumentQuery | да | — |

## DocumentResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['documents'] | да | — |
| versions | list[DocumentVersion] | да | minItems=0; maxItems=100 |
| missing_ids | list[Identifier] | да | minItems=0; maxItems=100 |

## ReadDocumentsOutput

Тип: `DocumentResult | ReceiptResult`. Ограничения: —.

## ClassificationInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| material | PreparedMaterial | да | — |
| taxonomy | VersionedRef | да | — |
| allowed_codes | list[CodeRef] | да | minItems=1; maxItems=1000 |
| multi_label | StrictBool | да | — |

## ClassificationOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| topics | list[TopicScore] | да | minItems=0; maxItems=1000 |
| event_hints | list[CodeRef] | да | minItems=0; maxItems=1000 |
| classification_status | Literal['classified', 'uncertain', 'other', 'no_content'] | да | — |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=100 |

## ExtractionInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| material | PreparedMaterial | да | — |
| event_schema | VersionedRef | да | — |
| hints | list[CodeRef] | да | minItems=0; maxItems=1000 |
| known_entities | list[EntityRef] | да | minItems=0; maxItems=1000 |

## ExtractionOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| mentions | list[EventMention] | да | minItems=0; maxItems=1000 |
| evidence_spans | list[EvidenceSpan] | да | minItems=0; maxItems=10000 |
| unresolved_entities | list[EntityRef] | да | minItems=0; maxItems=1000 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=1000 |

## ResolutionInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| mentions | list[EventMention] | да | minItems=0; maxItems=1000 |
| existing | EventSnapshot | да | — |
| evidence | list[EvidenceRecord] | да | minItems=0; maxItems=10000 |
| policy | VersionedRef | да | — |

## ResolutionOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| proposal | EventChangeProposal | да | — |

## ApplyEventsInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| proposal | EventChangeProposal | да | — |
| expected_revisions | list[TargetRevision] | да | minItems=0; maxItems=1000 |
| evidence | list[EvidenceRecord] | да | minItems=0; maxItems=10000 |

## ApplyEventsOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| snapshot | EventSnapshot | да | — |
| receipt | CommandReceipt | да | — |

## EventSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['events'] | да | — |
| event_ids | list[Identifier] | да | minItems=0; maxItems=1000 |
| partition_id | Identifier | да | — |
| as_of | TimeSlice | да | — |
| limit | StrictInt | да | minimum=1; maximum=100 |
| cursor | str \| None | да | — |

## EventQuery

Тип: `EventSelection | ReceiptQuery`. Ограничения: —.

## ReadEventsInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| query | EventQuery | да | — |

## EventResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['events'] | да | — |
| snapshot | EventSnapshot | да | — |
| next_cursor | str \| None | да | — |

## ReadEventsOutput

Тип: `EventResult | ReceiptResult`. Ограничения: —.

## ProfileInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| company | EntityRef | да | — |
| description | str | да | minLength=0; maxLength=200000 |
| documents | list[RawMaterial] | да | minItems=0; maxItems=100 |
| answers | list[QuestionAnswer] | да | minItems=0; maxItems=1000 |
| existing | BusinessSnapshot \| None | да | — |
| as_of | TimeSlice | да | — |

## ProfileOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| proposal | ProfileChangeProposal | да | — |

## QuestionsInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| profile | BusinessSnapshot | да | — |
| event | EventRecord \| None | да | — |
| question_history | list[QuestionAnswer] | да | minItems=0; maxItems=1000 |
| budget | StrictInt | да | minimum=0; maximum=10 |

## QuestionsOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| questions | list[QuestionProposal] | да | minItems=0; maxItems=10 |
| stop_reason | Literal['budget', 'complete', 'declined', 'no_useful_question', 'proposed'] | да | — |

## ApplyBusinessInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| proposal | ProfileChangeProposal | да | — |
| answers | list[QuestionAnswer] | да | minItems=0; maxItems=1000 |
| preferences | QuestionPreferences \| None | да | — |
| evidence | list[EvidenceRecord] | да | minItems=0; maxItems=10000 |

## ApplyBusinessOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| snapshot | BusinessSnapshot | да | — |
| receipt | CommandReceipt | да | — |

## BusinessSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['business'] | да | — |
| company_id | Identifier | да | — |
| revision | StrictInt \| None | да | — |
| as_of | TimeSlice \| None | да | — |

## BusinessQuery

Тип: `BusinessSelection | ReceiptQuery`. Ограничения: —.

## ReadBusinessInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| query | BusinessQuery | да | — |

## BusinessResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['business'] | да | — |
| snapshot | BusinessSnapshot \| None | да | — |

## ReadBusinessOutput

Тип: `BusinessResult | ReceiptResult`. Ограничения: —.

## BuildGraphInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| graph_id | Identifier | да | — |
| knowledge | KnowledgeSnapshot | да | — |
| ontology | VersionedRef | да | — |
| rules | VersionedRef | да | — |

## BuildGraphOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| candidate | GraphSnapshot | да | — |

## PublishGraphInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| candidate | GraphSnapshot | да | — |
| expected_revision | StrictInt | да | minimum=0; maximum=2147483647 |

## PublishGraphOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| projection_ref | ObjectRef | да | — |
| receipt | CommandReceipt | да | — |

## SubgraphSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['subgraph'] | да | — |
| graph_id | Identifier | да | — |
| revision | StrictInt | да | minimum=1; maximum=2147483647 |
| seed_ids | list[Identifier] | да | minItems=0; maxItems=1000 |
| relations | list[CodeRef] | да | minItems=0; maxItems=100 |
| max_depth | StrictInt | да | minimum=0; maximum=5 |
| max_nodes | StrictInt | да | minimum=1; maximum=10000 |
| required_slices | list[KnowledgeSlice] | да | minItems=0; maxItems=1000 |
| freshness_policy | Literal['current_required', 'allow_stale', 'historical'] | да | — |
| as_of | TimeSlice | да | — |

## GraphQuery

Тип: `SubgraphSelection | ReceiptQuery`. Ограничения: —.

## QueryGraphInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| query | GraphQuery | да | — |

## SubgraphResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['subgraph'] | да | — |
| subgraph | GraphSubgraph \| None | да | — |

## QueryGraphOutput

Тип: `SubgraphResult | ReceiptResult`. Ограничения: —.

## MatchingInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| event | EventRecord | да | — |
| graph | GraphSubgraph | да | — |
| profiles | list[BusinessSnapshot] | да | minItems=0; maxItems=1000 |
| mode | Literal['strict', 'balanced', 'broad'] | да | — |
| limit | StrictInt | да | minimum=1; maximum=100 |

## MatchingOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| matches | list[Match] | да | minItems=0; maxItems=100 |
| candidate_scope | list[Identifier] | да | minItems=0; maxItems=1000 |
| search_complete_for_scope | StrictBool | да | — |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=1000 |

## ImpactInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| event | EventRecord | да | — |
| profile | BusinessSnapshot | да | — |
| match | Match | да | — |
| graph | GraphSubgraph | да | — |
| evidence | list[EvidenceRecord] | да | minItems=0; maxItems=10000 |
| rules | VersionedRef \| None | да | — |
| as_of | TimeSlice | да | — |

## ImpactOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| assessment | ImpactAssessment | да | — |

## ActionDefinition

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| code | CodeRef | да | — |
| title | str | да | minLength=1; maxLength=300 |
| audiences | list[Literal['entrepreneur', 'bank_manager', 'analyst']] | да | minItems=1; maxItems=3 |
| requires_approval | StrictBool | да | — |

## RecommendationInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| assessment | ImpactAssessment | да | — |
| audience | Literal['entrepreneur', 'bank_manager', 'analyst'] | да | — |
| allowed_actions | list[ActionDefinition] | да | minItems=0; maxItems=100 |
| constraints | list[SafeText] | да | minItems=0; maxItems=100 |

## RecommendationOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| recommendations | list[Recommendation] | да | minItems=0; maxItems=100 |
| missing_data | list[MissingDatum] | да | minItems=0; maxItems=100 |

## RegisterEvidenceInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| evidence_id | Identifier | да | — |
| expected_revision | StrictInt | да | minimum=0; maximum=2147483647 |
| source_ref | ObjectRef | да | — |
| locator | EvidenceLocator | да | — |

## RegisterEvidenceOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| evidence | EvidenceRecord | да | — |
| receipt | CommandReceipt | да | — |

## EvidenceSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['evidence'] | да | — |
| refs | list[ObjectRef] | да | minItems=1; maxItems=100 |
| include_source_text | StrictBool | да | — |

## EvidenceQuery

Тип: `EvidenceSelection | ReceiptQuery`. Ограничения: —.

## ReadEvidenceInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| query | EvidenceQuery | да | — |

## EvidenceResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['evidence'] | да | — |
| records | list[EvidenceRecord] | да | minItems=0; maxItems=100 |
| source_artifacts | list[ArtifactView] | да | minItems=0; maxItems=100 |
| missing_refs | list[ObjectRef] | да | minItems=0; maxItems=100 |

## ReadEvidenceOutput

Тип: `EvidenceResult | ReceiptResult`. Ограничения: —.

## QueryRunsInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| run_ids | list[Identifier] | да | minItems=0; maxItems=100 |
| operation_id | Identifier \| None | да | — |
| scenario_id | Identifier \| None | да | — |
| include_artifacts | StrictBool | да | — |
| limit | StrictInt | да | minimum=1; maximum=100 |
| cursor | str \| None | да | — |

## QueryRunsOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| runs | list[RunRecord] | да | minItems=0; maxItems=100 |
| next_cursor | str \| None | да | — |

## SaveCaseInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| case_id | Identifier | да | — |
| expected_revision | StrictInt | да | minimum=0; maximum=2147483647 |
| source_run_id | Identifier | да | — |
| title | str | да | minLength=1; maxLength=300 |
| tags | list[Identifier] | да | minItems=0; maxItems=50 |

## SaveCaseOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| case | CaseRecord | да | — |
| receipt | CommandReceipt | да | — |

## CaseSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['cases'] | да | — |
| case_ids | list[Identifier] | да | minItems=0; maxItems=100 |
| revision | StrictInt \| None | да | — |
| tags | list[Identifier] | да | minItems=0; maxItems=50 |
| include_artifacts | StrictBool | да | — |
| limit | StrictInt | да | minimum=1; maximum=100 |
| cursor | str \| None | да | — |

## CaseQuery

Тип: `CaseSelection | ReceiptQuery`. Ограничения: —.

## QueryCasesInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| query | CaseQuery | да | — |

## CaseResult

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| kind | Literal['cases'] | да | — |
| cases | list[CaseRecord] | да | minItems=0; maxItems=100 |
| next_cursor | str \| None | да | — |

## QueryCasesOutput

Тип: `CaseResult | ReceiptResult`. Ограничения: —.

## EvaluationInput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| results | list[ObservedResult] | да | minItems=1; maxItems=100 |
| expectations | list[Expectation] | да | minItems=0; maxItems=1000 |
| require_same_input | StrictBool | да | — |
| method | VersionedRef | да | — |

## EvaluationOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| report | EvaluationReport | да | — |

## MockParameters

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| scenario | Literal['default', 'empty', 'partial', 'contradictory', 'timeout', 'retryable_error', 'fatal_error'] | да | — |

## MockSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| id | Literal['mock.baseline', 'mock.alternative'] | да | — |
| version | Literal['1.0.0'] | да | — |
| parameters | MockParameters | да | — |

## RealPrepareParameters

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|

## RealPrepareSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| id | Literal['real.prepare'] | да | — |
| version | Literal['1.0.0'] | да | — |
| parameters | RealPrepareParameters | да | — |

## ImplementationParameters

Тип: `MockParameters | RealPrepareParameters`. Ограничения: —.

## ImplementationSelection

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| id | Identifier | да | — |
| version | Version | да | — |
| parameters | ImplementationParameters | да | — |

## LiveExecution

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| mode | Literal['live'] | да | — |
| recording | Literal['full', 'metadata_only'] | да | — |
| analytical_time | Timestamp | да | — |
| random_seed | StrictInt | да | minimum=0; maximum=2147483647 |
| timeout_ms | StrictInt | да | minimum=1; maximum=30000 |

## ReplayExecution

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| mode | Literal['replay'] | да | — |
| recording | Literal['full'] | да | — |
| source_run_id | Identifier | да | — |
| strict | Literal[True] | да | — |
| timeout_ms | StrictInt | да | minimum=1; maximum=30000 |

## ExecutionOptions

Тип: `LiveExecution | ReplayExecution`. Ограничения: —.

## ErrorInfo

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| code | Identifier | да | — |
| category | Literal['validation', 'access', 'policy', 'conflict', 'dependency', 'timeout', 'internal', 'unavailable', 'replay'] | да | — |
| retryable | StrictBool | да | — |
| safe_message | SafeText | да | — |
| field_paths | list[str] | да | minItems=0; maxItems=100 |
| dependency_id | Identifier \| None | да | — |
| outcome | Literal['not_applied', 'applied', 'unknown', 'not_applicable'] | да | — |

## ExecutionMeta

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| run_id | Identifier | да | — |
| operation_id | Identifier | да | — |
| contract_version | Literal['1.0.0'] | да | — |
| implementation | VersionedRef | да | — |
| execution_mode | Literal['live', 'replay'] | да | — |
| environment | Literal['development', 'testing', 'production'] | да | — |
| configuration_hash | Hash | да | — |
| duration_ms | StrictInt | да | minimum=0; maximum=2147483647 |
| lineage | LineageSummary | да | — |
| trace_status | Literal['complete', 'partial', 'metadata_only'] | да | — |
| replay_status | Literal['available', 'incomplete', 'unavailable'] | да | — |
| measurements | list[Measurement] | да | minItems=0; maxItems=100 |
| data_policy | DataPolicyDecision | да | — |

## ErrorResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta \| None | да | — |
| error | ErrorInfo | да | — |

## Sources_fetchRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | FetchInput | да | — |

## Sources_fetchResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | FetchOutput | да | — |

## Documents_prepareRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | PrepareInput | да | — |

## Documents_prepareResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | PrepareOutput | да | — |

## Documents_registerRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | RegisterDocumentInput | да | — |
| idempotency_key | Identifier | да | — |

## Documents_registerResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | RegisterDocumentOutput | да | — |

## Documents_readRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ReadDocumentsInput | да | — |

## Documents_readResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ReadDocumentsOutput | да | — |

## Understanding_classifyRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ClassificationInput | да | — |

## Understanding_classifyResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ClassificationOutput | да | — |

## Understanding_extractRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ExtractionInput | да | — |

## Understanding_extractResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ExtractionOutput | да | — |

## Events_propose_resolutionRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ResolutionInput | да | — |

## Events_propose_resolutionResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ResolutionOutput | да | — |

## Events_applyRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ApplyEventsInput | да | — |
| idempotency_key | Identifier | да | — |

## Events_applyResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ApplyEventsOutput | да | — |

## Events_readRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ReadEventsInput | да | — |

## Events_readResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ReadEventsOutput | да | — |

## Business_propose_profileRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ProfileInput | да | — |

## Business_propose_profileResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ProfileOutput | да | — |

## Business_propose_questionsRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | QuestionsInput | да | — |

## Business_propose_questionsResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | QuestionsOutput | да | — |

## Business_applyRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ApplyBusinessInput | да | — |
| idempotency_key | Identifier | да | — |

## Business_applyResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ApplyBusinessOutput | да | — |

## Business_readRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ReadBusinessInput | да | — |

## Business_readResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ReadBusinessOutput | да | — |

## Graph_buildRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | BuildGraphInput | да | — |

## Graph_buildResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | BuildGraphOutput | да | — |

## Graph_publishRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | PublishGraphInput | да | — |
| idempotency_key | Identifier | да | — |

## Graph_publishResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | PublishGraphOutput | да | — |

## Graph_queryRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | QueryGraphInput | да | — |

## Graph_queryResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | QueryGraphOutput | да | — |

## Matching_matchRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | MatchingInput | да | — |

## Matching_matchResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | MatchingOutput | да | — |

## Impact_assessRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ImpactInput | да | — |

## Impact_assessResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ImpactOutput | да | — |

## Recommendations_proposeRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | RecommendationInput | да | — |

## Recommendations_proposeResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | RecommendationOutput | да | — |

## Evidence_registerRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | RegisterEvidenceInput | да | — |
| idempotency_key | Identifier | да | — |

## Evidence_registerResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | RegisterEvidenceOutput | да | — |

## Evidence_readRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | ReadEvidenceInput | да | — |

## Evidence_readResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | ReadEvidenceOutput | да | — |

## Runs_queryRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | QueryRunsInput | да | — |

## Runs_queryResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | QueryRunsOutput | да | — |

## Cases_saveRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | SaveCaseInput | да | — |
| idempotency_key | Identifier | да | — |

## Cases_saveResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | SaveCaseOutput | да | — |

## Cases_queryRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | QueryCasesInput | да | — |

## Cases_queryResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | QueryCasesOutput | да | — |

## Evaluation_evaluateRequest

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| contract_version | Literal['1.0.0'] | да | — |
| request_id | Identifier | да | — |
| sandbox_id | Identifier | да | — |
| implementation | ImplementationSelection | да | — |
| execution | ExecutionOptions | да | — |
| data_declaration | Literal['synthetic', 'public', 'unknown'] | да | — |
| payload | EvaluationInput | да | — |

## Evaluation_evaluateResponse

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| meta | ExecutionMeta | да | — |
| status | Literal['success', 'partial', 'abstained'] | да | — |
| payload | EvaluationOutput | да | — |

## ImplementationDescriptor

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| id | Identifier | да | — |
| version | Version | да | — |
| kind | Literal['real', 'mock'] | да | — |
| available | StrictBool | да | — |
| reason | SafeText \| None | да | — |
| parameter_schema_id | Identifier | да | — |
| capabilities | list[Identifier] | да | minItems=0; maxItems=100 |
| environments | list[Literal['development', 'testing', 'production']] | да | minItems=0; maxItems=3 |

## OperationDescriptor

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| operation_id | Identifier | да | — |
| contract_version | Version | да | — |
| path | str | да | minLength=1; maxLength=300 |
| method | Literal['POST'] | да | — |
| kind | Literal['source', 'compute', 'read', 'command'] | да | — |
| request_schema_id | Identifier | да | — |
| response_schema_id | Identifier | да | — |
| implementations | list[ImplementationDescriptor] | да | minItems=0; maxItems=100 |
| effects | list[SafeText] | да | minItems=0; maxItems=100 |
| replay_profile | Literal['restore_state', 'recorded_owner_read', 'recorded_dependencies', 'fixed_input'] | да | — |

## CatalogOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| operations | list[OperationDescriptor] | да | minItems=25; maxItems=25 |
| environment | Literal['development', 'testing', 'production'] | да | — |
| allowed_sandboxes | list[Identifier] | да | minItems=0; maxItems=100 |
| build_hash | Hash | да | — |
| readiness_report_hash | Hash \| None | да | — |

## HealthOutput

| Поле | Pydantic-тип | Обязательно | Ограничения |
|---|---|---|---|
| status | Literal['ok', 'unavailable'] | да | — |
| build_hash | Hash | да | — |
