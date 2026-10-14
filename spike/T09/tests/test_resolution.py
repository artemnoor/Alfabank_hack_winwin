from __future__ import annotations

import copy
import json
import logging
import socket
import pytest
from pydantic import ValidationError

from alfalab_contracts.models import SCHEMA_TYPES
from alfalab_contracts.semantics import validate_resolution_pair
from t09_events.resolution import ResolutionPolicy, propose_resolution, retrieve_candidates, sha256_ref
from t09_events.scenarios import DATASET_DIR, SHARED_DIR, input_from_fixture, load_cases, load_dataset, _shared_path


CASES = load_cases()
CASES_BY_ID = {item["fixture_id"].removeprefix("fixture-t09-"): item for item in CASES}
ResolutionInput = SCHEMA_TYPES["ResolutionInput"]
EventDecision = SCHEMA_TYPES["EventDecision"]
EventChangeProposal = SCHEMA_TYPES["EventChangeProposal"]


def _proposal(case_id: str):
    case = CASES_BY_ID[case_id]
    return case, input_from_fixture(case), propose_resolution(input_from_fixture(case)).proposal


def _refresh_record_hash(record: dict) -> None:
    content = {key: value for key, value in record.items() if key != "ref"}
    record["ref"]["hash"] = sha256_ref(content)


def _focus_decision(case: dict, proposal):
    focus_id = case["input_data"]["focus_mention_id"]
    return next(item for item in proposal.decisions if focus_id in item.mention_ids)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["fixture_id"])
def test_all_materialized_cases_strictly_validate_and_assign_mentions_once(case):
    request = input_from_fixture(case)
    response = propose_resolution(request)
    validate_resolution_pair(request, response)

    input_ids = {item.mention_id for item in request.mentions}
    assigned_ids = {
        mention_id
        for decision in response.proposal.decisions
        for mention_id in decision.mention_ids
    } | set(response.proposal.unresolved_mentions)
    assert assigned_ids == input_ids


@pytest.mark.parametrize("case_id", sorted(CASES_BY_ID))
def test_focus_decision_matches_provisional_case_expectation(case_id):
    case, _, proposal = _proposal(case_id)
    assert _focus_decision(case, proposal).action.value == case["provisional_expectation"]


def test_false_merge_and_split_metrics_against_provisional_case_annotations():
    expected_merges = {case_id for case_id, case in CASES_BY_ID.items() if case["provisional_expectation"] == "merge"}
    expected_splits = {case_id for case_id, case in CASES_BY_ID.items() if case["provisional_expectation"] == "split"}
    predicted_merges = set()
    predicted_splits = set()
    for case_id in CASES_BY_ID:
        _, _, proposal = _proposal(case_id)
        actions = {decision.action.value for decision in proposal.decisions}
        if "merge" in actions:
            predicted_merges.add(case_id)
        if "split" in actions:
            predicted_splits.add(case_id)

    assert predicted_merges == expected_merges
    assert predicted_splits == expected_splits
    assert len(CASES_BY_ID) >= 30


def test_resolution_decision_semantics_are_preserved():
    for case_id, case in CASES_BY_ID.items():
        request = input_from_fixture(case)
        proposal = propose_resolution(request).proposal
        for decision in proposal.decisions:
            action = decision.action.value
            if action == "create":
                assert not decision.target_refs
            elif action in {"attach", "correct"}:
                assert len(decision.target_refs) == 1
            elif action == "merge":
                assert len(decision.target_refs) >= 2
                assert len(decision.proposed_events) == 1
            elif action == "split":
                assert len(decision.target_refs) == 1
                assert len(decision.proposed_events) >= 2
            elif action == "defer":
                assert not decision.target_refs
                assert not decision.proposed_events


def test_defer_contract_rejects_target_mutation():
    _, request, proposal = _proposal("company-near-name")
    decision = proposal.decisions[0].model_dump(mode="json")
    decision["target_refs"] = [request.existing.events[0].ref.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="defer cannot change event state"):
        EventDecision.model_validate(decision)


def test_split_proposal_has_one_target_and_successors_linked_to_it():
    _, _, proposal = _proposal("split-two-events-one-article")
    decision = proposal.decisions[0]
    target = decision.target_refs[0]
    assert len(decision.proposed_events) == 2
    for successor in decision.proposed_events:
        assert any(ref.object_id == target.object_id for ref in successor.lineage_refs)


def test_merge_groups_the_mentions_once_and_keeps_both_predecessors():
    _, _, proposal = _proposal("merge-duplicate-export-records")
    assert len(proposal.decisions) == 1
    decision = proposal.decisions[0]
    assert decision.action.value == "merge"
    assert len(decision.mention_ids) == 3
    assert len(decision.target_refs) == 2
    assert len(decision.proposed_events) == 1
    assert {ref.object_id for ref in decision.target_refs}.issubset(
        {ref.object_id for ref in decision.proposed_events[0].lineage_refs}
    )


def test_merge_successor_preserves_distinct_status_and_provenance_variants():
    case = CASES_BY_ID["merge-duplicate-export-records"]
    proposal = propose_resolution(input_from_fixture(case)).proposal
    successor = proposal.decisions[0].proposed_events[0]
    statuses = {statement.epistemic_status.value for statement in successor.statements}
    source_ids = {
        ref.object_id
        for statement in successor.statements
        for ref in statement.provenance.source_refs
    }
    assert {"confirmed", "observed"}.issubset(statuses)
    assert {"doc-export-reprint-01", "doc-export-reprint-02"}.issubset(source_ids)


def test_similarity_only_retrieves_candidate_and_never_establishes_identity():
    case, request, proposal = _proposal("company-near-name")
    mention = request.mentions[0]
    candidates = retrieve_candidates(mention, request.existing)
    assert candidates
    assert candidates[0].near_name_pairs
    assert _focus_decision(case, proposal).action.value == "defer"


def test_exact_entity_ids_survive_display_name_metamorphism():
    case = CASES_BY_ID["same-export-ru-en"]
    raw = input_from_fixture(case).model_dump(mode="json")
    for mention in raw["mentions"]:
        for entity in [*mention["actors"], *mention["objects"]]:
            entity["display_name"] = "Changed alias for testing"
        for statement in mention["statements"]:
            if statement["subject"].get("entity_id"):
                statement["subject"]["display_name"] = "Changed alias for testing"
            value = statement["value"].get("value")
            if isinstance(value, dict) and value.get("entity_id"):
                value["display_name"] = "Changed alias for testing"
    changed = ResolutionInput.model_validate(raw)
    before = propose_resolution(input_from_fixture(case)).model_dump(mode="json")
    after = propose_resolution(changed).model_dump(mode="json")
    assert [item["action"] for item in before["proposal"]["decisions"]] == [
        item["action"] for item in after["proposal"]["decisions"]
    ]


def test_sentence_order_metamorphism_keeps_output_byte_equivalent():
    case = CASES_BY_ID["same-export-ten-reprints"]
    raw = input_from_fixture(case).model_dump(mode="json")
    raw["mentions"] = list(reversed(raw["mentions"]))
    raw["evidence"] = list(reversed(raw["evidence"]))
    raw["existing"]["events"] = list(reversed(raw["existing"]["events"]))
    first = propose_resolution(input_from_fixture(case)).model_dump(mode="json")
    second = propose_resolution(ResolutionInput.model_validate(raw)).model_dump(mode="json")
    assert first == second


def test_epistemic_change_from_observed_to_hypothetical_changes_decision():
    case = CASES_BY_ID["same-export-ru-en"]
    raw = input_from_fixture(case).model_dump(mode="json")
    focus_id = case["input_data"]["focus_mention_id"]
    changed_mention = next(item for item in raw["mentions"] if item["mention_id"] == focus_id)
    for statement in changed_mention["statements"]:
        statement["epistemic_status"] = "hypothetical"
    changed = ResolutionInput.model_validate(raw)
    baseline_decision = _focus_decision(case, propose_resolution(input_from_fixture(case)).proposal)
    changed_decision = _focus_decision(case, propose_resolution(changed).proposal)
    assert baseline_decision.action.value == "attach"
    assert changed_decision.action.value == "defer"


@pytest.mark.parametrize(
    ("effective_at", "expected_action"),
    [("2026-10-27T00:00:00Z", "attach"), ("2026-10-28T00:00:00Z", "create")],
)
def test_same_event_window_has_explicit_inclusive_boundary(effective_at, expected_action):
    case = CASES_BY_ID["same-port-closure-two-sources"]
    raw = input_from_fixture(case).model_dump(mode="json")
    raw["mentions"][0]["effective_at"] = effective_at
    request = ResolutionInput.model_validate(raw)
    proposal = propose_resolution(request).proposal
    action = next(item for item in proposal.decisions if raw["mentions"][0]["mention_id"] in item.mention_ids).action.value
    assert action == expected_action


def test_conflicting_fact_is_deferred_instead_of_overwriting_snapshot():
    case = CASES_BY_ID["same-port-closure-two-sources"]
    raw = input_from_fixture(case).model_dump(mode="json")
    mention = raw["mentions"][0]
    mention["statements"][0]["value"] = {"kind": "text", "value": "different port"}
    request = ResolutionInput.model_validate(raw)
    proposal = propose_resolution(request).proposal
    changed_mention_id = mention["mention_id"]
    changed_decision = next(item for item in proposal.decisions if changed_mention_id in item.mention_ids)
    assert changed_decision.action.value == "defer"


def test_unknown_time_and_identity_are_deferred():
    case, request, proposal = _proposal("unknown-date-export")
    assert _focus_decision(case, proposal).action.value == "defer"
    assert request.mentions[0].effective_at is None


def test_unavailable_source_does_not_become_a_create():
    case, request, proposal = _proposal("no-source-support")
    assert not request.mentions[0].provenance.source_refs
    assert _focus_decision(case, proposal).action.value == "defer"


def test_proposal_does_not_upgrade_statement_certainty_or_mutate_input():
    case = CASES_BY_ID["supplier-sanction-vs-export-ban"]
    request = input_from_fixture(case)
    before = request.model_dump(mode="json")
    proposal = propose_resolution(request).proposal
    assert request.model_dump(mode="json") == before
    mention_statuses = {
        (mention.mention_id, statement.statement_id): statement.epistemic_status.value
        for mention in request.mentions
        for statement in mention.statements
    }
    for decision in proposal.decisions:
        for event in decision.proposed_events:
            for statement in event.statements:
                assert statement.epistemic_status.value == mention_statuses.get(
                    (next(iter(decision.mention_ids)), statement.statement_id),
                    statement.epistemic_status.value,
                )


def test_decisions_preserve_source_and_evidence_provenance():
    case = CASES_BY_ID["same-export-ru-en"]
    request = input_from_fixture(case)
    proposal = propose_resolution(request).proposal
    evidence_ids = {item.ref.object_id for item in request.evidence}
    source_ids = {ref.object_id for mention in request.mentions for ref in mention.provenance.source_refs}
    assert proposal.provenance.derivation_method.id == "t09.deterministic-resolution-rules"
    for decision in proposal.decisions:
        assert decision.evidence_refs
        assert {ref.object_id for ref in decision.evidence_refs}.issubset(evidence_ids)
    for decision in proposal.decisions:
        for event in decision.proposed_events:
            for statement in event.statements:
                assert {ref.object_id for ref in statement.provenance.source_refs}.issubset(source_ids)


def test_proposal_generation_is_offline(monkeypatch):
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("unexpected network access")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    case = CASES_BY_ID["same-export-ru-en"]
    propose_resolution(input_from_fixture(case))


def test_debug_logging_contains_counts_not_event_payload(caplog):
    case = CASES_BY_ID["same-export-ru-en"]
    with caplog.at_level(logging.DEBUG, logger="t09_events.resolution"):
        propose_resolution(input_from_fixture(case))
    assert "mentions=2 decisions=2" in caplog.text
    assert "country-x" not in caplog.text
    assert "doc-export" not in caplog.text


def test_untrusted_mention_id_cannot_escape_into_paths_or_urls():
    case = CASES_BY_ID["supplier-sanction-vs-export-ban"]
    raw = input_from_fixture(case).model_dump(mode="json")
    malicious = "mention/../../outside"
    raw["mentions"][0]["mention_id"] = malicious
    request = ResolutionInput.model_validate(raw)
    proposal = propose_resolution(request).proposal
    proposed_ids = [
        event.ref.object_id
        for decision in proposal.decisions
        for event in decision.proposed_events
    ]
    assert proposed_ids
    assert all("/" not in object_id and "\\" not in object_id and "?" not in object_id for object_id in proposed_ids)


def test_fixture_load_rejects_tampered_payload(tmp_path):
    original_path = __import__("t09_events.scenarios", fromlist=["__file__"]).__file__
    source = CASES_BY_ID["same-export-ru-en"]
    manifest_path = tmp_path / "tampered.json"
    manifest = {
        "sha256": "sha256:bad",
        "dataset_hash": source["input_data"]["dataset_hash"],
        "dataset_version": source["input_data"]["dataset_version"],
        "cases": [source],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    from t09_events.scenarios import load_cases as read_cases

    with pytest.raises(ValueError, match="fixture hash"):
        read_cases(manifest_path)
    assert original_path


def test_pinned_shared_dataset_canonical_and_file_hashes_are_checked():
    assert load_dataset()
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "provisional_not_gold_not_approved"


def test_materialized_mentions_use_the_pinned_events_read_vocabulary_versions():
    case = CASES_BY_ID["same-export-ru-en"]
    request = input_from_fixture(case)
    event_refs = {
        (record.event_type.namespace, record.event_type.version)
        for record in request.existing.events
    }
    predicate_refs = {
        (statement.predicate.namespace, statement.predicate.version)
        for record in request.existing.events
        for statement in record.statements
    }
    assert event_refs
    assert predicate_refs
    assert all((mention.event_type.namespace, mention.event_type.version) in event_refs for mention in request.mentions)
    assert all(
        (statement.predicate.namespace, statement.predicate.version) in predicate_refs
        for mention in request.mentions
        for statement in mention.statements
    )


def test_shared_dataset_path_override_cannot_escape_repository(monkeypatch, tmp_path):
    outside = tmp_path / "outside"
    monkeypatch.setenv("T09_TEST_SHARED_PATH", str(outside))
    with pytest.raises(ValueError, match="must remain under"):
        _shared_path("T09_TEST_SHARED_PATH", SHARED_DIR / "datasets", SHARED_DIR / "datasets")


def test_duplicate_mention_assignment_fails_contract_semantics():
    _, _, proposal = _proposal("same-export-ru-en")
    raw = proposal.model_dump(mode="json")
    raw["decisions"][1]["mention_ids"] = raw["decisions"][0]["mention_ids"]
    with pytest.raises(ValidationError, match="mention IDs must be assigned at most once"):
        EventChangeProposal.model_validate(raw)


def test_invalid_resolution_input_fails_closed():
    case = copy.deepcopy(CASES_BY_ID["same-export-ru-en"])
    raw = case["request"]
    raw.pop("existing")
    with pytest.raises(ValidationError):
        ResolutionInput.model_validate(raw)


def test_candidate_and_resolution_order_is_deterministic():
    case = CASES_BY_ID["same-export-ru-en"]
    request = input_from_fixture(case)
    first = propose_resolution(request).model_dump(mode="json")
    second = propose_resolution(request).model_dump(mode="json")
    assert first == second
    assert isinstance(retrieve_candidates(request.mentions[0], request.existing), list)


def test_proposal_id_tracks_effective_algorithm_policy():
    request = input_from_fixture(CASES_BY_ID["same-export-ru-en"])
    default = propose_resolution(request).proposal.proposal_id
    changed = propose_resolution(request, ResolutionPolicy(same_event_window_days=13)).proposal.proposal_id
    assert default != changed


def test_runtime_policy_threshold_controls_resolution():
    case = CASES_BY_ID["same-port-closure-two-sources"]
    raw = input_from_fixture(case).model_dump(mode="json")
    focus_id = raw["mentions"][0]["mention_id"]
    raw["mentions"][0]["effective_at"] = "2026-10-27T00:00:00Z"
    request = ResolutionInput.model_validate(raw)
    default_action = next(
        decision.action.value for decision in propose_resolution(request).proposal.decisions if focus_id in decision.mention_ids
    )
    narrow_action = next(
        decision.action.value
        for decision in propose_resolution(
            request,
            ResolutionPolicy(same_event_window_days=13),
        ).proposal.decisions
        if focus_id in decision.mention_ids
    )
    assert (default_action, narrow_action) == ("attach", "create")


@pytest.mark.parametrize(
    "values",
    [
        {"same_event_window_days": -1},
        {"near_name_candidate_threshold": -0.01},
        {"near_name_candidate_threshold": 1.01},
        {"candidate_limit": 0},
    ],
)
def test_invalid_resolution_policy_boundaries_fail(values):
    with pytest.raises(ValueError):
        ResolutionPolicy(**values)


def test_output_evidence_refs_are_unique_and_sorted():
    for case in CASES:
        proposal = propose_resolution(input_from_fixture(case)).proposal
        for decision in proposal.decisions:
            ids = [item.object_id for item in decision.evidence_refs]
            assert ids == sorted(set(ids))


def test_merge_defers_when_mention_time_is_incompatible_with_duplicate_records():
    case = CASES_BY_ID["merge-duplicate-export-records"]
    raw = input_from_fixture(case).model_dump(mode="json")
    for mention in raw["mentions"]:
        mention["effective_at"] = "2026-12-01T00:00:00Z"
        for statement in mention["statements"]:
            statement["validity"]["valid_from"] = "2026-10-13T00:00:00Z"
    for record in raw["existing"]["events"]:
        for statement in record["statements"]:
            statement["validity"]["valid_from"] = "2026-10-13T00:00:00Z"
        _refresh_record_hash(record)
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    assert all(decision.action.value != "merge" for decision in proposal.decisions)
    assert any(decision.action.value == "defer" for decision in proposal.decisions)


@pytest.mark.parametrize("disagreeing_status", ["disputed", "disproved"])
def test_merge_does_not_hide_disputed_or_disproved_predecessor(disagreeing_status):
    case = CASES_BY_ID["merge-duplicate-export-records"]
    raw = input_from_fixture(case).model_dump(mode="json")
    raw["existing"]["events"][1]["statements"][0]["epistemic_status"] = disagreeing_status
    _refresh_record_hash(raw["existing"]["events"][1])
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    assert all(decision.action.value != "merge" for decision in proposal.decisions)
    assert any(decision.action.value == "defer" for decision in proposal.decisions)


@pytest.mark.parametrize("mention_status", ["disputed", "disproved"])
def test_uncertain_mention_status_is_not_erased_by_duplicate_merge(mention_status):
    case = CASES_BY_ID["merge-duplicate-export-records"]
    raw = input_from_fixture(case).model_dump(mode="json")
    focus_id = case["input_data"]["focus_mention_id"]
    mention = next(row for row in raw["mentions"] if row["mention_id"] == focus_id)
    mention["statements"][0]["epistemic_status"] = mention_status
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    focus_decision = next(decision for decision in proposal.decisions if focus_id in decision.mention_ids)
    assert focus_decision.action.value == "defer"


def test_same_type_aggregate_with_distinct_facilities_is_split_not_attached():
    case = CASES_BY_ID["fire-same-title-north-east"]
    raw = input_from_fixture(case).model_dump(mode="json")
    first, second = raw["mentions"]
    second["provenance"]["source_refs"] = copy.deepcopy(first["provenance"]["source_refs"])
    aggregate = {
        "ref": {
            "owner": "Events",
            "object_id": "event-mixed-facilities",
            "revision": 1,
            "hash": "sha256:" + "0" * 64,
        },
        "event_type": copy.deepcopy(first["event_type"]),
        "lifecycle": "active",
        "statements": copy.deepcopy(first["statements"] + second["statements"]),
        "mention_ids": [first["mention_id"], second["mention_id"]],
        "lineage_refs": [],
        "missing_data": [],
    }
    _refresh_record_hash(aggregate)
    raw["existing"]["events"] = [aggregate]
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    split = [decision for decision in proposal.decisions if decision.action.value == "split"]
    assert len(split) == 1
    assert set(split[0].mention_ids) == {first["mention_id"], second["mention_id"]}
    assert len(split[0].target_refs) == 1 and len(split[0].proposed_events) == 2


def test_actor_object_role_inversion_blocks_exact_id_attachment():
    case = CASES_BY_ID["same-export-ru-en"]
    raw = input_from_fixture(case).model_dump(mode="json")
    focus_id = case["input_data"]["focus_mention_id"]
    mention = next(row for row in raw["mentions"] if row["mention_id"] == focus_id)
    mention["actors"], mention["objects"] = mention["objects"], mention["actors"]
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    focus_decision = next(decision for decision in proposal.decisions if focus_id in decision.mention_ids)
    assert focus_decision.action.value == "defer"


@pytest.mark.parametrize(
    "predicate",
    [
        {"namespace": "alfalab.events", "version": "1.0.1", "code": "increases_price"},
        {"namespace": "unrelated.events", "version": "1.0.1", "code": "identifies_supplier"},
        {"namespace": "alfalab.events", "version": "1.0.1", "code": "identifies_supplier"},
        {"namespace": "alfalab.events", "version": "1.0.0", "code": "identifies_supplier"},
    ],
)
def test_irrelevant_entity_fact_does_not_correct_missing_supplier(predicate):
    case = CASES_BY_ID["historical-supplier-change"]
    raw = input_from_fixture(case).model_dump(mode="json")
    focus_id = case["input_data"]["focus_mention_id"]
    mention = next(row for row in raw["mentions"] if row["mention_id"] == focus_id)
    unrelated = input_from_fixture(CASES_BY_ID["same-product-different-country"]).mentions[0].objects[0].model_dump(mode="json")
    mention["objects"] = [mention["objects"][0], unrelated]
    irrelevant_statement = mention["statements"][1]
    irrelevant_statement["predicate"] = predicate
    irrelevant_statement["value"]["value"] = unrelated
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    focus_decision = next(decision for decision in proposal.decisions if focus_id in decision.mention_ids)
    assert focus_decision.action.value == "defer"


def test_correction_clears_only_the_missing_field_it_supplies():
    case = CASES_BY_ID["same-export-with-correction"]
    raw = input_from_fixture(case).model_dump(mode="json")
    focus_id = case["input_data"]["focus_mention_id"]
    raw["existing"]["events"][0]["missing_data"].append({
        "path": "/event/successor_supplier",
        "reason": "not_provided",
        "detail": "The successor supplier remains unknown.",
    })
    _refresh_record_hash(raw["existing"]["events"][0])
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    focus_decision = next(decision for decision in proposal.decisions if focus_id in decision.mention_ids)
    assert focus_decision.action.value == "correct"
    successor = focus_decision.proposed_events[0]
    missing_paths = {item.path for item in successor.missing_data}
    assert "/event/valid_to" not in missing_paths
    assert "/event/successor_supplier" in missing_paths


def test_merged_lifecycle_record_is_not_candidate_or_target():
    case = CASES_BY_ID["same-export-ru-en"]
    raw = input_from_fixture(case).model_dump(mode="json")
    raw["existing"]["events"][0]["lifecycle"] = "merged"
    _refresh_record_hash(raw["existing"]["events"][0])
    request = ResolutionInput.model_validate(raw)
    candidates = retrieve_candidates(request.mentions[-1], request.existing)
    assert candidates == []
    proposal = propose_resolution(request).proposal
    assert all(
        request.existing.events[0].ref.object_id
        not in {ref.object_id for ref in decision.target_refs}
        for decision in proposal.decisions
    )


def test_distinct_mention_ids_cannot_collide_after_safe_id_normalization():
    case = CASES_BY_ID["supplier-sanction-vs-export-ban"]
    raw = input_from_fixture(case).model_dump(mode="json")
    raw["mentions"][0]["mention_id"] = "mention/a"
    raw["mentions"][1]["mention_id"] = "mention-a"
    proposal = propose_resolution(ResolutionInput.model_validate(raw)).proposal
    generated_ids = [
        event.ref.object_id
        for decision in proposal.decisions
        for event in decision.proposed_events
    ]
    assert len(generated_ids) == len(set(generated_ids)) == 2
    assert all(len(value) <= 120 for value in generated_ids)


def test_contract_policy_ref_is_fingerprinted_but_not_claimed_as_resolved():
    case = CASES_BY_ID["same-export-ru-en"]
    request = input_from_fixture(case)
    changed_raw = request.model_dump(mode="json")
    changed_raw["policy"]["id"] = "another-unmaterialized-policy"
    changed = ResolutionInput.model_validate(changed_raw)
    original_candidates = retrieve_candidates(request.mentions[-1], request.existing)
    changed_candidates = retrieve_candidates(changed.mentions[-1], changed.existing)
    assert [item.target.ref.object_id for item in original_candidates] == [
        item.target.ref.object_id for item in changed_candidates
    ]
    assert propose_resolution(request).proposal.proposal_id != propose_resolution(changed).proposal.proposal_id
