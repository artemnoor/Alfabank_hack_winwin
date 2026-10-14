from __future__ import annotations

import copy
import ast
import hashlib
import json
import logging
from pathlib import Path

import pytest
from alfalab_contracts.models import SCHEMA_TYPES
from alfalab_contracts.registry import load_operation_registry, validate_operation_exchange

from evidence_trust import (
    AnchorIntegrity,
    SourceAssertion,
    assess_claim,
    check_anchor,
    evaluate_owner_policy,
    project_catalog_record,
    summarize_provenance,
)


def assertion_rows(bundle: dict, case: dict) -> list[SourceAssertion]:
    refs = set(case["evidence_refs"])
    return [SourceAssertion.from_mapping(row) for row in bundle["assertions"] if row["evidence_ref"] in refs]


def inputs_for_case(bundle: dict, case: dict):
    records = {key: project_catalog_record(bundle["records"][key]) for key in case["evidence_refs"]}
    sources = {
        records[key]["source_ref"]["object_id"]: copy.deepcopy(
            bundle["sources"][records[key]["source_ref"]["object_id"]]
        )
        for key in records
    }
    mutation = case["mutation"]
    if mutation == "wrong_quote":
        record = records["ev-export-official"]
        record["locator"]["start"] += 1
    elif mutation == "wrong_source_hash":
        record = records["ev-export-official"]
        record["source_hash"] = "sha256:" + "0" * 64
    elif mutation == "source_version_mismatch":
        record = records["ev-export-correction"]
        record["source_ref"]["revision"] += 1
    return records, sources


def assess_case(bundle: dict, case: dict):
    records, sources = inputs_for_case(bundle, case)
    observations = assertion_rows(bundle, case)
    assessment = assess_claim(
        case["claim_id"], observations, records, sources,
        valid_as_of=bundle["manifest"]["as_of"]["valid_as_of"],
        known_as_of=bundle["manifest"]["as_of"]["known_as_of"],
    )
    return assessment, records, sources, observations


def test_fixture_is_explicitly_provisional_and_pinned(t11_bundle: dict) -> None:
    fixture = t11_bundle["fixture"]
    assert fixture["origin"] == "synthetic"
    assert fixture["manual_approval"] == "provisional"
    assert fixture["provenance"]["model_outputs_used_as_labels"] is False
    assert fixture["provenance"]["external_facts_used"] is False
    assert fixture["dataset_ref"]["version"] == "1.0.1"
    assert len(fixture["cases"]) == 12


def test_fixture_and_shared_dataset_canonical_hashes_reproduce(t11_bundle: dict) -> None:
    fixture = copy.deepcopy(t11_bundle["fixture"])
    expected_fixture_hash = fixture.pop("content_hash")
    canonical = lambda value: json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    actual_fixture_hash = "sha256:" + hashlib.sha256(canonical(fixture)).hexdigest()
    actual_data_hash = "sha256:" + hashlib.sha256(canonical(t11_bundle["data"])).hexdigest()
    assert actual_fixture_hash == expected_fixture_hash
    assert actual_data_hash == t11_bundle["manifest"]["data_hash"]


@pytest.mark.parametrize("case_id", [
    "exact-anchor", "wrong-quote", "wrong-source-hash", "source-version-mismatch",
    "source-unavailable", "verified-rumor-wording", "ten-syndicated-copies",
    "independent-roots", "contradictory-stock", "stale-source", "model-hypothesis",
    "confirmed-needs-owner-policy",
])
def test_shared_t11_properties(case_id: str, t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == case_id)
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    anchor_states = {
        check_anchor(records[key], sources[records[key]["source_ref"]["object_id"]]).integrity.value
        for key in records
    }
    if not anchor_states:
        anchor_states = {"none"}
    assert case["expected_anchor"] in anchor_states
    assert assessment.status.value == case["expected_claim_status"]
    assert set(assessment.evidence_refs) == set(case["evidence_refs"])
    if case.get("mutation"):
        assert not assessment.verified_evidence_refs
    assert assessment.final_status != "confirmed"
    if "expected_distinct_roots" in case:
        assert assessment.distinct_supporting_publisher_roots == case["expected_distinct_roots"]
    if case.get("policy_allowed") is not None:
        policy = t11_bundle["policy"] if case.get("policy_mode") == "explicit" else None
        result = evaluate_owner_policy(
            case["statement_id"], assessment, observations, records, sources, policy,
            dataset_id=t11_bundle["manifest"]["dataset_id"],
        )
        assert result.eligible_for_owner_review is case["policy_allowed"]
        assert result.final_status != "confirmed"


def test_verified_anchor_is_not_source_truth_or_confirmation(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    assessment, records, sources, _ = assess_case(t11_bundle, case)
    anchor = check_anchor(records["ev-export-official"], sources["doc-export-official"])
    assert anchor.integrity is AnchorIntegrity.VERIFIED
    assert assessment.status.value == "supported_unconfirmed"
    assert assessment.final_status == "not_confirmed"


def test_rumor_anchor_does_not_assert_default(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "verified-rumor-wording")
    assessment, _, _, _ = assess_case(t11_bundle, case)
    assert assessment.status.value == "unknown"
    assert assessment.source_assertion_state == "mentions_only"


def test_reprints_collapse_to_one_origin(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "ten-syndicated-copies")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    summary = summarize_provenance(observations, records, sources)
    assert len(case["evidence_refs"]) == 10
    assert assessment.distinct_supporting_publisher_roots == 1
    assert summary.copy_count == 10
    assert summary.independent_root_count == 1
    assert assessment.final_status == "not_confirmed"


def test_conflict_preserves_both_anchors_and_values(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "contradictory-stock")
    assessment, _, _, _ = assess_case(t11_bundle, case)
    assert assessment.status.value == "disputed"
    assert set(assessment.evidence_refs) == {"ev-c-stock-8d", "ev-c-stock-12d"}
    assert set(assessment.asserted_values) == {"8 days", "12 days"}


def test_policy_is_scoped_and_only_returns_review_eligibility(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "independent-roots")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    allowed = evaluate_owner_policy(
        case["statement_id"], assessment, observations, records, sources,
        t11_bundle["policy"], dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    wrong_dataset = evaluate_owner_policy(
        case["statement_id"], assessment, observations, records, sources,
        t11_bundle["policy"], dataset_id="another-dataset",
    )
    assert allowed.eligible_for_owner_review is True
    assert "eligible" in allowed.decision
    assert allowed.final_status == "not_confirmed"
    assert allowed.policy_version == "1.0.1"
    assert allowed.policy_hash == "sha256:7ab45d5de57f60f612f11820a444bacf216cd77704f5e5598218eae7ca0e6327"
    assert wrong_dataset.eligible_for_owner_review is False
    assert "dataset_scope_mismatch" in wrong_dataset.reason_codes

    stale_policy = dict(t11_bundle["policy"], version="1.0.0")
    wrong_policy_version = evaluate_owner_policy(
        case["statement_id"], assessment, observations, records, sources,
        stale_policy, dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    assert wrong_policy_version.eligible_for_owner_review is False
    assert "unsupported_policy_schema_or_version" in wrong_policy_version.reason_codes


def test_policy_never_applies_to_unlisted_statement(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "independent-roots")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    result = evaluate_owner_policy(
        "unlisted-statement", assessment, observations, records, sources,
        t11_bundle["policy"], dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    assert result.eligible_for_owner_review is False
    assert "statement_not_authorized" in result.reason_codes


def test_policy_requires_statement_to_match_assessed_claim(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "contradictory-stock")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    result = evaluate_owner_policy(
        "c-warehouse", assessment, observations, records, sources,
        t11_bundle["policy"], dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    assert result.eligible_for_owner_review is False
    assert "statement_claim_mismatch" in result.reason_codes
    assert "claim_not_unambiguously_supported" in result.reason_codes


def test_policy_does_not_count_future_source_as_second_root(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "independent-roots")
    records, sources = inputs_for_case(t11_bundle, case)
    sources["doc-b-independent"]["published_at"] = "2026-10-15T08:00:00Z"
    observations = assertion_rows(t11_bundle, case)
    assessment = assess_claim(
        case["claim_id"], observations, records, sources, valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z"
    )
    result = evaluate_owner_policy(
        case["statement_id"], assessment, observations, records, sources,
        t11_bundle["policy"], dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    assert assessment.status.value == "supported_unconfirmed"
    assert assessment.distinct_supporting_publisher_roots == 1
    assert result.eligible_for_owner_review is False
    assert "insufficient_independent_publisher_roots" in result.reason_codes


def test_reliability_label_does_not_promote_claim(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    records["ev-export-official"]["source_reliability"] = "high"
    repeated = assess_claim(case["claim_id"], observations, records, sources, valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z")
    assert repeated.status.value == "supported_unconfirmed"
    assert repeated.final_status == "not_confirmed"


def test_source_version_and_hash_are_both_bound_to_immutable_source(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    _, records, sources, _ = assess_case(t11_bundle, case)
    record = copy.deepcopy(records["ev-export-official"])
    source = copy.deepcopy(sources["doc-export-official"])
    source["text"] += " tampered"
    check = check_anchor(record, source)
    assert check.integrity is AnchorIntegrity.INVALID
    assert "source_content_hash_mismatch" in check.reason_codes


def test_missing_publisher_root_is_not_counted_as_independent(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "independent-roots")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    for source in sources.values():
        source.pop("publisher_root_id", None)
    summary = summarize_provenance(observations, records, sources)
    assert summary.independent_root_count == 0
    assert "publisher_root_missing" in summary.reason_codes


def test_future_source_is_not_used_for_earlier_knowledge_snapshot(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    obs = assertion_rows(t11_bundle, case)
    result = assess_claim(case["claim_id"], obs, records, sources, valid_as_of="2026-10-12T00:00:00Z", known_as_of="2026-10-12T00:00:00Z")
    assert result.status.value == "unknown"
    assert "future_source_not_applicable" in result.reason_codes


def test_missing_source_publication_date_does_not_enter_as_of_claim(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    sources["doc-export-official"]["published_at"] = None
    result = assess_claim(
        case["claim_id"], assertion_rows(t11_bundle, case), records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    assert result.status.value == "unknown"
    assert "source_publication_time_missing" in result.reason_codes


def test_duplicate_annotations_from_one_source_do_not_create_independence(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    duplicate = SourceAssertion(
        annotation_id="duplicate-input",
        evidence_ref="ev-export-official",
        claim_id=case["claim_id"],
        relation="supports",
        value="export-restriction-announced",
        temporal_scope="current",
    )
    repeated = assess_claim(case["claim_id"], [*observations, duplicate], records, sources)
    assert repeated.distinct_supporting_publisher_roots == 1
    assert repeated.status.value == assessment.status.value


def test_assessment_preserves_anchor_and_annotation_provenance(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    assessment, _, _, _ = assess_case(t11_bundle, case)
    observed = assessment.observations[0]
    assert observed.source_ref == (
        "Documents", "doc-export-official", 1,
        "sha256:de49f2b304e98f8c58bbba9cd31474062316473a30e0ecea5cf492870d700698",
    )
    assert observed.anchor.locator_kind == "text_span"
    assert observed.anchor.locator_start == 41 and observed.anchor.locator_end == 73
    assert observed.anchor.quote_hash == "sha256:88cb1255106e2bad1c205589dcb7c33732ccc6bfe61dabf66c8d12e09e8d18a3"
    assert observed.annotation_provenance.startswith("t11-evidence-trust-cases-v1.0.0")
    assert observed.source_published_at == "2026-10-13T08:00:00Z"
    assert observed.source_collected_at == "2026-10-13T08:00:00Z"
    assert observed.source_type == "official_notice"
    assert observed.source_origin == "synthetic"


def test_codepoint_offsets_are_used_for_unicode_text() -> None:
    text = "Ёж😀 ограничение действует"
    start = text.index("ограничение")
    quote = text[start:]
    record = minimal_record(text, start, len(text), quote)
    source = minimal_source(text)
    result = check_anchor(record, source)
    assert result.integrity is AnchorIntegrity.VERIFIED
    assert result.locator_start == start


def test_span_boundaries_and_empty_span_fail_closed() -> None:
    text = "known source"
    source = minimal_source(text)
    for start, end in [(-1, 2), (0, len(text) + 1), (5, 5), (8, 2)]:
        record = minimal_record(text, max(start, 0), max(end, 0), text[max(start, 0):max(end, 0)])
        record["locator"]["start"] = start
        record["locator"]["end"] = end
        assert check_anchor(record, source).integrity is AnchorIntegrity.INVALID


def test_whole_artifact_anchor_checks_exact_document_hash() -> None:
    text = "whole immutable artifact"
    source = minimal_source(text)
    record = minimal_record(text, 0, len(text), text)
    record["locator"] = {"kind": "whole_artifact"}
    assert check_anchor(record, source).integrity is AnchorIntegrity.VERIFIED
    source["content_hash"] = "sha256:" + "1" * 64
    assert check_anchor(record, source).integrity is AnchorIntegrity.INVALID


def test_business_whole_artifact_is_explicitly_unavailable_without_owner_snapshot() -> None:
    text = "business snapshot payload"
    source = minimal_source(text)
    source["owner"] = "Business"
    record = minimal_record(text, 0, len(text), text)
    record["source_ref"]["owner"] = "Business"
    record["locator"] = {"kind": "whole_artifact"}
    result = check_anchor(record, source)
    assert result.integrity is AnchorIntegrity.UNAVAILABLE
    assert result.reason_codes == ("unsupported_source_owner",)


def test_invalid_source_snapshot_fails_closed() -> None:
    text = "source"
    record = minimal_record(text, 0, len(text), text)
    result = check_anchor(record, None)  # type: ignore[arg-type]
    assert result.integrity is AnchorIntegrity.UNAVAILABLE
    assert result.reason_codes == ("source_snapshot_invalid",)


def test_strict_evidence_dto_rejects_experimental_annotation_fields(t11_bundle: dict) -> None:
    catalog = t11_bundle["records"]["ev-export-official"]
    with pytest.raises(Exception):
        SCHEMA_TYPES["EvidenceRecord"].model_validate_json(
            json.dumps(catalog, ensure_ascii=False, separators=(",", ":")), strict=True
        )
    projected = project_catalog_record(catalog)
    validated = SCHEMA_TYPES["EvidenceRecord"].model_validate_json(
        json.dumps(projected, ensure_ascii=False, separators=(",", ":")), strict=True
    )
    assert validated.verification.value == "verified_anchor"


def test_materialized_evidence_read_exchange_matches_normative_contract(t11_paths: dict) -> None:
    registry, contracts = load_operation_registry(
        t11_paths["root"] / "docs/specs/framework-v1/contracts/operations.json",
        t11_paths["root"] / "docs/specs/framework-v1/contracts/openapi.json",
    )
    fixture = json.loads(t11_paths["evidence_read"].read_text(encoding="utf-8"))
    request = json.dumps(fixture["request"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    response = json.dumps(fixture["response"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    parsed_request, parsed_response = validate_operation_exchange(
        contracts["Evidence.read"], request, response
    )
    assert parsed_request.payload.query.refs
    assert parsed_response.status.value == "success"
    assert registry.version == "1.0.0"


def test_register_input_shape_matches_normative_dto_without_invoking_owner(t11_paths: dict, t11_bundle: dict) -> None:
    _, contracts = load_operation_registry(
        t11_paths["root"] / "docs/specs/framework-v1/contracts/operations.json",
        t11_paths["root"] / "docs/specs/framework-v1/contracts/openapi.json",
    )
    evidence = t11_bundle["records"]["ev-export-official"]
    payload = {
        "evidence_id": "ev-t11-register-shape-only",
        "expected_revision": 0,
        "source_ref": evidence["source_ref"],
        "locator": evidence["locator"],
    }
    wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    parsed = contracts["Evidence.register"].input_type.model_validate_json(wire, strict=True)
    assert parsed.evidence_id == payload["evidence_id"]
    assert parsed.source_ref.object_id == "doc-export-official"
    assert contracts["Evidence.register"].descriptor.kind == "command"


def test_assertion_annotation_input_rejects_unknown_relations() -> None:
    with pytest.raises(ValueError):
        SourceAssertion.from_mapping({
            "annotation_id": "bad", "evidence_ref": "ev", "claim_id": "claim",
            "relation": "probably_true", "value": None, "temporal_scope": "current",
        })


def test_deterministic_across_assertion_order(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "contradictory-stock")
    _, records, sources, observations = assess_case(t11_bundle, case)
    first = assess_claim(case["claim_id"], observations, records, sources)
    second = assess_claim(case["claim_id"], list(reversed(observations)), records, sources)
    assert first == second


def test_logger_never_emits_source_text_or_quotes(caplog: pytest.LogCaptureFixture) -> None:
    secret = "SYNTHETIC_SECRET_DO_NOT_LOG_9f7c"
    source = minimal_source(secret)
    record = minimal_record(secret, 0, len(secret), secret)
    caplog.set_level(logging.DEBUG, logger="t11.evidence_trust")
    check_anchor(record, source)
    assert secret not in caplog.text
    assert "source_text=" not in caplog.text


def test_missing_source_and_unknown_claim_are_not_negative_facts() -> None:
    result = assess_claim("unseen-claim", [], {}, {})
    assert result.status.value == "unknown"
    assert result.source_assertion_state == "none"
    assert result.final_status == "not_confirmed"


def test_missing_evidence_ref_is_preserved_as_unverified_provenance() -> None:
    assertion = SourceAssertion(
        annotation_id="ann-missing-ref",
        evidence_ref="ev-not-materialized",
        claim_id="claim-with-missing-source",
        relation="supports",
        value="reported value",
        temporal_scope="current",
    )
    result = assess_claim(
        assertion.claim_id, [assertion], {}, {}, valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z"
    )
    assert result.status.value == "unknown"
    assert result.source_assertion_state == "unverified"
    assert result.evidence_refs == ("ev-not-materialized",)
    assert "evidence_ref_missing" in result.reason_codes


def test_prototype_has_no_network_or_model_imports(t11_paths: dict) -> None:
    source_path = t11_paths["t11"] / "src" / "evidence_trust.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "urllib", "socket", "openai", "anthropic", "transformers"}
    assert imported_roots.isdisjoint(forbidden)


def minimal_source(text: str) -> dict:
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "document_id": "doc-test", "version": 1, "availability": "available",
        "content_hash": digest, "text": text, "publisher_root_id": "root-test",
        "published_at": "2026-10-13T00:00:00Z",
    }


def minimal_record(text: str, start: int, end: int, quote: str) -> dict:
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    quote_hash = "sha256:" + hashlib.sha256(quote.encode("utf-8")).hexdigest()
    return {
        "ref": {"owner": "Evidence", "object_id": "ev-test", "revision": 1,
                "hash": "sha256:" + "2" * 64},
        "source_ref": {"owner": "Documents", "object_id": "doc-test", "revision": 1,
                       "hash": digest},
        "locator": {"kind": "text_span", "start": start, "end": end, "quote_hash": quote_hash},
        "source_hash": digest, "verification": "verified_anchor",
        "source_reliability": "unassessed", "reliability_method": None,
    }


def test_pre_cutoff_publication_collected_after_known_as_of_is_not_applicable(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    source = sources["doc-export-official"]
    source["published_at"] = "2026-10-13T08:00:00Z"
    source["collected_at"] = "2026-10-15T08:00:00Z"
    result = assess_claim(
        case["claim_id"], assertion_rows(t11_bundle, case), records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    assert result.status.value == "unknown"
    assert result.observations[0].applicable_as_of is False
    assert "source_registered_after_knowledge_snapshot" in result.reason_codes


def test_missing_registration_time_is_unknown_even_with_old_publication(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    source = sources["doc-export-official"]
    source["published_at"] = "2026-10-13T08:00:00Z"
    source.pop("collected_at")
    result = assess_claim(
        case["claim_id"], assertion_rows(t11_bundle, case), records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    assert result.status.value == "unknown"
    assert result.observations[0].applicable_as_of is False
    assert "source_registration_time_missing" in result.reason_codes


def test_caller_edited_policy_allow_list_is_not_eligible(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "independent-roots")
    records, sources = inputs_for_case(t11_bundle, case)
    new_claim = "not-authorized-claim"
    assertions = [
        SourceAssertion.from_mapping({**row, "claim_id": new_claim})
        for row in t11_bundle["assertions"]
        if row["evidence_ref"] in set(case["evidence_refs"])
    ]
    assessment = assess_claim(
        new_claim, assertions, records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    modified_policy = copy.deepcopy(t11_bundle["policy"])
    modified_policy["authorized_statement_ids"] = [new_claim]
    result = evaluate_owner_policy(
        new_claim, assessment, assertions, records, sources,
        modified_policy, dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    assert result.eligible_for_owner_review is False
    assert "policy_content_hash_mismatch" in result.reason_codes
    assert result.final_status == "not_confirmed"


def test_late_collected_source_cannot_unlock_historical_owner_policy(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "independent-roots")
    records, sources = inputs_for_case(t11_bundle, case)
    sources["doc-b-independent"]["published_at"] = "2026-10-06T08:00:00Z"
    sources["doc-b-independent"]["collected_at"] = "2026-10-15T08:00:00Z"
    assertions = assertion_rows(t11_bundle, case)
    assessment = assess_claim(
        case["claim_id"], assertions, records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    result = evaluate_owner_policy(
        case["statement_id"], assessment, assertions, records, sources,
        t11_bundle["policy"], dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    assert assessment.status.value == "supported_unconfirmed"
    assert assessment.distinct_supporting_publisher_roots == 1
    assert result.eligible_for_owner_review is False
    assert "insufficient_independent_publisher_roots" in result.reason_codes


@pytest.mark.parametrize("registration_time", ["not-a-timestamp", "2026-10-15T08:00:00"])
def test_invalid_or_timezone_naive_registration_time_is_not_applicable(
    t11_bundle: dict, registration_time: str,
) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    source = sources["doc-export-official"]
    source["published_at"] = "2026-10-13T08:00:00Z"
    source["collected_at"] = registration_time
    result = assess_claim(
        case["claim_id"], assertion_rows(t11_bundle, case), records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    assert result.status.value == "unknown"
    assert result.observations[0].applicable_as_of is False
    assert "source_registration_time_invalid" in result.reason_codes


def test_later_recorded_at_controls_knowledge_cutoff(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    source = sources["doc-export-official"]
    source["published_at"] = "2026-10-13T08:00:00Z"
    source["collected_at"] = "2026-10-13T08:00:00Z"
    source["recorded_at"] = "2026-10-15T08:00:00Z"
    result = assess_claim(
        case["claim_id"], assertion_rows(t11_bundle, case), records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    assert result.status.value == "unknown"
    assert result.observations[0].source_registration_at == "2026-10-15T08:00:00Z"
    assert result.observations[0].source_registration_method == "recorded_at"
    assert "source_registered_after_knowledge_snapshot" in result.reason_codes


def test_recorded_at_can_supply_registration_time_when_collection_time_is_absent(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    source = sources["doc-export-official"]
    source.pop("collected_at")
    source["recorded_at"] = "2026-10-13T08:00:00Z"
    result = assess_claim(
        case["claim_id"], assertion_rows(t11_bundle, case), records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    assert result.status.value == "supported_unconfirmed"
    assert result.observations[0].applicable_as_of is True
    assert result.observations[0].source_registration_method == "recorded_at"


def test_owner_policy_rechecks_registration_time_against_assessment_slice(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "independent-roots")
    assessment, records, sources, observations = assess_case(t11_bundle, case)
    assert assessment.distinct_supporting_publisher_roots == 2
    sources["doc-b-independent"]["collected_at"] = "2026-10-15T08:00:00Z"
    result = evaluate_owner_policy(
        case["statement_id"], assessment, observations, records, sources,
        t11_bundle["policy"], dataset_id=t11_bundle["manifest"]["dataset_id"],
    )
    assert result.eligible_for_owner_review is False
    assert "source_registered_after_knowledge_snapshot" in result.reason_codes


def test_published_at_uses_valid_time_independently_of_known_time(t11_bundle: dict) -> None:
    case = next(row for row in t11_bundle["fixture"]["cases"] if row["case_id"] == "exact-anchor")
    records, sources = inputs_for_case(t11_bundle, case)
    source = sources["doc-export-official"]
    source["published_at"] = "2026-10-15T08:00:00Z"
    source["collected_at"] = "2026-10-13T08:00:00Z"
    result = assess_claim(
        case["claim_id"], assertion_rows(t11_bundle, case), records, sources,
        valid_as_of="2026-10-14T00:00:00Z", known_as_of="2026-10-14T00:00:00Z",
    )
    assert result.status.value == "unknown"
    assert "future_source_not_applicable" in result.reason_codes
    assert "source_registered_after_knowledge_snapshot" not in result.reason_codes
