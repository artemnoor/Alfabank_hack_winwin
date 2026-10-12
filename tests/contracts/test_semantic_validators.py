from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from alfalab_contracts import SCHEMA_TYPES
from alfalab_contracts.semantics import (
    evaluation_is_comparable,
    validate_evaluation_pair,
    validate_matching_pair,
    validate_prepare_pair,
    validate_profile_pair,
    validate_resolution_pair,
)

H = "sha256:" + "a" * 64


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _model(name: str, value: dict):
    return SCHEMA_TYPES[name].model_validate(value)


def _provenance() -> dict:
    return {
        "origin": "unknown",
        "source_refs": [],
        "input_statement_refs": [],
        "producer_run_id": None,
        "derivation_method": None,
        "evidence_refs": [],
        "origin_verified": False,
    }


def _versioned(identifier: str = "method") -> dict:
    return {"id": identifier, "version": "1.0.0", "hash": H}


def _object_ref(owner: str = "Events", object_id: str = "object-1") -> dict:
    return {"owner": owner, "object_id": object_id, "revision": 1, "hash": H}


def _knowledge_slice() -> dict:
    return {"owner": "Events", "partition_id": "events-1", "revision": 0, "selection_key": "all"}


def _artifact_view(availability: str = "metadata_only", content_json: str | None = None) -> dict:
    return {
        "ref": {
            "artifact_id": "artifact-1",
            "hash": H,
            "schema_id": "TestArtifact",
            "schema_version": "1.0.0",
            "size_bytes": len(content_json or ""),
            "classification": "synthetic",
            "media_type": "application/json",
        },
        "content_json": content_json,
        "availability": availability,
    }


def test_raw_material_hash_and_validity_ordering() -> None:
    raw = {
        "material_id": "material-1",
        "source_id": None,
        "source_url": None,
        "title": "Кириллица",
        "text": "ёж 🛰️",
        "published_at": None,
        "collected_at": "2026-10-12T00:00:00Z",
        "content_hash": _hash("ёж 🛰️"),
        "language": "ru",
        "provenance": _provenance(),
    }
    _model("RawMaterial", raw)
    with pytest.raises(ValidationError, match="content_hash"):
        _model("RawMaterial", {**raw, "content_hash": H})

    _model(
        "Validity",
        {
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": "2026-01-02T00:00:00+00:00",
            "recorded_at": "2026-01-03T00:00:00Z",
        },
    )
    for invalid_bounds in (
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ("2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z"),
    ):
        with pytest.raises(ValidationError, match="valid_to"):
            _model(
                "Validity",
                {"valid_from": invalid_bounds[0], "valid_to": invalid_bounds[1], "recorded_at": "2026-01-03T00:00:00Z"},
            )
    _model("Validity", {"valid_from": None, "valid_to": None, "recorded_at": "2026-01-03T00:00:00Z"})


def test_statement_ref_owner_question_answer_and_score_rules() -> None:
    _model(
        "StatementRef",
        {"aggregate_ref": _object_ref("Business"), "statement_id": "statement-1", "revision": 1, "hash": H},
    )
    with pytest.raises(ValidationError, match="aggregate owner"):
        _model(
            "StatementRef",
            {"aggregate_ref": _object_ref("Documents"), "statement_id": "statement-1", "revision": 1, "hash": H},
        )

    answer_base = {"question_id": "q1", "provenance": _provenance()}
    _model("QuestionAnswer", {**answer_base, "status": "unknown", "value": None})
    _model("QuestionAnswer", {**answer_base, "status": "answered", "value": {"kind": "text", "value": "supplier"}})
    with pytest.raises(ValidationError, match="answered requires"):
        _model("QuestionAnswer", {**answer_base, "status": "answered", "value": None})
    with pytest.raises(ValidationError, match="skipped requires"):
        _model("QuestionAnswer", {**answer_base, "status": "skipped", "value": {"kind": "boolean", "value": False}})

    score_base = {
        "code": {"namespace": "topics", "version": "1.0.0", "code": "trade"},
        "raw_score": 0.5,
        "score_method": None,
        "calibrated": False,
    }
    with pytest.raises(ValidationError, match="requires score_method"):
        _model("TopicScore", score_base)
    with pytest.raises(ValidationError, match="calibrated score requires"):
        _model("TopicScore", {**score_base, "raw_score": None, "calibrated": True})
    _model("TopicScore", {**score_base, "score_method": _versioned("calibration"), "calibrated": True})


def test_inferred_statements_require_explicit_derivation_inputs() -> None:
    statement = {
        "statement_id": "statement-1",
        "revision": 1,
        "subject": {
            "entity_id": "company-1",
            "kind": _versioned("company"),
            "display_name": "Company",
        },
        "predicate": {"namespace": "business", "version": "1.0.0", "code": "supplies"},
        "value": {"kind": "unknown", "reason": "not established"},
        "epistemic_status": "inferred",
        "validity": {"valid_from": None, "valid_to": None, "recorded_at": "2026-10-12T00:00:00Z"},
        "provenance": _provenance(),
    }
    with pytest.raises(ValidationError, match="derivation_method"):
        _model("Statement", statement)

    provenance = {
        **_provenance(),
        "derivation_method": _versioned("inference-rule"),
        "input_statement_refs": [
            {
                "aggregate_ref": _object_ref("Business"),
                "statement_id": "source-statement",
                "revision": 1,
                "hash": H,
            }
        ],
    }
    _model("Statement", {**statement, "provenance": provenance})


def test_confirmed_statements_require_an_evidence_reference() -> None:
    statement = {
        "statement_id": "statement-confirmed",
        "revision": 1,
        "subject": {
            "entity_id": "company-1",
            "kind": _versioned("company"),
            "display_name": "Company",
        },
        "predicate": {"namespace": "business", "version": "1.0.0", "code": "supplies"},
        "value": {"kind": "text", "value": "supplier"},
        "epistemic_status": "confirmed",
        "validity": {"valid_from": None, "valid_to": None, "recorded_at": "2026-10-12T00:00:00Z"},
        "provenance": _provenance(),
    }
    with pytest.raises(ValidationError, match="evidence reference"):
        _model("Statement", statement)
    _model(
        "Statement",
        {
            **statement,
            "provenance": {
                **_provenance(),
                "evidence_refs": [_object_ref("Evidence", "evidence-1")],
            },
        },
    )


def test_text_span_bounds_and_known_financial_values_require_minimal_support() -> None:
    _model("TextSpan", {"kind": "text_span", "start": 0, "end": 1, "quote_hash": H})
    # Empty half-open ranges are not forbidden by the current normative spec.
    _model("TextSpan", {"kind": "text_span", "start": 1, "end": 1, "quote_hash": H})
    with pytest.raises(ValidationError, match="ordered"):
        _model("TextSpan", {"kind": "text_span", "start": 2, "end": 1, "quote_hash": H})

    base = {
        "scenario_id": "scenario-1",
        "quantity": {"kind": "number", "value": "10", "unit": None},
        "assumptions": [],
        "calculation_method": _versioned("financial-calculation"),
        "input_refs": [],
    }
    with pytest.raises(ValidationError, match="require a unit"):
        _model("FinancialScenario", base)
    with pytest.raises(ValidationError, match="require input_refs"):
        _model("FinancialScenario", {**base, "quantity": {"kind": "number", "value": "10", "unit": {"namespace": "currency", "version": "1.0.0", "code": "USD"}}})
    _model("FinancialScenario", {**base, "quantity": None})


def test_event_decision_and_proposal_cover_mentions_without_duplicates() -> None:
    target = _object_ref()
    common = {"mention_ids": ["mention-1"], "proposed_events": [], "reason": "uncertain", "evidence_refs": []}
    _model("EventDecision", {**common, "action": "create", "target_refs": []})
    with pytest.raises(ValidationError, match="exactly one target"):
        _model("EventDecision", {**common, "action": "attach", "target_refs": []})
    _model("EventDecision", {**common, "action": "attach", "target_refs": [target]})
    with pytest.raises(ValidationError, match="cannot change"):
        _model("EventDecision", {**common, "action": "defer", "target_refs": [target]})

    proposal = {
        "proposal_id": "proposal-1",
        "source_snapshot": _knowledge_slice(),
        "decisions": [
            {**common, "action": "defer", "target_refs": []},
            {**common, "action": "defer", "target_refs": []},
        ],
        "unresolved_mentions": [],
        "missing_data": [],
        "provenance": _provenance(),
    }
    with pytest.raises(ValidationError, match="at most once"):
        _model("EventChangeProposal", proposal)


def test_projection_manifest_and_graph_snapshot_invariants() -> None:
    manifest = {
        "ontology": _versioned("ontology"),
        "rules": _versioned("rules"),
        "input_slices": [_knowledge_slice()],
        "as_of": {"valid_as_of": "2026-10-12T00:00:00Z", "known_as_of": "2026-10-12T00:00:00Z"},
        "builder": _versioned("builder"),
        "config_hash": H,
    }
    _model("ProjectionManifest", manifest)
    with pytest.raises(ValidationError, match="input slices must be unique"):
        _model("ProjectionManifest", {**manifest, "input_slices": [_knowledge_slice(), _knowledge_slice()]})

    edge = {
        "edge_id": "edge-1",
        "source_node_id": "missing-node",
        "target_node_id": "missing-node-2",
        "relation": {"namespace": "ontology", "version": "1.0.0", "code": "depends_on"},
        "epistemic_status": "unknown",
        "statement_refs": [],
        "evidence_refs": [],
        "provenance": _provenance(),
    }
    graph = {
        "graph_id": "graph-1",
        "revision": 1,
        "nodes": [],
        "edges": [edge],
        "manifest": manifest,
        "completeness": "unknown",
        "missing_data": [],
    }
    with pytest.raises(ValidationError, match="edge endpoints"):
        _model("GraphSnapshot", graph)

    nodes = [
        {
            "node_id": node_id,
            "entity": {
                "entity_id": node_id,
                "kind": _versioned("company"),
                "display_name": node_id,
            },
            "statement_refs": [],
            "provenance": _provenance(),
        }
        for node_id in ("node-1", "node-2")
    ]
    inferred_edge = {
        **edge,
        "source_node_id": "node-1",
        "target_node_id": "node-2",
        "epistemic_status": "inferred",
    }
    with pytest.raises(ValidationError, match="derivation_method"):
        _model("GraphSnapshot", {**graph, "nodes": nodes, "edges": [inferred_edge]})

    direct_edge = {**inferred_edge, "epistemic_status": "observed"}
    with pytest.raises(ValidationError, match="source statement"):
        _model("GraphSnapshot", {**graph, "nodes": nodes, "edges": [direct_edge]})
    source_statement_ref = {
        "aggregate_ref": _object_ref("Business", "business-1"),
        "statement_id": "statement-1",
        "revision": 1,
        "hash": H,
    }
    _model(
        "GraphSnapshot",
        {**graph, "nodes": nodes, "edges": [{**direct_edge, "statement_refs": [source_statement_ref]}]},
    )


def test_artifact_and_dependency_records_preserve_unknown_and_replay_rules() -> None:
    _model("ArtifactView", _artifact_view())
    _model("ArtifactView", _artifact_view("available", "{}"))
    with pytest.raises(ValidationError, match="require content_json"):
        _model("ArtifactView", _artifact_view("available", None))
    with pytest.raises(ValidationError, match="valid JSON"):
        _model("ArtifactView", _artifact_view("available", "not-json"))

    base = {
        "sequence": 0,
        "port_id": "model.classifier",
        "kind": "model",
        "request": _artifact_view("available", "{}"),
        "response": _artifact_view("available", "{}"),
        "error": None,
        "duration_ms": 1,
        "request_hash": H,
        "substitution": "live",
        "original_run_id": None,
    }
    _model("DependencyRecord", base)
    with pytest.raises(ValidationError, match="exactly one"):
        _model("DependencyRecord", {**base, "response": None})
    with pytest.raises(ValidationError, match="original_run_id"):
        _model("DependencyRecord", {**base, "substitution": "replay", "original_run_id": None})
    _model("DependencyRecord", {**base, "substitution": "replay", "original_run_id": "run-source"})


def test_measurement_unknown_does_not_turn_into_zero() -> None:
    _model("Measurement", {"name": "cost_usd", "value": None, "unit": "USD", "basis": "unknown"})
    _model("Measurement", {"name": "latency_ms", "value": "5", "unit": "ms", "basis": "measured"})
    for invalid in (
        {"name": "cost_usd", "value": "0", "unit": "USD", "basis": "unknown"},
        {"name": "latency_ms", "value": None, "unit": "ms", "basis": "measured"},
    ):
        with pytest.raises(ValidationError):
            _model("Measurement", invalid)


def test_prepare_pair_checks_text_hashes_and_span_map() -> None:
    raw_text = " \r\nabc \n"
    normalized = "abc"
    raw_material = {
        "material_id": "raw-1",
        "source_id": None,
        "source_url": None,
        "title": "raw",
        "text": raw_text,
        "published_at": None,
        "collected_at": "2026-10-12T00:00:00Z",
        "content_hash": _hash(raw_text),
        "language": "unknown",
        "provenance": _provenance(),
    }
    prepared_material = {**raw_material, "material_id": "prepared-1", "text": normalized, "content_hash": _hash(normalized)}
    request = _model("PrepareInput", {"material": raw_material, "normalize_newlines": True, "trim_outer_whitespace": True})
    prepared = _model(
        "PreparedMaterial",
        {
            "material": prepared_material,
            "raw_hash": _hash(raw_text),
            "prepared_hash": _hash(normalized),
            "quality": "valid",
            "span_map": [{"prepared_start": 0, "prepared_end": 3, "raw_start": 3, "raw_end": 6}],
            "warnings": [],
        },
    )
    response = _model("PrepareOutput", {"prepared": prepared})
    validate_prepare_pair(request, response)

    bad_response = _model(
        "PrepareOutput",
        {"prepared": prepared.model_copy(update={"raw_hash": H})},
    )
    with pytest.raises(ValueError, match="raw_hash"):
        validate_prepare_pair(request, bad_response)


def test_resolution_business_and_evaluation_cross_dto_rules(examples: list[dict]) -> None:
    mention = {
        "mention_id": "mention-1",
        "event_type": {"namespace": "events", "version": "1.0.0", "code": "unknown"},
        "actors": [],
        "objects": [],
        "statements": [],
        "effective_at": None,
        "missing_data": [],
        "provenance": _provenance(),
    }
    request = _model(
        "ResolutionInput",
        {
            "mentions": [mention],
            "existing": {
                "events": [],
                "slice": _knowledge_slice(),
                "as_of": {"valid_as_of": "2026-10-12T00:00:00Z", "known_as_of": "2026-10-12T00:00:00Z"},
            },
            "evidence": [],
            "policy": _versioned("resolution-policy"),
        },
    )
    proposal = {
        "proposal_id": "proposal-1",
        "source_snapshot": _knowledge_slice(),
        "decisions": [{"action": "defer", "mention_ids": ["mention-1"], "target_refs": [], "proposed_events": [], "reason": "uncertain", "evidence_refs": []}],
        "unresolved_mentions": [],
        "missing_data": [],
        "provenance": _provenance(),
    }
    response = _model("ResolutionOutput", {"proposal": proposal})
    validate_resolution_pair(request, response)
    with pytest.raises(ValueError, match="exactly one decision"):
        validate_resolution_pair(request, _model("ResolutionOutput", {"proposal": {**proposal, "decisions": []}}))
    attach_to_missing_target = {
        **proposal,
        "decisions": [
            {
                "action": "attach",
                "mention_ids": ["mention-1"],
                "target_refs": [_object_ref("Events", "not-in-snapshot")],
                "proposed_events": [],
                "reason": "candidate target",
                "evidence_refs": [],
            }
        ],
    }
    with pytest.raises(ValueError, match="supplied snapshot"):
        validate_resolution_pair(request, _model("ResolutionOutput", {"proposal": attach_to_missing_target}))

    profile_example = next(item for item in examples if item["operation_id"] == "Business.propose_profile")
    profile_request = _model("ProfileInput", profile_example["request"]["payload"])
    profile_output = _model("ProfileOutput", profile_example["response"]["payload"])
    validate_profile_pair(profile_request, profile_output)
    with pytest.raises(ValueError, match="expected_revision"):
        validate_profile_pair(
            profile_request,
            _model("ProfileOutput", {"proposal": {**profile_example["response"]["payload"]["proposal"], "expected_revision": 1}}),
        )
    with pytest.raises(ValueError, match="company"):
        validate_profile_pair(
            profile_request,
            _model(
                "ProfileOutput",
                {
                    "proposal": {
                        **profile_example["response"]["payload"]["proposal"],
                        "company": {**profile_example["response"]["payload"]["proposal"]["company"], "entity_id": "other-company"},
                    }
                },
            ),
        )

    existing_snapshot_data = dict(
        _model("ImpactInput", next(item for item in examples if item["operation_id"] == "Impact.assess")["request"]["payload"]).profile.model_dump(mode="json")
    )
    existing_snapshot_data["ref"] = {**existing_snapshot_data["ref"], "owner": "Business"}
    existing_snapshot_data["statements"] = [
        {
            "statement_id": "business-fact-1",
            "revision": 1,
            "subject": existing_snapshot_data["company"],
            "predicate": {"namespace": "business", "version": "1.0.0", "code": "activity"},
            "value": {"kind": "text", "value": "selling radio components"},
            "epistemic_status": "user_declared",
            "validity": {"valid_from": None, "valid_to": None, "recorded_at": "2026-10-12T00:00:00Z"},
            "provenance": _provenance(),
        }
    ]
    existing_snapshot = _model("BusinessSnapshot", existing_snapshot_data)
    existing_request_data = {
        **profile_example["request"]["payload"],
        "company": existing_snapshot.company.model_dump(mode="json"),
        "existing": existing_snapshot.model_dump(mode="json"),
    }
    existing_proposal = {
        **profile_example["response"]["payload"]["proposal"],
        "company": existing_snapshot.company.model_dump(mode="json"),
        "expected_revision": existing_snapshot.ref.revision,
    }
    valid_supersede_ref = {
        "aggregate_ref": existing_snapshot.ref.model_dump(mode="json"),
        "statement_id": "business-fact-1",
        "revision": 1,
        "hash": H,
    }
    existing_proposal["supersede_refs"] = [valid_supersede_ref]
    existing_request = _model("ProfileInput", existing_request_data)
    validate_profile_pair(existing_request, _model("ProfileOutput", {"proposal": existing_proposal}))
    with pytest.raises(ValueError, match="expected_revision"):
        validate_profile_pair(
            existing_request,
            _model("ProfileOutput", {"proposal": {**existing_proposal, "expected_revision": existing_snapshot.ref.revision - 1}}),
        )
    phantom_supersede_ref = {
        "aggregate_ref": {
            **existing_snapshot.ref.model_dump(mode="json"),
            "owner": "Business",
        },
        "statement_id": "not-in-snapshot",
        "revision": 1,
        "hash": H,
    }
    with pytest.raises(ValueError, match="must exist"):
        validate_profile_pair(
            existing_request,
            _model("ProfileOutput", {"proposal": {**existing_proposal, "supersede_refs": [phantom_supersede_ref]}}),
        )
    foreign_aggregate_ref = {
        **phantom_supersede_ref,
        "aggregate_ref": {**phantom_supersede_ref["aggregate_ref"], "owner": "Events"},
    }
    with pytest.raises(ValueError, match="aggregate must belong"):
        validate_profile_pair(
            existing_request,
            _model("ProfileOutput", {"proposal": {**existing_proposal, "supersede_refs": [foreign_aggregate_ref]}}),
        )

    observation = {
        "run_id": "run-1",
        "input_hash": H,
        "implementation": _versioned("mock.baseline"),
        "output": _artifact_view(),
    }
    evaluation = _model(
        "EvaluationInput",
        {"results": [observation, {**observation, "run_id": "run-2", "input_hash": "sha256:" + "b" * 64}], "expectations": [], "require_same_input": True, "method": _versioned("evaluation")},
    )
    assert not evaluation_is_comparable(evaluation)
    report = {"evaluation_id": "eval-1", "run_ids": ["run-1", "run-2"], "comparable": False, "metrics": [], "limitations": ["different inputs"]}
    validate_evaluation_pair(evaluation, _model("EvaluationOutput", {"report": report}))
    with pytest.raises(ValueError, match="cannot be comparable"):
        validate_evaluation_pair(evaluation, _model("EvaluationOutput", {"report": {**report, "comparable": True}}))


def test_matching_paths_must_be_present_and_topologically_connected(examples: list[dict]) -> None:
    from copy import deepcopy

    matching_example = next(item for item in examples if item["operation_id"] == "Matching.match")
    impact_example = next(item for item in examples if item["operation_id"] == "Impact.assess")
    payload = deepcopy(matching_example["request"]["payload"])
    profile = impact_example["request"]["payload"]["profile"]
    payload["profiles"] = [profile]

    node_ids = ["node-1", "node-2", "node-3", "node-4"]
    source_statement_ref = {
        "aggregate_ref": _object_ref("Business", "business-1"),
        "statement_id": "statement-1",
        "revision": 1,
        "hash": H,
    }
    payload["graph"]["snapshot"]["nodes"] = [
        {
            "node_id": node_id,
            "entity": {
                "entity_id": node_id,
                "kind": _versioned("company"),
                "display_name": node_id,
            },
            "statement_refs": [source_statement_ref],
            "provenance": _provenance(),
        }
        for node_id in node_ids
    ]
    payload["graph"]["snapshot"]["edges"] = [
        {
            "edge_id": "edge-1",
            "source_node_id": "node-1",
            "target_node_id": "node-2",
            "relation": {"namespace": "synthetic-example", "version": "1.0.0", "code": "depends_on"},
            "epistemic_status": "unknown",
            "statement_refs": [source_statement_ref],
            "evidence_refs": [],
            "provenance": _provenance(),
        },
        {
            "edge_id": "edge-2",
            "source_node_id": "node-3",
            "target_node_id": "node-4",
            "relation": {"namespace": "synthetic-example", "version": "1.0.0", "code": "depends_on"},
            "epistemic_status": "unknown",
            "statement_refs": [source_statement_ref],
            "evidence_refs": [],
            "provenance": _provenance(),
        },
    ]
    request = _model("MatchingInput", payload)
    match = {
        "match_id": "match-1",
        "event_ref": matching_example["request"]["payload"]["event"]["ref"],
        "company": profile["company"],
        "exposure": "potential",
        "affected_components": [],
        "edge_paths": [["edge-1", "edge-2"]],
        "evidence_refs": [],
        "missing_data": [],
        "provenance": _provenance(),
    }
    response = _model("MatchingOutput", {"matches": [match], "candidate_scope": [profile["company"]["entity_id"]], "search_complete_for_scope": True, "missing_data": []})
    with pytest.raises(ValueError, match="share a graph node"):
        validate_matching_pair(request, response)

    connected_payload = deepcopy(payload)
    connected_payload["graph"]["snapshot"]["edges"][1]["source_node_id"] = "node-2"
    connected_request = _model("MatchingInput", connected_payload)
    validate_matching_pair(connected_request, response)

    absent_edge = _model("MatchingOutput", {"matches": [{**match, "edge_paths": [["missing-edge"]]}], "candidate_scope": [profile["company"]["entity_id"]], "search_complete_for_scope": True, "missing_data": []})
    with pytest.raises(ValueError, match="supplied graph"):
        validate_matching_pair(connected_request, absent_edge)
