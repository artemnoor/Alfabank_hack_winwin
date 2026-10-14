from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from alfalab_contracts.models import (
    ApplyBusinessInput,
    BusinessSnapshot,
    EntityRef,
    EvidenceRecord,
    ObjectRef,
    ProfileInput,
    Provenance,
    QuestionAnswer,
    QuestionPreferences,
    QuestionsInput,
    ReadBusinessInput,
    TimeSlice,
)
from alfalab_contracts.semantics import validate_dto
from t10_business import (
    ApplyContext,
    ConfirmationNotAuthorized,
    RevisionConflict,
    TrustedOwnerPolicy,
    _canonical_json,
    _extract_claims,
    active_supplier_ids,
    apply_profile,
    propose_profile,
    propose_questions,
    read_profile,
)

from conftest import DATASET_DIR, DATASET_HASH


AS_OF = TimeSlice(valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z")
ROOT = Path(__file__).resolve().parents[3]


def _profile_input(company: EntityRef, description: str, existing=None) -> ProfileInput:
    return ProfileInput(
        company=company,
        description=description,
        documents=[],
        answers=[],
        existing=existing,
        as_of=AS_OF,
    )


def _event_input(profile: BusinessSnapshot, event, budget: int = 10, history=None) -> QuestionsInput:
    return QuestionsInput(profile=profile, event=event, question_history=history or [], budget=budget)


def _question_ids(result) -> list[str]:
    return [item.question_id for item in result.questions]


def _ref(owner: str, object_id: str, digest: str = "0" * 64) -> ObjectRef:
    return ObjectRef(owner=owner, object_id=object_id, revision=1, hash=f"sha256:{digest}")


def test_pinned_shared_dataset_has_22_provisional_scenarios(dataset):
    cases = dataset["t10_business_question_cases"]
    assert len(cases) == 22
    assert len({case["case_id"] for case in cases}) == 22
    assert all(case["manual_approval"] == "provisional" for case in cases)
    assert all(case["expected_properties"] for case in cases)
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_hash"] == DATASET_HASH


def test_scenario_index_hash_and_case_list_are_reproducible(dataset):
    path = ROOT / "spike" / "T10" / "fixtures" / "scenario-index.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = manifest.pop("data_hash")
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual = "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert actual == expected
    assert manifest["manual_approval"] == "provisional"
    assert set(manifest["scenario_ids"]) == {case["case_id"] for case in dataset["t10_business_question_cases"]}
    lock = json.loads((ROOT / manifest["contract_lock"]["path"]).read_text(encoding="utf-8"))
    lock_operations = lock.get("operations", lock)
    operations = {item["operation_id"]: item for item in lock_operations}
    for reference in manifest["operation_refs"]:
        pinned = operations[reference["operation_id"]]
        assert reference["contract_version"] == pinned["contract_version"]
        assert reference["schema_hash"] == pinned["schema_hash"]


@pytest.mark.parametrize(
    "case_id",
    [
        "sparse-export-country", "sparse-export-vendor", "skipped-is-not-no", "sparse-import-share",
        "b-export-purchase-volume", "b-export-alternative-supplier", "b-port-alternate-route",
        "b-sanction-scope", "b-budget-one-question", "b-budget-three-questions",
        "c-price-input-quantity", "c-contradictory-inventory", "c-port-route-check",
        "c-process-capacity", "c-historical-supplier", "declined-answer-preserved",
        "forecast-vs-actual", "tax-product-scope", "industry-only-no-profile-fact",
        "unknown-answer-not-negative", "question-preference-suppression", "investment-amount-unknown",
    ],
)
def test_every_shared_scenario_runs_offline_and_returns_contract(case_id, dataset, latest_profile, events):
    case = next(item for item in dataset["t10_business_question_cases"] if item["case_id"] == case_id)
    profile = latest_profile(case["company_id"])
    event = events[case["event_id"]]
    budget = 1 if case_id == "b-budget-one-question" else 10
    if case_id in {"sparse-export-country", "sparse-export-vendor"}:
        # These two scenarios test an unanswered sparse profile. The separate
        # skipped-answer case keeps the recorded skipped answer intact.
        profile = profile.model_copy(update={"answers": []})
    if case_id == "question-preference-suppression":
        profile = profile.model_copy(update={
            "preferences": profile.preferences.model_copy(update={"suppressed_targets": ["alternative_route"]})
        })
    question_input = _event_input(profile, event, budget)
    before = question_input.model_dump(mode="json")
    result = propose_questions(question_input)
    assert len(result.questions) <= min(budget, profile.preferences.max_questions)
    assert question_input.model_dump(mode="json") == before
    validate_dto(result)
    # A repeated invocation with the same materialized input is reproducible.
    assert result.model_dump(mode="json") == propose_questions(question_input).model_dump(mode="json")


@pytest.mark.parametrize(
    "case_id",
    [
        "sparse-export-country", "sparse-export-vendor", "skipped-is-not-no", "sparse-import-share",
        "b-export-purchase-volume", "b-export-alternative-supplier", "b-port-alternate-route",
        "b-sanction-scope", "b-budget-one-question", "b-budget-three-questions",
        "c-price-input-quantity", "c-contradictory-inventory", "c-port-route-check",
        "c-process-capacity", "c-historical-supplier", "declined-answer-preserved",
        "forecast-vs-actual", "tax-product-scope", "industry-only-no-profile-fact",
        "unknown-answer-not-negative", "question-preference-suppression", "investment-amount-unknown",
    ],
)
def test_shared_case_property_expectations(case_id, dataset, latest_profile, events):
    case = next(item for item in dataset["t10_business_question_cases"] if item["case_id"] == case_id)
    profile = latest_profile(case["company_id"])
    if case_id in {"sparse-export-country", "sparse-export-vendor"}:
        profile = profile.model_copy(update={"answers": []})
    if case_id == "question-preference-suppression":
        profile = profile.model_copy(update={
            "preferences": profile.preferences.model_copy(update={"suppressed_targets": ["alternative_route"]})
        })
    budget = 1 if case_id == "b-budget-one-question" else 10
    event = events[case["event_id"]]
    result = propose_questions(_event_input(profile, event, budget))
    questions = set(_question_ids(result))
    statements = profile.statements
    predicates = {statement.predicate.code for statement in statements}
    missing = {item.path for item in profile.missing_data}

    expected_question = {
        "sparse-export-country": "supplier_countries",
        "sparse-export-vendor": "supplier_names",
        "b-export-alternative-supplier": "alternative_supplier",
        "b-port-alternate-route": "alternative_route",
        "b-sanction-scope": "transaction_scope",
        "c-price-input-quantity": "procurement_quantity",
        "c-contradictory-inventory": "inventory_reconciliation",
        "c-port-route-check": "alternative_route",
        "forecast-vs-actual": "forecast_materialized",
        "tax-product-scope": "tax_scope",
        "unknown-answer-not-negative": "route",
        "investment-amount-unknown": "investment_amount",
    }.get(case_id)
    if expected_question:
        assert expected_question in questions, case_id
    if case_id == "skipped-is-not-no":
        assert any(answer.status == "skipped" for answer in profile.answers)
        assert not any(predicate.startswith("does_not_") for predicate in predicates)
    elif case_id == "sparse-import-share":
        assert "import_share" not in predicates
        assert "/procurement/import_share" in missing
    elif case_id == "b-export-purchase-volume":
        assert "/procurement/volume" in missing
        assert not predicates & {"procurement_volume", "purchase_volume"}
    elif case_id == "b-budget-one-question":
        assert len(result.questions) == 1
        assert result.questions[0].priority == "high"
    elif case_id == "b-budget-three-questions":
        assert len(result.questions) <= min(3, profile.preferences.max_questions)
    elif case_id == "c-process-capacity":
        assert "production_capacity" not in predicates
    elif case_id == "c-historical-supplier":
        assert "supplier-c-old" not in active_supplier_ids(profile, AS_OF.valid_as_of)
    elif case_id == "declined-answer-preserved":
        assert any(answer.status == "declined" for answer in profile.answers)
        assert "import_share" not in predicates
    elif case_id == "industry-only-no-profile-fact":
        assert result.questions == []
    elif case_id == "question-preference-suppression":
        assert "alternative_route" not in questions
    elif case_id == "c-port-route-check":
        assert "ships_via" in predicates


def test_sparse_product_profile_does_not_infer_supplier_country_or_volume(latest_profile):
    prior = latest_profile("company-a")
    company = prior.company
    proposed = propose_profile(_profile_input(company, "Мы продаём радиодетали."))
    predicates = {item.predicate.code for item in proposed.proposal.add_statements}
    assert predicates == {"trades_in"}
    assert not predicates & {"purchases_from", "sourcing_country", "procurement_volume", "import_share"}
    assert {item.path for item in proposed.proposal.missing_data} >= {
        "/dependencies/suppliers", "/sourcing/countries", "/procurement/volume", "/procurement/import_share"
    }
    statement = proposed.proposal.add_statements[0]
    assert statement.epistemic_status == "user_declared"
    assert statement.provenance.evidence_refs == []
    assert statement.provenance.origin_verified is False
    validate_dto(proposed)


def test_known_current_supplier_does_not_fill_unreported_volume(latest_profile, events):
    profile = latest_profile("company-b")
    proposed = propose_profile(_profile_input(profile.company, "", profile))
    assert any(item.path == "/procurement/volume" for item in proposed.proposal.missing_data)
    assert not any(item.predicate.code in {"procurement_volume", "purchase_volume"} for item in proposed.proposal.add_statements)
    assert "supplier_names" not in _question_ids(
        propose_questions(_event_input(profile, events["event-export-x-mk7"], budget=10))
    )


def test_a_skipped_answer_is_preserved_without_creating_a_negative_statement(profiles, events):
    profile = profiles["company-a"][0]
    answer = next(a for a in profile.answers if a.question_id == "supplier-countries")
    assert answer.status == "skipped"
    assert answer.value is None
    assert not any(statement.predicate.code == "does_not_source_country" for statement in profile.statements)
    output = propose_questions(_event_input(profile, events["event-export-x-mk7"]))
    assert "supplier_countries" not in _question_ids(output)
    assert not any("supplier_countries" in statement.predicate.code for statement in profile.statements)


def test_declined_answer_is_not_a_negative_claim_and_is_not_reasked(latest_profile, events):
    profile = latest_profile("company-b")
    answer = next(a for a in profile.answers if a.question_id == "procurement-share")
    assert answer.status == "declined" and answer.value is None
    assert not any(statement.predicate.code == "import_share" for statement in profile.statements)
    questions = propose_questions(_event_input(profile, events["event-export-x-mk7"]))
    assert "import_share" not in _question_ids(questions)


def test_hypothesis_and_explicit_negative_remain_separate_from_facts(latest_profile):
    company = latest_profile("company-a").company
    claims = _extract_claims("Компания может закупать компоненты у Вектора. Компания не закупает товар у Рубежа.")
    assert {claim.epistemic_status for claim in claims} == {"hypothetical", "user_declared"}
    assert any(claim.predicate == "purchases_from" and claim.epistemic_status == "hypothetical" for claim in claims)
    assert any(claim.predicate == "does_not_purchases_from" for claim in claims)
    proposal = propose_profile(_profile_input(company, "Компания может использовать модуль QX."))
    assert proposal.proposal.add_statements[0].epistemic_status == "hypothetical"
    assert any(item.path == "/products/components" for item in proposal.proposal.missing_data)
    negative = propose_profile(_profile_input(company, "Компания не закупает товар у Рубежа."))
    assert negative.proposal.add_statements[0].predicate.code == "does_not_purchases_from"
    # Denying one named relationship does not prove that no other supplier exists.
    assert any(item.path == "/dependencies/suppliers" for item in negative.proposal.missing_data)


def test_unsupported_inference_stays_unknown_for_industry_only_event(latest_profile, events):
    profile = latest_profile("company-a")
    original = [item.model_dump(mode="json") for item in profile.statements]
    result = propose_questions(_event_input(profile, events["event-industry-outlook"]))
    assert result.questions == []
    assert result.stop_reason == "no_useful_question"
    assert [item.model_dump(mode="json") for item in profile.statements] == original


def test_question_priority_is_event_conditioned_and_bounded(latest_profile, events):
    profile = latest_profile("company-a")
    export = propose_questions(_event_input(profile, events["event-export-x-mk7"], budget=1))
    port = propose_questions(_event_input(profile, events["event-port-vega"], budget=1))
    assert len(export.questions) == len(port.questions) == 1
    assert export.questions[0].question_id in {"supplier_names", "supplier_countries", "component_identity"}
    assert port.questions[0].question_id in {"route", "alternative_route", "inventory_cover", "delivery_lead_time"}
    assert "порядковая эвристика" in export.questions[0].why
    assert "не оценка вероятности." in export.questions[0].why


def test_zero_question_budget_returns_empty_bounded_output(latest_profile, events):
    profile = latest_profile("company-a")
    request = _event_input(profile, events["event-export-x-mk7"], budget=0)
    result = propose_questions(request)
    assert result.questions == []
    assert result.stop_reason == "budget"
    validate_dto(result)


@pytest.mark.parametrize("budget", [-1, 11])
def test_question_budget_contract_rejects_out_of_range_values(latest_profile, events, budget):
    with pytest.raises(ValidationError):
        _event_input(latest_profile("company-a"), events["event-export-x-mk7"], budget=budget)


def test_question_budget_is_capped_by_profile_preferences(latest_profile, events):
    profile = latest_profile("company-a")
    capped = profile.model_copy(update={"preferences": QuestionPreferences(
        max_questions=1, allow_event_prompts=True, suppressed_targets=[]
    )})
    result = propose_questions(_event_input(capped, events["event-export-x-mk7"], budget=10))
    assert len(result.questions) == 1


def test_event_prompt_preference_prevents_event_from_expanding_generic_gap_questions(latest_profile, events):
    profile = latest_profile("company-b")
    disabled = profile.model_copy(update={"preferences": profile.preferences.model_copy(
        update={"allow_event_prompts": False}
    )})
    with_event = propose_questions(_event_input(disabled, events["event-export-x-mk7"], budget=10))
    without_event = propose_questions(_event_input(disabled, None, budget=10))
    assert _question_ids(with_event) == _question_ids(without_event)
    assert _question_ids(with_event) == ["procurement_volume"]


def test_suppressed_question_target_is_not_proposed(latest_profile, events):
    profile = latest_profile("company-c")
    suppressed = profile.model_copy(update={"preferences": profile.preferences.model_copy(
        update={"suppressed_targets": ["alternative_route"]}
    )})
    result = propose_questions(_event_input(suppressed, events["event-port-vega"]))
    assert "alternative_route" not in _question_ids(result)


def test_unrecognized_or_sector_only_event_does_not_expand_missing_profile(latest_profile, events):
    profile = latest_profile("company-a")
    result = propose_questions(_event_input(profile, events["event-industry-outlook"]))
    assert result.questions == []


def test_contradictory_inventory_values_are_preserved_and_trigger_reconciliation(latest_profile, events):
    profile = latest_profile("company-c")
    old_ids = {statement.statement_id for statement in profile.statements}
    proposal = propose_profile(_profile_input(profile.company, "Запас сырья составляет 15 дней.", profile))
    inventory = [item for item in proposal.proposal.add_statements if item.predicate.code == "inventory_cover"]
    assert len(inventory) == 1
    assert inventory[0].statement_id not in old_ids
    assert any(set(item.statement_ids) >= {"c-stock-8-days", inventory[0].statement_id} for item in proposal.proposal.contradictions)
    assert any(set(item.statement_ids) >= {"c-stock-12-days", inventory[0].statement_id} for item in proposal.proposal.contradictions)
    assert len([x for x in profile.statements if x.predicate.code == "inventory_cover"]) == 2
    updated = profile.model_copy(update={"contradictions": proposal.proposal.contradictions})
    questions = propose_questions(_event_input(updated, events["event-port-vega"]))
    assert "inventory_reconciliation" in _question_ids(questions)


def test_question_history_keeps_declined_state_and_does_not_mutate_profile(latest_profile, events):
    profile = latest_profile("company-b")
    history = list(profile.answers)
    prior = json.dumps(profile.model_dump(mode="json"), sort_keys=True)
    propose_questions(_event_input(profile, events["event-export-x-mk7"], history=history))
    assert json.dumps(profile.model_dump(mode="json"), sort_keys=True) == prior
    assert history[0].status == "declined"


def test_profile_extraction_is_order_invariant_and_ignores_unrelated_text(latest_profile):
    company = latest_profile("company-a").company
    left = propose_profile(_profile_input(company, "Мы продаём радиодетали. Закупаем компоненты у Вектора."))
    right = propose_profile(_profile_input(company, "Закупаем компоненты у Вектора. Мы продаём радиодетали."))
    assert [x.model_dump(mode="json") for x in left.proposal.add_statements] == [
        x.model_dump(mode="json") for x in right.proposal.add_statements
    ]
    extended = propose_profile(_profile_input(company, "Мы продаём радиодетали. Закупаем компоненты у Вектора. Номер офиса не указан."))
    assert [x.model_dump(mode="json") for x in left.proposal.add_statements] == [
        x.model_dump(mode="json") for x in extended.proposal.add_statements
    ]


def test_semantic_change_from_actual_to_possible_changes_epistemic_status(latest_profile):
    company = latest_profile("company-a").company
    actual = propose_profile(_profile_input(company, "Мы закупаем компоненты у Вектора."))
    possible = propose_profile(_profile_input(company, "Мы можем закупать компоненты у Вектора."))
    assert actual.proposal.add_statements[0].epistemic_status == "user_declared"
    assert possible.proposal.add_statements[0].epistemic_status == "hypothetical"


def test_document_claim_has_source_provenance_and_is_not_auto_confirmed(latest_profile):
    from alfalab_contracts.models import RawMaterial

    company = latest_profile("company-a").company
    text = "Компания производит платы."
    content_hash = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    material = RawMaterial(
        material_id="material-1", source_id="source-1", source_url="https://example.invalid/company",
        title="Synthetic company notice", text=text, published_at="2026-10-01T00:00:00Z",
        collected_at="2026-10-02T00:00:00Z", content_hash=content_hash, language="ru",
        provenance=Provenance(origin="public_source", source_refs=[], input_statement_refs=[], producer_run_id=None,
                              derivation_method=None, evidence_refs=[], origin_verified=False),
    )
    request = ProfileInput(company=company, description="", documents=[material], answers=[], existing=None, as_of=AS_OF)
    response = propose_profile(request)
    statement = response.proposal.add_statements[0]
    assert statement.provenance.source_refs[0].object_id == "material-1"
    assert statement.provenance.source_refs[0].hash == content_hash
    assert statement.epistemic_status == "observed"
    assert statement.epistemic_status != "confirmed"
    validate_dto(response)


def test_apply_creates_isolated_snapshot_and_read_returns_explicitly_passed_snapshot(latest_profile):
    company = latest_profile("company-a").company
    profile_output = propose_profile(_profile_input(company, "Мы продаём радиодетали."))
    request = ApplyBusinessInput(proposal=profile_output.proposal, answers=[], preferences=None, evidence=[])
    applied = apply_profile(request, current=None, context=ApplyContext(as_of=AS_OF, idempotency_key="apply-1"))
    assert applied.snapshot.ref.revision == 1
    assert applied.receipt.applied is True
    validate_dto(applied)
    read_request = ReadBusinessInput(query={"kind": "business", "company_id": company.entity_id, "revision": 1, "as_of": None})
    read = read_profile(read_request, [applied.snapshot])
    assert read.snapshot == applied.snapshot
    validate_dto(read)


def test_apply_rejects_stale_revision_without_mutating_previous_snapshot(latest_profile):
    existing = latest_profile("company-a")
    proposal = propose_profile(_profile_input(existing.company, "Мы продаём радиодетали.", existing)).proposal
    stale = proposal.model_copy(update={"expected_revision": existing.ref.revision - 1})
    request = ApplyBusinessInput(proposal=stale, answers=[], preferences=None, evidence=[])
    before = existing.model_dump(mode="json")
    with pytest.raises(RevisionConflict):
        apply_profile(request, current=existing, context=ApplyContext(as_of=AS_OF, idempotency_key="stale"))
    assert existing.model_dump(mode="json") == before


def test_apply_preserves_statement_history_and_previous_snapshot_when_superseding(profiles):
    existing = profiles["company-a"][0]
    old = next(item for item in existing.statements if item.statement_id == "a-activity-v1")
    proposed = propose_profile(_profile_input(existing.company, "Мы продаём платы.", existing)).proposal
    supersede = {
        "aggregate_ref": existing.ref.model_dump(mode="json"),
        "statement_id": old.statement_id,
        "revision": old.revision,
        "hash": "sha256:" + hashlib.sha256(_canonical_json(old.model_dump(mode="json"))).hexdigest(),
    }
    proposal = type(proposed).model_validate({
        **proposed.model_dump(mode="json"),
        "supersede_refs": [supersede],
    })
    request = ApplyBusinessInput(proposal=proposal, answers=[], preferences=None, evidence=[])
    previous = existing.model_dump(mode="json")
    applied = apply_profile(request, current=existing, context=ApplyContext(as_of=AS_OF, idempotency_key="supersede-1"))
    closed = next(item for item in applied.snapshot.statements if item.statement_id == old.statement_id)
    assert closed.revision == old.revision + 1
    assert closed.validity.valid_to == AS_OF.valid_as_of
    assert closed.validity.recorded_at == AS_OF.known_as_of
    assert any(item.predicate.code == "trades_in" and item.statement_id != old.statement_id for item in applied.snapshot.statements)
    assert existing.model_dump(mode="json") == previous
    validate_dto(applied)


def test_confirmed_claim_requires_explicit_owner_policy_and_verified_anchor(latest_profile):
    company = latest_profile("company-a").company
    profile_output = propose_profile(_profile_input(company, "Мы продаём радиодетали."))
    statement = profile_output.proposal.add_statements[0]
    evidence_ref = _ref("Evidence", "evidence-activity", hashlib.sha256(b"evidence").hexdigest())
    confirmed = type(statement).model_validate({
        **statement.model_dump(mode="json"),
        "epistemic_status": "confirmed",
        "provenance": {**statement.provenance.model_dump(mode="json"), "evidence_refs": [evidence_ref.model_dump(mode="json")]},
    })
    proposal = profile_output.proposal.model_copy(update={"add_statements": [confirmed]})
    evidence = EvidenceRecord(
        ref=evidence_ref,
        source_ref=_ref("Documents", "source-activity"),
        locator={"kind": "text_span", "start": 0, "end": 1,
                 "quote_hash": "sha256:" + hashlib.sha256(b"q").hexdigest()},
        source_hash="sha256:" + hashlib.sha256(b"source").hexdigest(),
        verification="verified_anchor",
        source_reliability="unassessed",
        reliability_method=None,
    )
    request = ApplyBusinessInput(proposal=proposal, answers=[], preferences=None, evidence=[evidence])
    with pytest.raises(ConfirmationNotAuthorized):
        apply_profile(request, current=None, context=ApplyContext(as_of=AS_OF, idempotency_key="no-policy"))
    policy = TrustedOwnerPolicy(
        policy_id="test-owner-only", policy_hash="sha256:" + hashlib.sha256(b"policy").hexdigest(),
        confirmed_statement_ids=frozenset({confirmed.statement_id}),
        evidence_refs=frozenset({(evidence_ref.object_id, evidence_ref.revision, evidence_ref.hash)}),
    )
    accepted = apply_profile(request, current=None, context=ApplyContext(
        as_of=AS_OF, idempotency_key="explicit-policy", owner_policy=policy
    ))
    assert accepted.snapshot.statements[0].epistemic_status == "confirmed"


def test_anchor_only_with_wrong_hash_or_unverified_anchor_does_not_authorize_confirmed(latest_profile):
    company = latest_profile("company-a").company
    output = propose_profile(_profile_input(company, "Мы продаём радиодетали."))
    statement = output.proposal.add_statements[0]
    expected_ref = _ref("Evidence", "ev-a", hashlib.sha256(b"expected").hexdigest())
    confirmed = type(statement).model_validate({
        **statement.model_dump(mode="json"),
        "epistemic_status": "confirmed",
        "provenance": {**statement.provenance.model_dump(mode="json"), "evidence_refs": [expected_ref.model_dump(mode="json")]},
    })
    proposal = output.proposal.model_copy(update={"add_statements": [confirmed]})
    wrong_anchor = EvidenceRecord(
        ref=_ref("Evidence", "ev-a", hashlib.sha256(b"actual").hexdigest()),
        source_ref=_ref("Documents", "source-a"), locator={"kind": "text_span", "start": 0, "end": 1,
            "quote_hash": "sha256:" + hashlib.sha256(b"q").hexdigest()},
        source_hash="sha256:" + hashlib.sha256(b"source").hexdigest(), verification="verified_anchor",
        source_reliability="unassessed", reliability_method=None,
    )
    policy = TrustedOwnerPolicy(
        policy_id="test-owner-only", policy_hash="sha256:" + hashlib.sha256(b"policy").hexdigest(),
        confirmed_statement_ids=frozenset({confirmed.statement_id}),
        evidence_refs=frozenset({(expected_ref.object_id, expected_ref.revision, expected_ref.hash)}),
    )
    request = ApplyBusinessInput(proposal=proposal, answers=[], preferences=None, evidence=[wrong_anchor])
    with pytest.raises(ConfirmationNotAuthorized):
        apply_profile(request, current=None, context=ApplyContext(
            as_of=AS_OF, idempotency_key="hash-mismatch", owner_policy=policy
        ))


def test_bitemporal_read_uses_only_snapshots_known_and_valid_at_requested_time(profiles):
    history = profiles["company-a"]
    request = ReadBusinessInput(query={"kind": "business", "company_id": "company-a", "revision": None, "as_of": {
        "valid_as_of": "2026-09-01T00:00:00Z", "known_as_of": "2026-09-01T00:00:00Z"
    }})
    result = read_profile(request, history)
    assert result.snapshot.ref.revision == 1
    validate_dto(result)


def test_regression_disputed_scalar_values_are_not_dropped_from_conflict_detection(latest_profile):
    profile = latest_profile("company-c")
    assert all(item.epistemic_status == "disputed" for item in profile.statements if item.predicate.code == "inventory_cover")
    proposal = propose_profile(_profile_input(profile.company, "Запас сырья составляет 15 дней.", profile))
    assert any("c-stock-8-days" in item.statement_ids for item in proposal.proposal.contradictions)


def test_regression_industry_only_input_never_adds_supplier_country_or_volume(latest_profile, events):
    profile = latest_profile("company-a")
    result = propose_questions(_event_input(profile, events["event-industry-outlook"]))
    assert result.questions == []
    proposed = propose_profile(_profile_input(profile.company, "Торговля радиодеталями в отрасли растёт."))
    assert not {item.predicate.code for item in proposed.proposal.add_statements} & {
        "purchases_from", "sourcing_country", "procurement_volume", "import_share"
    }


def test_active_suppliers_excludes_historical_expired_supplier(latest_profile):
    profile = latest_profile("company-c")
    suppliers = active_supplier_ids(profile, "2026-10-14T00:00:00Z")
    assert "supplier-c-current" in suppliers
    assert "supplier-c-old" not in suppliers


def test_invalid_or_extra_contract_fields_are_rejected(latest_profile):
    company = latest_profile("company-a").company
    payload = {
        "company": company.model_dump(mode="json"), "description": "",
        "documents": [], "answers": [], "existing": None,
        "as_of": AS_OF.model_dump(mode="json"), "invented_supplier": "Acme",
    }
    with pytest.raises(ValidationError):
        ProfileInput.model_validate(payload)


def test_debug_logging_omits_raw_description_and_document_text(latest_profile, caplog):
    company = latest_profile("company-a").company
    secret = "CONFIDENTIAL-PROBE-12345"
    with caplog.at_level(logging.DEBUG, logger="t10_business"):
        propose_profile(_profile_input(company, f"Мы продаём радиодетали. {secret}"))
    assert "profile proposal built" in caplog.text
    assert secret not in caplog.text


def test_no_network_dependency_is_imported_or_called():
    source = (ROOT / "spike" / "T10" / "src" / "t10_business.py").read_text(encoding="utf-8")
    forbidden_imports = ("requests", "httpx", "urllib.request", "openai", "anthropic")
    assert not any(f"import {name}" in source or f"from {name}" in source for name in forbidden_imports)


def test_repeated_profile_proposal_and_canonical_serialization_are_byte_deterministic(latest_profile):
    company = latest_profile("company-a").company
    request = _profile_input(company, "Мы продаём радиодетали. Закупаем компоненты у Вектора.")
    first = propose_profile(request).model_dump(mode="json")
    second = propose_profile(request).model_dump(mode="json")
    assert _canonical_json(first) == _canonical_json(second)


def test_hypothetical_to_asserted_metamorphism_should_change_status(latest_profile):
    company = latest_profile("company-a").company
    asserted = propose_profile(_profile_input(company, "Мы закупаем компоненты у Вектора."))
    hypothetical = propose_profile(_profile_input(company, "Мы можем закупать компоненты у Вектора."))
    assert asserted.proposal.add_statements[0].epistemic_status != hypothetical.proposal.add_statements[0].epistemic_status



def test_regression_future_recorded_statement_does_not_fill_profile_or_hide_question(latest_profile, events):
    from alfalab_contracts.models import TimeSlice

    profile = latest_profile("company-a")
    source = next(
        statement for statement in latest_profile("company-b").statements
        if statement.predicate.code == "purchases_from" and statement.value.kind != "unknown"
    )
    historical = TimeSlice(valid_as_of="2026-10-01T00:00:00Z", known_as_of="2026-10-01T00:00:00Z")
    future_supplier = source.model_copy(update={
        "statement_id": "probe-future-supplier",
        "revision": 1,
        "subject": profile.company,
        "epistemic_status": type(source.epistemic_status)("user_declared"),
        "provenance": Provenance(
            origin="user_declared", source_refs=[], input_statement_refs=[], producer_run_id=None,
            derivation_method=None, evidence_refs=[], origin_verified=False,
        ),
        "validity": source.validity.model_copy(update={
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": None,
            "recorded_at": "2026-10-14T01:00:00Z",
        }),
    })
    historical_profile = profile.model_copy(update={
        "as_of": historical,
        "statements": [future_supplier],
    })
    request = ProfileInput(
        company=profile.company, description="", documents=[], answers=[],
        existing=historical_profile, as_of=historical,
    )
    proposal = propose_profile(request).proposal
    assert "/dependencies/suppliers" in {item.path for item in proposal.missing_data}
    assert "supplier_names" in _question_ids(propose_questions(
        _event_input(historical_profile, events["event-export-x-mk7"])
    ))
    assert active_supplier_ids(historical_profile, historical) == set()


def test_regression_apply_rejects_reviewers_foreign_supersede_probe_atomically(latest_profile):
    current = latest_profile("company-a")
    other = latest_profile("company-b")
    old = next(item for item in current.statements if item.statement_id == "a-activity-v2")
    proposal = propose_profile(_profile_input(current.company, "Мы продаём платы.", current)).proposal
    exact_review_probe = {
        "aggregate_ref": other.ref.model_dump(mode="json"),
        "statement_id": "a-activity-v2",
        "revision": 2,
        "hash": "sha256:" + "0" * 64,
    }
    invalid = type(proposal).model_validate({
        **proposal.model_dump(mode="json"),
        "supersede_refs": [exact_review_probe],
    })
    request = ApplyBusinessInput(proposal=invalid, answers=[], preferences=None, evidence=[])
    before = current.model_dump(mode="json")
    with pytest.raises(ValueError, match="aggregate_ref"):
        apply_profile(request, current=current, context=ApplyContext(as_of=AS_OF, idempotency_key="foreign-supersede-probe"))
    assert current.model_dump(mode="json") == before
    assert old.validity.valid_to is None


@pytest.mark.parametrize("mutation", ["stale_aggregate", "wrong_hash", "missing_statement", "duplicate_ref"])
def test_apply_rejects_each_incomplete_or_stale_supersede_reference_atomically(latest_profile, mutation):
    current = latest_profile("company-a")
    old = next(item for item in current.statements if item.statement_id == "a-activity-v2")
    proposal = propose_profile(_profile_input(current.company, "Мы продаём платы.", current)).proposal
    valid_ref = {
        "aggregate_ref": current.ref.model_dump(mode="json"),
        "statement_id": old.statement_id,
        "revision": old.revision,
        "hash": "sha256:" + hashlib.sha256(_canonical_json(old.model_dump(mode="json"))).hexdigest(),
    }
    if mutation == "stale_aggregate":
        stale = {**current.ref.model_dump(mode="json"), "revision": current.ref.revision - 1}
        refs = [{**valid_ref, "aggregate_ref": stale}]
    elif mutation == "wrong_hash":
        refs = [{**valid_ref, "hash": "sha256:" + "0" * 64}]
    elif mutation == "missing_statement":
        refs = [{**valid_ref, "statement_id": "foreign-statement"}]
    else:
        refs = [valid_ref, valid_ref]
    invalid = type(proposal).model_validate({**proposal.model_dump(mode="json"), "supersede_refs": refs})
    request = ApplyBusinessInput(proposal=invalid, answers=[], preferences=None, evidence=[])
    before = current.model_dump(mode="json")
    with pytest.raises(ValueError):
        apply_profile(request, current=current, context=ApplyContext(as_of=AS_OF, idempotency_key=f"bad-supersede-{mutation}"))
    assert current.model_dump(mode="json") == before
    assert old.validity.valid_to is None


def test_regression_conflicts_between_two_statements_in_one_new_proposal(latest_profile):
    company = latest_profile("company-a").company
    proposal = propose_profile(_profile_input(
        company, "Запас сырья составляет 8 дней; Запас сырья составляет 12 дней."
    )).proposal
    inventory = [item for item in proposal.add_statements if item.predicate.code == "inventory_cover"]
    assert {item.value.value for item in inventory} == {"8", "12"}
    assert any(set(item.statement_ids) == {entry.statement_id for entry in inventory} for item in proposal.contradictions)


def test_regression_apply_detects_incoming_answer_conflict_with_current_snapshot(latest_profile):
    from alfalab_contracts.models import TimeSlice

    base = latest_profile("company-c")
    eight_days = next(item for item in base.statements if item.statement_id == "c-stock-8-days")
    current = base.model_copy(update={"statements": [eight_days], "contradictions": []})
    proposal = propose_profile(_profile_input(current.company, "", current)).proposal
    answer = QuestionAnswer.model_validate({
        "question_id": "inventory_days",
        "status": "answered",
        "value": {"kind": "number", "value": "12", "unit": {"namespace": "units", "version": "1.0.0", "code": "day"}},
        "provenance": current.answers[0].provenance.model_dump(mode="json"),
    })
    request = ApplyBusinessInput(proposal=proposal, answers=[answer], preferences=None, evidence=[])
    output = apply_profile(request, current=current, context=ApplyContext(
        as_of=TimeSlice(valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z"),
        idempotency_key="incoming-answer-conflict",
    ))
    added = next(item for item in output.snapshot.statements if item.statement_id != eight_days.statement_id and item.predicate.code == "inventory_cover")
    assert any(set(item.statement_ids) == {eight_days.statement_id, added.statement_id} for item in output.snapshot.contradictions)
    validate_dto(output)


def test_warehouse_and_service_facts_are_explicit_provenanced_and_never_inferred(latest_profile, events):
    from alfalab_contracts.models import RawMaterial

    company = latest_profile("company-a").company
    text = "Сырьё хранится на складе Северный. Компания использует внешний сервис Облако Z."
    content_hash = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    material = RawMaterial(
        material_id="warehouse-service-material", source_id="warehouse-service-source",
        source_url="https://example.invalid/synthetic", title="Synthetic logistics and service note",
        text=text, published_at="2026-10-01T00:00:00Z", collected_at="2026-10-02T00:00:00Z",
        content_hash=content_hash, language="ru",
        provenance=Provenance(origin="public_source", source_refs=[], input_statement_refs=[], producer_run_id=None,
                              derivation_method=None, evidence_refs=[], origin_verified=False),
    )
    output = propose_profile(ProfileInput(
        company=company, description="", documents=[material], answers=[], existing=None, as_of=AS_OF,
    ))
    by_code = {item.predicate.code: item for item in output.proposal.add_statements}
    assert {"stores_at", "uses_service"} <= set(by_code)
    for predicate in ("stores_at", "uses_service"):
        statement = by_code[predicate]
        assert statement.epistemic_status == "observed"
        assert statement.provenance.source_refs[0].object_id == material.material_id
        assert statement.provenance.source_refs[0].hash == content_hash
    assert all(item.value.kind == "text" for item in by_code.values())
    assert {"/logistics/warehouses", "/dependencies/services"}.isdisjoint(
        {item.path for item in output.proposal.missing_data}
    )
    validate_dto(output)

    sparse = propose_profile(_profile_input(company, "Мы торгуем радиодеталями.")).proposal
    sparse_codes = {item.predicate.code for item in sparse.add_statements}
    assert not sparse_codes & {"stores_at", "uses_warehouse", "warehouse_location", "uses_service", "depends_on_service"}
    assert {"/logistics/warehouses", "/dependencies/services"} <= {item.path for item in sparse.missing_data}

    profile = latest_profile("company-a")
    profile = profile.model_copy(update={
        "preferences": profile.preferences.model_copy(update={"max_questions": 10})
    })
    warehouse_questions = propose_questions(_event_input(profile, events["event-port-vega"], budget=10))
    service_questions = propose_questions(_event_input(profile, events["event-cyber-orbita"], budget=10))
    assert "warehouse" in _question_ids(warehouse_questions)
    assert "service_dependency" in _question_ids(service_questions)
    validate_dto(warehouse_questions)
    validate_dto(service_questions)



def test_warehouse_and_service_answers_keep_source_provenance_and_negative_stays_unknown(latest_profile):
    company = latest_profile("company-a").company
    source_ref = ObjectRef(
        owner="Documents", object_id="user-answer-source", revision=1,
        hash="sha256:" + hashlib.sha256(b"source").hexdigest(),
    )
    provenance = Provenance(
        origin="user_declared", source_refs=[source_ref], input_statement_refs=[],
        producer_run_id=None, derivation_method=None, evidence_refs=[], origin_verified=False,
    )
    answers = [
        QuestionAnswer(
            question_id="warehouse", status="answered",
            value={"kind": "text", "value": "Склад Северный"}, provenance=provenance,
        ),
        QuestionAnswer(
            question_id="service_dependency", status="answered",
            value={"kind": "text", "value": "Облако Z"}, provenance=provenance,
        ),
    ]
    output = propose_profile(ProfileInput(
        company=company, description="", documents=[], answers=answers, existing=None, as_of=AS_OF,
    ))
    by_code = {item.predicate.code: item for item in output.proposal.add_statements}
    assert {"stores_at", "uses_service"} <= set(by_code)
    for code in ("stores_at", "uses_service"):
        statement = by_code[code]
        assert statement.provenance.source_refs == [source_ref]
        assert statement.epistemic_status == "user_declared"

    negative = propose_profile(_profile_input(
        company, "Сырьё не хранится на складе Северный. Компания не использует сервис Облако Z."
    )).proposal
    negative_codes = {item.predicate.code for item in negative.add_statements}
    assert "does_not_stores_at" in negative_codes
    assert "does_not_uses_service" in negative_codes
    assert {"/logistics/warehouses", "/dependencies/services"} <= {
        item.path for item in negative.missing_data
    }



def test_regression_apply_reconstructs_unknown_when_only_future_statement_exists(latest_profile, events):
    from alfalab_contracts.models import TimeSlice

    profile = latest_profile("company-a")
    supplier = next(
        statement for statement in latest_profile("company-b").statements
        if statement.predicate.code == "purchases_from" and statement.value.kind != "unknown"
    )
    historical = TimeSlice(valid_as_of="2026-10-01T00:00:00Z", known_as_of="2026-10-01T00:00:00Z")
    future_supplier = supplier.model_copy(update={
        "statement_id": "probe-apply-future-supplier",
        "revision": 1,
        "subject": profile.company,
        "epistemic_status": type(supplier.epistemic_status)("user_declared"),
        "provenance": Provenance(
            origin="user_declared", source_refs=[], input_statement_refs=[], producer_run_id=None,
            derivation_method=None, evidence_refs=[], origin_verified=False,
        ),
        "validity": supplier.validity.model_copy(update={
            "valid_from": "2026-01-01T00:00:00Z", "valid_to": None,
            "recorded_at": "2026-10-14T01:00:00Z",
        }),
    })
    current = profile.model_copy(update={
        "statements": [future_supplier],
        "missing_data": [item for item in profile.missing_data if item.path != "/dependencies/suppliers"],
    })
    proposal = propose_profile(ProfileInput(
        company=profile.company, description="", documents=[], answers=[], existing=current, as_of=historical,
    )).proposal.model_copy(update={"missing_data": []})
    request = ApplyBusinessInput(proposal=proposal, answers=[], preferences=None, evidence=[])
    result = apply_profile(request, current=current, context=ApplyContext(
        as_of=historical, idempotency_key="apply-future-unknown",
    ))
    assert "/dependencies/suppliers" in {item.path for item in result.snapshot.missing_data}
    assert not active_supplier_ids(result.snapshot, historical)
    validate_dto(result)
