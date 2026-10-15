"""T08-policy → extraction-only port → existing T09 EventMention DTOs."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Protocol

from alfalab_contracts import (
    EntityRef,
    EntityValue,
    EvidenceSpan,
    EventMention,
    ExtractionInput,
    ExtractionOutput,
    MissingDatum,
    Provenance,
    Statement,
    TextSpan,
    TextValue,
    Validity,
)
from alfalab_contracts.semantics import validate_dto
from pydantic import ValidationError

from .binding import CandidateEvent, EventSchemaBinding, candidates_from_t08
from .allowlist import load_approved_pilot_case
from .errors import (
    ExtractionProviderError,
    ExtractionValidationError,
    LiveCallsDisabled,
)
from .models import ExtractedMention, ParticipantClaim

_EVIDENCE_STATUS_TO_EPISTEMIC = {
    "reported": "unknown",
    "rumored": "hypothetical",
    "planned": "hypothetical",
    "denied": "disputed",
    "negated": "disputed",
    "disputed": "disputed",
    "unknown": "unknown",
}
_ABSOLUTE_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)


class CandidateExtractor(Protocol):
    """Extract exact claims for one already-selected event candidate."""

    def extract_candidate(
        self,
        *,
        case_id: str,
        article_text: str,
        classification: dict,
        candidate: CandidateEvent,
    ) -> list[ExtractedMention]: ...


@dataclass(frozen=True)
class ExtractionContext:
    """Trusted spike context supplied by the local experiment harness.

    ``trusted_synthetic`` is not a public request field. A future runtime must
    obtain classification and source refs from its server policy/owner ports.
    """

    case_id: str
    recorded_at: str
    origin: str
    origin_verified: bool
    source_refs: list
    producer_run_id: str | None
    trusted_synthetic: bool = True


@dataclass(frozen=True)
class ExperimentalFlowResult:
    status: Literal[
        "classification_missing",
        "no_content",
        "no_candidates",
        "no_candidates_with_unlisted_review",
        "held_for_insufficient_evidence",
        "held_with_unlisted_review",
        "extracted",
        "extracted_with_unlisted_review",
        "partial_provider_failure",
        "provider_unavailable",
    ]
    candidate_codes: list[str]
    held_codes: list[str]
    unlisted_review: bool
    output: ExtractionOutput | None
    failed_candidate_code: str | None = None
    safe_failure_code: str | None = None


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_prepared(material) -> None:
    try:
        validate_dto(material)
    except (TypeError, ValueError, ValidationError) as exc:
        raise ExtractionValidationError("prepared_material_invalid") from exc
    if material.quality != "valid" or not material.material.text.strip():
        raise ExtractionValidationError("prepared_material_not_extractable")
    if _sha256_text(material.material.text) != material.prepared_hash:
        raise ExtractionValidationError("prepared_material_hash_mismatch")


def _validate_context(
    context: ExtractionContext,
    *,
    prepared,
    classification: dict,
    taxonomy: dict,
) -> None:
    if (
        context.origin != "synthetic"
        or context.origin_verified is not True
        or context.trusted_synthetic is not True
        or prepared.material.provenance.origin != "synthetic"
        or prepared.material.provenance.origin_verified is not True
    ):
        raise ExtractionValidationError("external_egress_denied")
    if (
        not context.case_id
        or not isinstance(context.case_id, str)
        or not isinstance(classification, dict)
        or prepared.material.material_id != context.case_id
        or classification.get("case_id") != context.case_id
    ):
        raise ExtractionValidationError("trusted_case_context_invalid")
    if not isinstance(context.recorded_at, str):
        raise ExtractionValidationError("trusted_clock_value_missing")
    approved = load_approved_pilot_case(context.case_id, prepared.material.text)
    if (
        prepared.material.title != approved.case["title"]
        or classification != approved.classification
        or taxonomy != approved.taxonomy
    ):
        raise ExtractionValidationError("trusted_synthetic_case_not_allowlisted")


def _normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def _quote_bounds(text: str, value: str, quote: str) -> tuple[int, int]:
    if value not in quote:
        raise ExtractionValidationError("claim_value_not_inside_evidence_quote")
    first = text.find(quote)
    if first < 0 or text.find(quote, first + 1) >= 0:
        raise ExtractionValidationError("evidence_quote_not_found_or_ambiguous")
    return first, first + len(quote)


def _validate_company_event_relation_quote(
    company_value: str, event_value: str, quote: str
) -> None:
    """Require company and event evidence to occur in the same sentence.

    Co-occurrence elsewhere in a multi-sentence quote is not enough to turn a
    named entity into the event subject. This is a conservative text-boundary
    check, not a semantic entailment proof; the extracted relation stays
    unconfirmed and still needs downstream evidence review.
    """
    if quote.count(company_value) != 1 or quote.count(event_value) != 1:
        raise ExtractionValidationError("company_event_relation_unverified")
    company_start = quote.index(company_value)
    event_start = quote.index(event_value)
    company_end = company_start + len(company_value)
    event_end = event_start + len(event_value)
    if company_start < event_end and event_start < company_end:
        raise ExtractionValidationError("company_event_relation_unverified")
    between_start = min(company_end, event_end)
    between_end = max(company_start, event_start)
    if re.search(r"[.!?;\r\n]", quote[between_start:between_end]):
        raise ExtractionValidationError("company_event_relation_unverified")


def _entity_ref(
    *,
    name: str,
    kind: str,
    prepared_hash: str,
    binding: EventSchemaBinding,
    known_entities: list,
    unresolved_entities: dict[str, EntityRef],
) -> EntityRef:
    normalized = _normalize_name(name)
    for entity in known_entities:
        if _normalize_name(entity.display_name) == normalized:
            return entity
    kind_ref = binding.entity_kind_refs.get(kind, binding.entity_kind_refs["unknown"])
    entity_id = (
        "unresolved-"
        + hashlib.sha256(
            f"{prepared_hash}\0{kind}\0{normalized}".encode("utf-8")
        ).hexdigest()[:24]
    )
    entity = EntityRef(entity_id=entity_id, kind=kind_ref, display_name=name)
    unresolved_entities[entity.entity_id] = entity
    return entity


def _statement_id(
    material_hash: str, candidate_code: str, mention_ordinal: int, ordinal: int
) -> str:
    seed = (f"{material_hash}\0{candidate_code}\0{mention_ordinal}\0{ordinal}").encode(
        "utf-8"
    )
    return "statement-" + hashlib.sha256(seed).hexdigest()[:24]


def _mention_id(material_hash: str, candidate_code: str, ordinal: int) -> str:
    seed = f"{material_hash}\0{candidate_code}\0mention\0{ordinal}".encode("utf-8")
    return "mention-" + hashlib.sha256(seed).hexdigest()[:24]


def _provenance(context: ExtractionContext, binding: EventSchemaBinding) -> Provenance:
    return Provenance(
        origin=context.origin,
        source_refs=context.source_refs,
        input_statement_refs=[],
        producer_run_id=context.producer_run_id,
        derivation_method=binding.derivation_method,
        evidence_refs=[],
        origin_verified=context.origin_verified,
    )


def _missing(path: str, reason: str, detail: str) -> MissingDatum:
    return MissingDatum(path=path, reason=reason, detail=detail)


def _map_mention(
    mention: ExtractedMention,
    *,
    candidate: CandidateEvent,
    ordinal: int,
    material,
    known_entities: list,
    binding: EventSchemaBinding,
    context: ExtractionContext,
    unresolved_entities: dict[str, EntityRef],
) -> tuple[EventMention, list]:
    text = material.material.text
    if mention.assertion_status not in _EVIDENCE_STATUS_TO_EPISTEMIC:
        raise ExtractionValidationError("assertion_status_invalid")
    code_ref = binding.event_code_ref(candidate.code)
    epistemic_status = _EVIDENCE_STATUS_TO_EPISTEMIC[mention.assertion_status]
    provenance = _provenance(context, binding)
    validate_dto(provenance)
    validity = Validity(valid_from=None, valid_to=None, recorded_at=context.recorded_at)
    statements: list[Statement] = []
    evidence: list[EvidenceSpan] = []
    ordinal_counter = 0

    company_ref = None
    company_candidate_ref = None
    relation_roles = {"subject", "actor", "affected"}
    if mention.company is None and mention.company_role is not None:
        raise ExtractionValidationError("company_role_without_company")
    if mention.company is not None:
        _quote_bounds(text, mention.company.value, mention.company.quote)
        if mention.company_role is None:
            raise ExtractionValidationError("company_role_missing")
        if mention.company.quote != mention.event.quote:
            raise ExtractionValidationError("company_event_quote_mismatch")
        _validate_company_event_relation_quote(
            mention.company.value, mention.event.value, mention.company.quote
        )
        company_candidate_ref = _entity_ref(
            name=mention.company.value,
            kind="organization",
            prepared_hash=material.prepared_hash,
            binding=binding,
            known_entities=known_entities,
            unresolved_entities=unresolved_entities,
        )
        if mention.company_role in relation_roles:
            company_ref = company_candidate_ref

    participants: list[tuple[ParticipantClaim, EntityRef]] = []
    for participant in mention.participants:
        _quote_bounds(text, participant.value, participant.quote)
        ref = _entity_ref(
            name=participant.value,
            kind=participant.kind,
            prepared_hash=material.prepared_hash,
            binding=binding,
            known_entities=known_entities,
            unresolved_entities=unresolved_entities,
        )
        participants.append((participant, ref))

    subject = company_ref or next(
        (ref for participant, ref in participants if participant.role == "actor"),
        None,
    )
    missing: list[MissingDatum] = []
    if subject is None:
        subject = _entity_ref(
            name="Не указан в тексте",
            kind="unknown",
            prepared_hash=material.prepared_hash,
            binding=binding,
            known_entities=[],
            unresolved_entities=unresolved_entities,
        )
        missing.append(
            _missing("subject", "not_provided", "Текст не называет субъект события.")
        )
    if mention.company is None:
        missing.append(
            _missing(
                "company",
                "not_provided",
                "Компания не названа с точной опорой в тексте.",
            )
        )
    elif company_ref is None:
        role_detail = (
            "Компания указана как источник сообщения; она не связывается автоматически с событием."
            if mention.company_role == "reporter"
            else "Роль названной компании в событии не установлена; связь оставлена для проверки."
        )
        missing.append(_missing("company_relation", "unsupported", role_detail))

    def add_statement(
        *,
        field: str,
        value,
        quote: str,
        claim_value: str,
        predicate_field: str | None = None,
    ) -> Statement:
        nonlocal ordinal_counter
        start, end = _quote_bounds(text, claim_value, quote)
        statement = Statement(
            statement_id=_statement_id(
                material.prepared_hash, candidate.code, ordinal, ordinal_counter
            ),
            revision=1,
            subject=subject,
            predicate=binding.predicate_refs[predicate_field or field],
            value=value,
            epistemic_status=epistemic_status,
            validity=validity,
            provenance=provenance,
        )
        statements.append(statement)
        validate_dto(statement)
        evidence.append(
            EvidenceSpan(
                local_id="local-evidence-"
                + hashlib.sha256(
                    f"{material.prepared_hash}\0{start}\0{end}\0{statement.statement_id}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:24],
                material_hash=material.prepared_hash,
                locator=TextSpan(
                    kind="text_span",
                    start=start,
                    end=end,
                    quote_hash=_sha256_text(quote),
                ),
                claim_ids=[statement.statement_id],
            )
        )
        validate_dto(evidence[-1].locator)
        validate_dto(evidence[-1])
        ordinal_counter += 1
        return statement

    add_statement(
        field="event",
        value=TextValue(kind="text", value=mention.event.value),
        quote=mention.event.quote,
        claim_value=mention.event.value,
    )

    if mention.date is None:
        missing.append(
            _missing(
                "date",
                "not_provided",
                "В ответе извлечения нет даты с текстовой опорой.",
            )
        )
        effective_at = None
    else:
        add_statement(
            field="date",
            value=TextValue(kind="text", value=mention.date.value),
            quote=mention.date.quote,
            claim_value=mention.date.value,
        )
        effective_at = (
            mention.date.value
            if _ABSOLUTE_TIMESTAMP.fullmatch(mention.date.value)
            else None
        )
        if effective_at is None:
            missing.append(
                _missing(
                    "effective_at",
                    "unsupported",
                    "Дата сохранена как цитируемый текст; календарное время нельзя разрешить без явной даты и часового пояса.",
                )
            )

    if mention.location is None:
        missing.append(
            _missing(
                "location",
                "not_provided",
                "В ответе извлечения нет места с текстовой опорой.",
            )
        )
    else:
        add_statement(
            field="location",
            value=TextValue(kind="text", value=mention.location.value),
            quote=mention.location.quote,
            claim_value=mention.location.value,
        )

    if not participants:
        missing.append(
            _missing(
                "participants",
                "not_provided",
                "В ответе извлечения нет участников с текстовой опорой.",
            )
        )
    for participant, entity_ref in participants:
        participant_statement = add_statement(
            field="participant",
            value=EntityValue(kind="entity", value=entity_ref),
            quote=participant.quote,
            claim_value=participant.value,
        )
        # The same source span grounds the extracted participant role as well.
        add_statement(
            field="participant_role",
            value=TextValue(kind="text", value=participant.role),
            quote=participant.quote,
            claim_value=participant.value,
        )
        del participant_statement

    if not mention.circumstances:
        missing.append(
            _missing(
                "circumstances",
                "not_provided",
                "Дополнительные обстоятельства не извлечены с точной опорой.",
            )
        )
    for circumstance in mention.circumstances:
        add_statement(
            field="circumstance",
            value=TextValue(kind="text", value=circumstance.value),
            quote=circumstance.quote,
            claim_value=circumstance.value,
        )

    _quote_bounds(text, mention.status_quote, mention.status_quote)
    add_statement(
        field="assertion_status",
        value=TextValue(kind="text", value=mention.assertion_status),
        quote=mention.status_quote,
        claim_value=mention.status_quote,
    )

    actors = []
    if company_ref is not None and mention.company_role in {"subject", "actor"}:
        actors.append(company_ref)
    actors.extend(
        ref for participant, ref in participants if participant.role == "actor"
    )
    objects = [
        ref for participant, ref in participants if participant.role == "affected"
    ]
    if company_ref is not None and mention.company_role == "affected":
        objects.append(company_ref)
    # Stable de-duplication protects against a model repeating a name.
    actors = list({ref.entity_id: ref for ref in actors}.values())
    objects = list({ref.entity_id: ref for ref in objects}.values())
    event_mention = EventMention(
        mention_id=_mention_id(material.prepared_hash, candidate.code, ordinal),
        event_type=code_ref,
        actors=actors,
        objects=objects,
        statements=statements,
        effective_at=effective_at,
        missing_data=missing,
        provenance=provenance,
    )
    validate_dto(event_mention)
    return event_mention, evidence


def _validate_output_evidence(output: ExtractionOutput, prepared) -> None:
    """Verify every local evidence span still anchors one emitted statement."""
    text = prepared.material.text
    statements = {
        statement.statement_id
        for mention in output.mentions
        for statement in mention.statements
    }
    span_ids = [span.local_id for span in output.evidence_spans]
    if len(span_ids) != len(set(span_ids)):
        raise ExtractionValidationError("evidence_span_id_duplicate")
    linked_statement_ids: set[str] = set()
    for span in output.evidence_spans:
        validate_dto(span)
        locator = span.locator
        if (
            span.material_hash != prepared.prepared_hash
            or locator.end > len(text)
            or locator.start >= locator.end
            or _sha256_text(text[locator.start : locator.end]) != locator.quote_hash
            or not span.claim_ids
            or not set(span.claim_ids).issubset(statements)
        ):
            raise ExtractionValidationError("evidence_span_integrity_failure")
        linked_statement_ids.update(span.claim_ids)
    if linked_statement_ids != statements:
        raise ExtractionValidationError("statement_without_evidence")


def run_t08_to_t09(
    *,
    prepared,
    classification: dict | None,
    taxonomy: dict,
    extractor: CandidateExtractor,
    binding: EventSchemaBinding,
    context: ExtractionContext,
    known_entities: list | None = None,
) -> ExperimentalFlowResult:
    """Apply pinned T08 routing, call one extraction job per released candidate.

    Calls are sequential and stop at the first provider/validation failure.
    A missing or held Jev result never reaches the provider. Only trusted,
    verified synthetic inputs are eligible for this spike's egress profile.
    """
    known = list(known_entities or [])
    if classification is None:
        return ExperimentalFlowResult(
            status="classification_missing",
            candidate_codes=[],
            held_codes=[],
            unlisted_review=False,
            output=None,
        )
    if not prepared.material.text.strip():
        return ExperimentalFlowResult(
            status="no_content",
            candidate_codes=[],
            held_codes=[],
            unlisted_review=False,
            output=None,
        )
    _validate_prepared(prepared)
    _validate_context(
        context,
        prepared=prepared,
        classification=classification,
        taxonomy=taxonomy,
    )
    try:
        from policy_v2 import evaluate_result

        decision = evaluate_result(classification, taxonomy)
    except (ImportError, KeyError, TypeError, ValueError) as exc:
        raise ExtractionValidationError("jev_result_or_policy_invalid") from exc

    held_codes = list(decision["candidate_blocked_codes"])
    unlisted_review = bool(decision["unlisted_review"])
    if held_codes:
        return ExperimentalFlowResult(
            status="held_with_unlisted_review"
            if unlisted_review
            else "held_for_insufficient_evidence",
            candidate_codes=[],
            held_codes=held_codes,
            unlisted_review=unlisted_review,
            output=None,
        )
    codes = list(decision["candidate_codes"])
    if not codes:
        return ExperimentalFlowResult(
            status="no_candidates_with_unlisted_review"
            if unlisted_review
            else "no_candidates",
            candidate_codes=[],
            held_codes=[],
            unlisted_review=unlisted_review,
            output=None,
        )
    candidates = candidates_from_t08(codes, taxonomy, binding)
    source_text = prepared.material.text
    evidence_spans: list[dict] = []
    mentions: list = []
    missing: list = []
    unresolved_entities: dict[str, EntityRef] = {}
    failed_candidate_code = None
    safe_failure_code = None

    for candidate in candidates:
        # Validate the precise existing Understanding.extract payload shape.
        try:
            ExtractionInput(
                material=prepared,
                event_schema=binding.event_schema,
                hints=[binding.event_code_ref(candidate.code)],
                known_entities=known,
            )
            model_mentions = extractor.extract_candidate(
                case_id=context.case_id,
                article_text=source_text,
                classification=classification,
                candidate=candidate,
            )
            if not isinstance(model_mentions, list):
                raise ExtractionValidationError("provider_output_not_a_list")
            if not model_mentions:
                missing.append(
                    _missing(
                        f"hints/{candidate.code}",
                        "not_observed",
                        "Для переданного кандидата не найдено извлечение с проверяемой цитатой.",
                    )
                )
            for mention_index, model_mention in enumerate(model_mentions):
                if not isinstance(model_mention, ExtractedMention):
                    raise ExtractionValidationError("provider_output_schema_invalid")
                event_mention, spans = _map_mention(
                    model_mention,
                    candidate=candidate,
                    ordinal=len(mentions) + mention_index,
                    material=prepared,
                    known_entities=known,
                    binding=binding,
                    context=context,
                    unresolved_entities=unresolved_entities,
                )
                mentions.append(event_mention)
                evidence_spans.extend(spans)
        except LiveCallsDisabled:
            raise
        except ExtractionProviderError as exc:
            failed_candidate_code = candidate.code
            safe_failure_code = exc.code
            missing.append(
                _missing(
                    f"hints/{candidate.code}",
                    "unavailable",
                    "Поставщик недоступен; этот кандидат и последующие кандидаты не обработаны.",
                )
            )
            break
        except (
            ExtractionValidationError,
            ValidationError,
            KeyError,
            TypeError,
            ValueError,
        ):
            failed_candidate_code = candidate.code
            safe_failure_code = "provider_output_rejected"
            missing.append(
                _missing(
                    f"hints/{candidate.code}",
                    "unsupported",
                    "Ответ извлечения не прошёл локальную проверку и не был передан дальше.",
                )
            )
            break

    output = ExtractionOutput(
        mentions=mentions,
        evidence_spans=evidence_spans,
        unresolved_entities=list(unresolved_entities.values()),
        missing_data=missing,
    )
    try:
        _validate_output_evidence(output, prepared)
    except (ExtractionValidationError, ValueError, ValidationError):
        raise ExtractionValidationError("extraction_output_evidence_invalid") from None
    if failed_candidate_code:
        status = "partial_provider_failure" if mentions else "provider_unavailable"
    else:
        status = "extracted_with_unlisted_review" if unlisted_review else "extracted"
    return ExperimentalFlowResult(
        status=status,
        candidate_codes=codes,
        held_codes=[],
        unlisted_review=unlisted_review,
        output=output,
        failed_candidate_code=failed_candidate_code,
        safe_failure_code=safe_failure_code,
    )
