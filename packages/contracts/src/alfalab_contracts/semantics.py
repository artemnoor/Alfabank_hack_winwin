"""DTO-local semantic validation plus explicit validators for related DTOs.

Checks requiring a trusted principal, owner repository, ontology registry,
artifact registry, or trace remain at those boundaries and are not guessed
from caller-supplied fields here.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from ._types import parse_utc_timestamp

if TYPE_CHECKING:
    from ._base import OpenAPIModel
    from ._generated import (
        EvaluationInput,
        EvaluationOutput,
        PrepareInput,
        PrepareOutput,
        ResolutionInput,
        ResolutionOutput,
        MatchingInput,
        MatchingOutput,
        ImpactInput,
        ImpactOutput,
        ProfileInput,
        ProfileOutput,
        RecommendationInput,
        RecommendationOutput,
    )


def _text_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _enum_value(value: object) -> str:
    return str(value)


def _object_key(value: OpenAPIModel) -> tuple[tuple[str, object], ...]:
    return tuple(sorted(value.model_dump(mode="python").items()))


def _code_key(value: OpenAPIModel) -> tuple[object, ...]:
    return (value.namespace, value.version, value.code)


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_dto(model: OpenAPIModel) -> None:
    """Apply only semantic rules decidable from this DTO's typed values."""
    name = type(model).__name__

    if name == "RawMaterial":
        _ensure(model.content_hash == _text_hash(model.text), "content_hash must be SHA-256 of UTF-8 text")

    elif name == "PreparedMaterial":
        _ensure(
            model.prepared_hash == model.material.content_hash,
            "prepared_hash must equal the prepared material content_hash",
        )
        _validate_prepared_span_coverage(model)

    elif name == "SpanMap":
        _ensure(model.prepared_start <= model.prepared_end, "prepared span bounds must be ordered")
        _ensure(model.raw_start <= model.raw_end, "raw span bounds must be ordered")

    elif name == "Validity":
        if model.valid_from is not None and model.valid_to is not None:
            _ensure(
                parse_utc_timestamp(model.valid_to) > parse_utc_timestamp(model.valid_from),
                "valid_to must be later than valid_from",
            )

    elif name == "StatementRef":
        _ensure(
            _enum_value(model.aggregate_ref.owner) in {"Events", "Business"},
            "StatementRef aggregate owner must be Events or Business",
        )

    elif name == "Statement":
        if model.epistemic_status.value == "confirmed":
            _ensure(
                bool(model.provenance.evidence_refs),
                "confirmed statements require at least one evidence reference",
            )
        if model.epistemic_status.value == "inferred" or model.provenance.origin.value == "derived":
            _ensure(model.provenance.derivation_method is not None, "derived/inferred statements require derivation_method")
            _ensure(bool(model.provenance.input_statement_refs), "derived/inferred statements require input_statement_refs")

    elif name == "TextSpan":
        _ensure(model.end >= model.start, "text spans require an ordered [start, end) range")

    elif name == "QuestionAnswer":
        status = _enum_value(model.status)
        if status == "answered":
            _ensure(model.value is not None, "answered requires a value")
        else:
            _ensure(model.value is None, f"{status} requires a null value")

    elif name == "TopicScore":
        if model.raw_score is not None or model.calibrated:
            _ensure(model.score_method is not None, "raw_score or calibrated score requires score_method")

    elif name == "EventDecision":
        action = _enum_value(model.action)
        targets = len(model.target_refs)
        successors = len(model.proposed_events)
        if action == "create":
            _ensure(targets == 0, "create cannot target an existing event")
        elif action in {"attach", "correct"}:
            _ensure(targets == 1, f"{action} requires exactly one target")
        elif action == "merge":
            _ensure(targets >= 2, "merge requires at least two targets")
            _ensure(successors == 1, "merge requires exactly one successor")
        elif action == "split":
            _ensure(targets == 1, "split requires exactly one target")
            _ensure(successors >= 2, "split requires at least two successors")
        elif action == "defer":
            _ensure(targets == 0 and successors == 0, "defer cannot change event state")

    elif name == "EventChangeProposal":
        mention_ids = [
            mention_id
            for decision in model.decisions
            for mention_id in decision.mention_ids
        ]
        unresolved = list(model.unresolved_mentions)
        all_mentions = mention_ids + unresolved
        _ensure(len(all_mentions) == len(set(all_mentions)), "mention IDs must be assigned at most once")
        proposed_ids = [
            event.ref.object_id
            for decision in model.decisions
            for event in decision.proposed_events
        ]
        _ensure(len(proposed_ids) == len(set(proposed_ids)), "proposed event IDs must be unique")
        proposed_events = {
            _object_key(event.ref): event
            for decision in model.decisions
            for event in decision.proposed_events
        }
        visiting: set[tuple[tuple[str, object], ...]] = set()
        visited: set[tuple[tuple[str, object], ...]] = set()

        def visit(event_key: tuple[tuple[str, object], ...]) -> None:
            _ensure(event_key not in visiting, "proposed event lineage must be acyclic")
            if event_key in visited:
                return
            visiting.add(event_key)
            for predecessor in proposed_events[event_key].lineage_refs:
                predecessor_key = _object_key(predecessor)
                if predecessor_key in proposed_events:
                    visit(predecessor_key)
            visiting.remove(event_key)
            visited.add(event_key)

        for event_key in proposed_events:
            visit(event_key)

    elif name == "ProjectionManifest":
        slice_keys = [
            (_enum_value(item.owner), item.partition_id, item.selection_key)
            for item in model.input_slices
        ]
        _ensure(len(slice_keys) == len(set(slice_keys)), "projection input slices must be unique")

    elif name == "GraphSnapshot":
        node_ids = [node.node_id for node in model.nodes]
        edge_ids = [edge.edge_id for edge in model.edges]
        _ensure(len(node_ids) == len(set(node_ids)), "graph node IDs must be unique")
        _ensure(len(edge_ids) == len(set(edge_ids)), "graph edge IDs must be unique")
        node_id_set = set(node_ids)
        for edge in model.edges:
            _ensure(
                edge.source_node_id in node_id_set and edge.target_node_id in node_id_set,
                "graph edge endpoints must exist in the snapshot",
            )
            _ensure(
                edge.relation.namespace == model.manifest.ontology.id
                and edge.relation.version == model.manifest.ontology.version,
                "graph relation namespace/version must match the manifest ontology",
            )
            if edge.epistemic_status.value == "inferred" or edge.provenance.origin.value == "derived":
                _ensure(edge.provenance.derivation_method is not None, "derived/inferred graph edges require derivation_method")
                _ensure(bool(edge.provenance.input_statement_refs), "derived/inferred graph edges require input_statement_refs")
                has_basis = bool(
                    edge.statement_refs
                    or edge.evidence_refs
                    or edge.provenance.input_statement_refs
                    or edge.provenance.source_refs
                )
                _ensure(has_basis, "derived/inferred graph edges require grounding references")
            else:
                _ensure(bool(edge.statement_refs), "direct graph edges require a source statement reference")

    elif name == "FinancialScenario":
        if model.quantity is not None:
            _ensure(model.quantity.unit is not None, "known financial quantities require a unit")
            _ensure(bool(model.input_refs), "known financial quantities require input_refs")

    elif name == "DependencyRecord":
        _ensure(
            (model.response is None) != (model.error is None),
            "dependency record must contain exactly one of response or error",
        )
        if _enum_value(model.substitution) == "replay":
            _ensure(model.original_run_id is not None, "replay substitution requires original_run_id")

    elif name == "ArtifactView":
        available = _enum_value(model.availability) == "available"
        _ensure(
            (model.content_json is not None) == available,
            "available artifacts require content_json; other availability states require null",
        )
        if model.content_json is not None:
            try:
                json.loads(model.content_json)
            except json.JSONDecodeError as exc:
                raise ValueError("content_json must contain valid JSON") from exc

    elif name == "Measurement":
        if _enum_value(model.basis) == "unknown":
            _ensure(model.value is None, "unknown measurement basis requires null value")
        else:
            _ensure(model.value is not None, "measured or estimated basis requires a value")


def _validate_prepared_span_coverage(prepared: OpenAPIModel) -> None:
    text_length = len(prepared.material.text)
    spans = prepared.span_map
    if not text_length:
        _ensure(not spans, "empty prepared text must have an empty span map")
        return
    _ensure(bool(spans), "non-empty prepared text must have a span map")
    expected_start = 0
    previous_raw_end = 0
    for span in spans:
        _ensure(span.prepared_start == expected_start, "span map must cover prepared code points in order")
        _ensure(span.prepared_start < span.prepared_end, "span map entries must cover at least one prepared point")
        _ensure(span.raw_start >= previous_raw_end, "span map raw ranges must be monotonic")
        _ensure(span.raw_start < span.raw_end, "span map entries must reference at least one raw point")
        _ensure(span.raw_end <= 200000, "span map raw offset exceeds the contract limit")
        expected_start = span.prepared_end
        previous_raw_end = span.raw_end
    _ensure(expected_start == text_length, "span map must cover all prepared code points")


def validate_prepare_pair(request: PrepareInput, response: PrepareOutput) -> None:
    """Validate the Documents.prepare request/output relationship.

    This checks the agreed normalization semantics, content hashes, and map
    bounds. It does not prescribe a canonical segmentation of SpanMap entries.
    """
    raw = request.material
    prepared = response.prepared
    expected_text = raw.text
    if request.normalize_newlines:
        expected_text = expected_text.replace("\r\n", "\n").replace("\r", "\n")
    if request.trim_outer_whitespace:
        expected_text = expected_text.strip()
    _ensure(prepared.raw_hash == raw.content_hash, "prepared raw_hash must refer to the input material")
    _ensure(prepared.material.text == expected_text, "prepared text violates the declared normalization options")
    _ensure(prepared.prepared_hash == _text_hash(expected_text), "prepared_hash must hash prepared text")
    if expected_text:
        _ensure(_enum_value(prepared.quality) == "valid", "non-empty prepared text must have valid quality")
    else:
        _ensure(_enum_value(prepared.quality) == "rejected", "empty prepared text must have rejected quality")
        _ensure(not prepared.span_map, "empty prepared text must have an empty span map")

    raw_length = len(raw.text)
    for span in prepared.span_map:
        _ensure(span.raw_end <= raw_length, "span map raw offset exceeds input text")
    _validate_prepared_span_coverage(prepared)


def validate_resolution_pair(request: ResolutionInput, response: ResolutionOutput) -> None:
    """Ensure each inline mention is decided exactly once or unresolved."""
    input_ids = [mention.mention_id for mention in request.mentions]
    _ensure(len(input_ids) == len(set(input_ids)), "resolution input mention IDs must be unique")
    proposal = response.proposal
    assigned = [
        mention_id
        for decision in proposal.decisions
        for mention_id in decision.mention_ids
    ]
    all_output_ids = assigned + list(proposal.unresolved_mentions)
    _ensure(len(all_output_ids) == len(set(all_output_ids)), "each mention must be assigned at most once")
    _ensure(
        set(all_output_ids) == set(input_ids),
        "each input mention must have exactly one decision or be unresolved",
    )
    _ensure(
        proposal.source_snapshot == request.existing.slice,
        "resolution proposal source_snapshot must match the supplied existing snapshot",
    )
    known_targets = {_object_key(event.ref) for event in request.existing.events}
    for decision in proposal.decisions:
        for target in decision.target_refs:
            _ensure(_object_key(target) in known_targets, "resolution target must exist in the supplied snapshot")


def validate_profile_pair(request: ProfileInput, response: ProfileOutput) -> None:
    """Keep a profile proposal tied to the explicitly supplied company snapshot."""
    proposal = response.proposal
    _ensure(
        proposal.company.entity_id == request.company.entity_id,
        "profile proposal company must match the supplied company",
    )
    existing = request.existing
    if existing is not None:
        _ensure(
            existing.company.entity_id == request.company.entity_id,
            "existing profile snapshot must belong to the supplied company",
        )
    expected_revision = existing.ref.revision if existing is not None else 0
    _ensure(
        proposal.expected_revision == expected_revision,
        "profile proposal expected_revision must match the supplied company snapshot",
    )
    if existing is None:
        _ensure(not proposal.supersede_refs, "a new company proposal cannot supersede statements")
        return

    _ensure(_enum_value(existing.ref.owner) == "Business", "existing profile snapshot ref must be owned by Business")
    existing_statement_revisions = {
        (statement.statement_id, statement.revision)
        for statement in existing.statements
    }
    for statement_ref in proposal.supersede_refs:
        _ensure(
            _object_key(statement_ref.aggregate_ref) == _object_key(existing.ref),
            "superseded statement aggregate must belong to the supplied company snapshot",
        )
        _ensure(
            (statement_ref.statement_id, statement_ref.revision) in existing_statement_revisions,
            "superseded statement must exist in the supplied company snapshot",
        )


def validate_matching_pair(request: MatchingInput, response: MatchingOutput) -> None:
    """Validate that a matching result stays within its fully supplied scope."""
    profile_ids = [profile.company.entity_id for profile in request.profiles]
    _ensure(
        len(response.candidate_scope) == len(set(response.candidate_scope))
        and set(response.candidate_scope) == set(profile_ids),
        "candidate_scope must exactly match the supplied profile companies",
    )
    event_ref = request.event.ref
    graph_edges = {edge.edge_id: edge for edge in request.graph.snapshot.edges}
    for match in response.matches:
        _ensure(match.event_ref == event_ref, "match event_ref must match the supplied event")
        _ensure(match.company.entity_id in set(profile_ids), "match company must belong to the supplied profile scope")
        _validate_edge_paths(match.edge_paths, graph_edges)


def _validate_edge_paths(edge_paths: list[list[str]], graph_edges: dict[str, OpenAPIModel]) -> None:
    """Require each declared path to be a non-empty connected sequence of supplied edges.

    The contract does not define whether impact traversal follows or reverses a
    relation's source/target orientation, so this validates undirected
    topological continuity without inventing a direction policy.
    """
    for path in edge_paths:
        _ensure(bool(path), "edge paths must contain at least one edge")
        _ensure(all(edge_id in graph_edges for edge_id in path), "match paths must use edges from the supplied graph")
        for left_id, right_id in zip(path, path[1:]):
            left = graph_edges[left_id]
            right = graph_edges[right_id]
            left_nodes = {left.source_node_id, left.target_node_id}
            right_nodes = {right.source_node_id, right.target_node_id}
            _ensure(bool(left_nodes & right_nodes), "consecutive path edges must share a graph node")


def validate_impact_pair(request: ImpactInput, response: ImpactOutput) -> None:
    """Validate event/company/graph consistency without inferring risk from no match."""
    match = request.match
    assessment = response.assessment
    _ensure(match.event_ref == request.event.ref, "impact match event_ref must match the supplied event")
    _ensure(match.company.entity_id == request.profile.company.entity_id, "impact match company must match the supplied profile")
    _ensure(assessment.event_ref == request.event.ref, "impact assessment event_ref must match the supplied event")
    _ensure(assessment.company.entity_id == request.profile.company.entity_id, "impact assessment company must match the supplied profile")
    _ensure(
        assessment.graph_manifest == request.graph.snapshot.manifest,
        "impact assessment graph_manifest must match the supplied graph",
    )
    graph_edges = {edge.edge_id: edge for edge in request.graph.snapshot.edges}
    _validate_edge_paths(match.edge_paths, graph_edges)


def validate_recommendation_pair(request: RecommendationInput, response: RecommendationOutput) -> None:
    """Enforce the inline action allowlist, audience, assessment, and approval floor."""
    definitions = {_code_key(action.code): action for action in request.allowed_actions}
    _ensure(len(definitions) == len(request.allowed_actions), "allowed_actions must not contain duplicate action codes")
    if not request.allowed_actions:
        _ensure(not response.recommendations, "empty allowed_actions requires an empty recommendation list")
    assessment = request.assessment
    for recommendation in response.recommendations:
        _ensure(recommendation.assessment_id == assessment.assessment_id, "recommendation assessment_id must match the supplied assessment")
        definition = definitions.get(_code_key(recommendation.action_type))
        _ensure(definition is not None, "recommendation action_type must be in allowed_actions")
        _ensure(request.audience in definition.audiences, "recommendation action must allow the requested audience")
        if definition.requires_approval:
            _ensure(recommendation.requires_approval, "recommendation cannot lower the action approval requirement")
        assessment_evidence = {_object_key(ref) for ref in assessment.evidence_refs}
        _ensure(
            {_object_key(ref) for ref in recommendation.evidence_refs}.issubset(assessment_evidence),
            "recommendation evidence_refs must be supported by the supplied assessment",
        )


def validate_operation_semantics(operation_id: str, request: OpenAPIModel, response: OpenAPIModel) -> None:
    """Dispatch all request/response semantic invariants supported by T01."""
    if operation_id == "Documents.prepare":
        validate_prepare_pair(request.payload, response.payload)
    elif operation_id == "Events.propose_resolution":
        validate_resolution_pair(request.payload, response.payload)
    elif operation_id == "Business.propose_profile":
        validate_profile_pair(request.payload, response.payload)
    elif operation_id == "Matching.match":
        validate_matching_pair(request.payload, response.payload)
    elif operation_id == "Impact.assess":
        validate_impact_pair(request.payload, response.payload)
    elif operation_id == "Recommendations.propose":
        validate_recommendation_pair(request.payload, response.payload)
    elif operation_id == "Evaluation.evaluate":
        validate_evaluation_pair(request.payload, response.payload)


def evaluation_is_comparable(request: EvaluationInput) -> bool:
    """Return whether the request satisfies its declared same-input policy."""
    hashes = {result.input_hash for result in request.results}
    return not request.require_same_input or len(hashes) <= 1


def validate_evaluation_pair(request: EvaluationInput, response: EvaluationOutput) -> None:
    """Prevent a result from claiming comparability across mismatched inputs."""
    if not evaluation_is_comparable(request):
        _ensure(not response.report.comparable, "mismatched input hashes cannot be comparable")
