"""Isolated in-memory revision model for Graph.publish experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping

from alfalab_contracts.models import (
    CommandReceipt,
    GraphSnapshot,
    Graph_publishRequest,
    ObjectRef,
    PublishGraphOutput,
    StatementRef,
)
from alfalab_contracts.semantics import validate_dto

from .core import canonical_hash


class RevisionConflict(ValueError):
    """The request's expected graph revision is not the current revision."""


class IdempotencyConflict(ValueError):
    """An idempotency key was reused with a different command payload."""


class SourceReferenceMismatch(ValueError):
    """A candidate reference is not present in the explicitly materialized owner reads."""


@dataclass
class IsolatedGraphStore:
    """A per-test Python object; never connects to or persists a production DB."""

    _revisions: dict[str, list[GraphSnapshot]] = field(default_factory=dict)
    _idempotency: dict[tuple[str, str], tuple[str, PublishGraphOutput]] = field(default_factory=dict)
    _receipts: dict[tuple[str, str], CommandReceipt] = field(default_factory=dict)

    def publish(
        self,
        request: Graph_publishRequest,
        *,
        source_statement_refs: Mapping[tuple[str, int], StatementRef] | None,
    ) -> PublishGraphOutput:
        payload = request.payload
        candidate = payload.candidate
        if candidate.revision != 0:
            raise ValueError("Graph.publish requires a revision-zero candidate")
        validate_dto(candidate)
        operation_id = "Graph.publish"
        command_hash = canonical_hash(
            {
                "candidate": candidate.model_dump(mode="json"),
                "expected_revision": payload.expected_revision,
            }
        )
        idempotency_key = (operation_id, request.idempotency_key)
        prior = self._idempotency.get(idempotency_key)
        if prior is not None:
            prior_hash, prior_output = prior
            if prior_hash != command_hash:
                raise IdempotencyConflict("idempotency key is already bound to a different graph command")
            return prior_output.model_copy(deep=True)

        if source_statement_refs is None:
            raise SourceReferenceMismatch(
                "Graph.publish requires explicitly materialized source StatementRefs; no hidden owner read is performed"
            )
        candidate_refs: list[StatementRef] = []
        for node in candidate.nodes:
            candidate_refs.extend(node.statement_refs)
            candidate_refs.extend(node.provenance.input_statement_refs)
        for edge in candidate.edges:
            candidate_refs.extend(edge.statement_refs)
            candidate_refs.extend(edge.provenance.input_statement_refs)
        for reference in candidate_refs:
            aggregate = reference.aggregate_ref
            declared = any(
                str(slice_.owner) == str(aggregate.owner)
                and slice_.partition_id == aggregate.object_id
                and slice_.revision == aggregate.revision
                for slice_ in candidate.manifest.input_slices
            )
            if not declared:
                raise SourceReferenceMismatch(
                    "candidate StatementRef aggregate is absent from the graph manifest input slices"
                )
            key = (reference.statement_id, reference.revision)
            if source_statement_refs.get(key) != reference:
                raise SourceReferenceMismatch(
                    "candidate contains a StatementRef absent from or different in the explicit materialized source index"
                )

        revisions = self._revisions.get(candidate.graph_id, [])
        current_revision = revisions[-1].revision if revisions else 0
        if payload.expected_revision != current_revision:
            raise RevisionConflict(
                f"expected revision {payload.expected_revision}, current revision is {current_revision}"
            )
        next_revision = current_revision + 1
        published_wire = json.dumps(
            {
                **candidate.model_dump(mode="json"),
                "revision": next_revision,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        published = GraphSnapshot.model_validate_json(
            published_wire,
            strict=True,
        )
        validate_dto(published)
        projection_ref = ObjectRef(
            owner="Graph",
            object_id=published.graph_id,
            revision=next_revision,
            hash=canonical_hash(published),
        )
        committed_at = getattr(request.execution, "analytical_time", None)
        if committed_at is None:
            committed_at = published.manifest.as_of.known_as_of
        original_run_id = getattr(request.execution, "source_run_id", None) or request.request_id
        receipt = CommandReceipt(
            operation_id=operation_id,
            idempotency_key=request.idempotency_key,
            command_hash=command_hash,
            applied=True,
            changed_refs=[projection_ref],
            audit_id=f"audit-{command_hash[7:31]}",
            committed_at=committed_at,
            original_run_id=original_run_id,
        )
        output = PublishGraphOutput(projection_ref=projection_ref, receipt=receipt)
        validate_dto(output)

        new_revisions = [*revisions, published.model_copy(deep=True)]
        self._revisions[candidate.graph_id] = new_revisions
        self._receipts[idempotency_key] = receipt.model_copy(deep=True)
        self._idempotency[idempotency_key] = (command_hash, output.model_copy(deep=True))
        return output

    def snapshot(self, graph_id: str, revision: int) -> GraphSnapshot | None:
        for item in self._revisions.get(graph_id, []):
            if item.revision == revision:
                return item.model_copy(deep=True)
        return None

    def snapshots(self) -> Mapping[tuple[str, int], GraphSnapshot]:
        return {
            (graph_id, snapshot.revision): snapshot.model_copy(deep=True)
            for graph_id, revisions in self._revisions.items()
            for snapshot in revisions
        }

    def receipts(self) -> Mapping[tuple[str, str], CommandReceipt]:
        return {key: receipt.model_copy(deep=True) for key, receipt in self._receipts.items()}
