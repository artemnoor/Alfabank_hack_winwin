from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Sequence

from alfalab_contracts.models import (
    BusinessSnapshot,
    EventRecord,
    GraphSubgraph,
    Match,
    MatchingInput,
    MatchingOutput,
    MissingDatum,
    ObjectRef,
    Provenance,
    StatementRef,
    VersionedRef,
)
from alfalab_contracts._generated import Exposure
from alfalab_contracts.semantics import validate_matching_pair

METHOD = VersionedRef(
    id="spike.t13.matching",
    version="0.1.0",
    hash="sha256:7597671c1f9d71f1f9dd005727de94c5f9e9cec370b424435316d4d558b32707",
)
# Provisional synthetic pin only; its T11 result is never itself confirmation.
TEST_OWNER_POLICY_REF = VersionedRef(
    id="test-owner-policy-t09-t13-v1",
    version="1.0.1",
    hash="sha256:7ab45d5de57f60f612f11820a444bacf216cd77704f5e5598218eae7ca0e6327",
)
MODE_POLICY = {
    "strict": {"statuses": {"confirmed"}, "max_depth": 2, "stale_paths": False},
    "balanced": {"statuses": {"confirmed", "user_declared"}, "max_depth": 4, "stale_paths": False},
    "broad": {
        "statuses": {"confirmed", "user_declared", "inferred", "hypothetical"},
        "max_depth": 5,
        "stale_paths": True,
    },
}


@dataclass(frozen=True)
class EventContext:
    event_ref: ObjectRef
    event_type: str
    target_entity_ids: tuple[str, ...]
    evidence_refs: tuple[ObjectRef, ...]
    factual_status: str = "confirmed"
    current: bool = True
    sector_only: bool = False
    trust_claim_status: str = "not_provided"
    trust_final_status: str = "not_confirmed"
    owner_policy_ref: VersionedRef | None = None
    owner_policy_decision: str | None = None
    statement_refs: tuple[StatementRef, ...] = ()

    @property
    def owner_confirmed(self) -> bool:
        """Require a separately pinned, explicit owner confirmation.

        The prepared T11 policy only yields review eligibility and
        `not_confirmed`; neither state passes this gate.
        """
        return (
            self.factual_status == "confirmed"
            and self.trust_claim_status == "confirmed"
            and self.trust_final_status == "confirmed"
            and self.owner_policy_ref == TEST_OWNER_POLICY_REF
            and self.owner_policy_decision == "explicit_owner_confirmation"
        )

    @classmethod
    def from_record(cls, event: EventRecord) -> "EventContext":
        targets: set[str] = set()
        evidence: dict[tuple[str, str, int, str], ObjectRef] = {}
        statement_refs: dict[tuple[str, str, int, str, str, int, str], StatementRef] = {}
        target_statuses: list[str] = []
        for statement in event.statements:
            targets.add(statement.subject.entity_id)
            if statement.value.kind == "entity":
                targets.add(statement.value.value.entity_id)
                target_statuses.append(statement.epistemic_status.value)
            for ref in statement.provenance.evidence_refs:
                evidence[_ref_key(ref)] = ref
            for ref in statement.provenance.input_statement_refs:
                statement_refs[_statement_ref_key(ref)] = ref
        state = "confirmed" if target_statuses and all(s == "confirmed" for s in target_statuses) else "unknown"
        return cls(
            event_ref=event.ref,
            event_type=event.event_type.code,
            target_entity_ids=tuple(sorted(targets)),
            evidence_refs=tuple(evidence[k] for k in sorted(evidence)),
            factual_status=state,
            current=event.lifecycle.value == "active",
            statement_refs=tuple(statement_refs[k] for k in sorted(statement_refs)),
        )


def _ref_key(ref: ObjectRef) -> tuple[str, str, int, str]:
    return ref.owner.value, ref.object_id, ref.revision, ref.hash


def _statement_ref_key(ref: StatementRef) -> tuple[str, str, int, str, str, int, str]:
    aggregate = _ref_key(ref.aggregate_ref)
    return (*aggregate, ref.statement_id, ref.revision, ref.hash)


def _unique_missing(items: Iterable[MissingDatum]) -> list[MissingDatum]:
    by_key = {(item.path, item.reason.value, item.detail): item for item in items}
    return [by_key[key] for key in sorted(by_key)]


def _make_missing(path: str, reason: str, detail: str) -> MissingDatum:
    return MissingDatum(path=path, reason=reason, detail=detail)


def _graph_paths(
    graph: GraphSubgraph,
    company_id: str,
    targets: set[str],
    allowed_statuses: set[str],
    max_depth: int,
    limit: int = 8,
) -> list[tuple[str, tuple[str, ...]]]:
    """Return deterministic undirected paths made only from the supplied edge IDs."""
    nodes = {node.node_id: node for node in graph.snapshot.nodes}
    starts = sorted(node_id for node_id, node in nodes.items() if node.entity.entity_id == company_id)
    if not starts or not targets:
        return []
    edge_by_id = {edge.edge_id: edge for edge in graph.snapshot.edges}
    adjacency: dict[str, list[tuple[str, str]]] = {node_id: [] for node_id in nodes}
    for edge in graph.snapshot.edges:
        if edge.epistemic_status.value not in allowed_statuses:
            continue
        if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
            continue
        adjacency[edge.source_node_id].append((edge.edge_id, edge.target_node_id))
    for neighbors in adjacency.values():
        neighbors.sort()

    found: list[tuple[str, tuple[str, ...]]] = []
    visited_paths: set[tuple[str, ...]] = set()
    for start in starts:
        queue = deque([(start, tuple(), frozenset({start}))])
        while queue and len(found) < limit:
            node_id, edge_path, seen_nodes = queue.popleft()
            entity_id = nodes[node_id].entity.entity_id
            if edge_path and entity_id in targets:
                if edge_path not in visited_paths:
                    found.append((entity_id, edge_path))
                    visited_paths.add(edge_path)
                continue
            if len(edge_path) >= max_depth:
                continue
            for edge_id, next_node in adjacency[node_id]:
                if next_node in seen_nodes:
                    continue
                queue.append((next_node, edge_path + (edge_id,), seen_nodes | {next_node}))
    found.sort(key=lambda item: (len(item[1]), item[0], item[1]))
    return found[:limit]


def _profile_slice_is_in_graph(graph: GraphSubgraph, profile: BusinessSnapshot) -> bool:
    wanted = (profile.slice.owner.value, profile.slice.partition_id, profile.slice.revision, profile.slice.selection_key)
    return any(
        (item.owner.value, item.partition_id, item.revision, item.selection_key) == wanted
        for item in graph.snapshot.manifest.input_slices
    )


def _path_is_currently_usable(graph: GraphSubgraph, profile: BusinessSnapshot, mode: str) -> bool:
    return _profile_slice_is_in_graph(graph, profile) and (
        graph.freshness.value == "current" or bool(MODE_POLICY[mode]["stale_paths"])
    )


def _make_match(
    event: EventContext,
    profile: BusinessSnapshot,
    graph: GraphSubgraph,
    mode: str,
) -> MatchingOutput:
    policy = MODE_POLICY[mode]
    company_id = profile.company.entity_id
    event_targets = set() if event.sector_only else set(event.target_entity_ids)
    slice_aligned = _profile_slice_is_in_graph(graph, profile)
    found = _graph_paths(
        graph,
        company_id,
        event_targets,
        policy["statuses"],
        policy["max_depth"],
    ) if _path_is_currently_usable(graph, profile, mode) else []
    direct_mention = company_id in event_targets
    missing: list[MissingDatum] = list(profile.missing_data) + list(graph.snapshot.missing_data)
    if graph.freshness.value != "current":
        missing.append(_make_missing("/graph/freshness", "unavailable", "The supplied graph is not marked current."))
    if not slice_aligned:
        missing.append(_make_missing("/graph/input_slices", "unavailable", "The graph projection does not contain the exact Business slice revision supplied for this company."))
    if graph.snapshot.completeness.value != "complete_for_declared_slice":
        missing.append(_make_missing("/graph/completeness", "not_observed", "No path is scoped to this supplied partial graph; absence is not evidence of no dependency."))
    if graph.traversal_truncated:
        missing.append(_make_missing("/graph/traversal", "not_observed", "The supplied graph traversal was truncated."))
    if not event_targets:
        missing.append(_make_missing("/event/targets", "not_provided", "The event input has no company-specific target entity."))
    if not event.current:
        missing.append(_make_missing("/event/currentness", "unavailable", "The supplied event is inactive or outside its valid time interval."))
    if not event.owner_confirmed:
        missing.append(_make_missing("/event/trusted_confirmation", "unavailable", "The supplied event has no pinned trust result and explicit owner confirmation."))

    evidence_refs: dict[tuple[str, str, int, str], ObjectRef] = {_ref_key(ref): ref for ref in event.evidence_refs}
    edge_by_id = {edge.edge_id: edge for edge in graph.snapshot.edges}
    paths: list[list[str]] = []
    components: set[str] = set()
    for entity_id, path in found:
        paths.append(list(path))
        components.add(entity_id)
        for edge_id in path:
            for ref in edge_by_id[edge_id].evidence_refs:
                evidence_refs[_ref_key(ref)] = ref

    if found:
        statuses = {edge_by_id[eid].epistemic_status.value for path in paths for eid in path}
        positive_statuses = event.owner_confirmed and event.current and statuses == {"confirmed"} and graph.freshness.value == "current"
        exposure = Exposure.confirmed if positive_statuses else Exposure.potential
    elif direct_mention:
        exposure = Exposure.potential
        missing.append(_make_missing("/impact/mechanism", "not_observed", "The event names this company, but the supplied graph contains no business mechanism path."))
    elif (
        graph.snapshot.completeness.value == "complete_for_declared_slice"
        and slice_aligned
        and graph.freshness.value == "current"
        and not graph.traversal_truncated
        and not profile.missing_data
        and not profile.contradictions
    ):
        exposure = Exposure.none_found
    else:
        exposure = Exposure.unknown

    if event.factual_status in {"rumor", "disputed", "historical", "forecast", "unknown"}:
        exposure = Exposure.unknown if not found else Exposure.potential
        missing.append(_make_missing("/event/evidential_status", "unavailable", f"Event status {event.factual_status!r} limits a current exposure claim."))
    if event.trust_claim_status in {"not_confirmed", "disputed"}:
        exposure = Exposure.unknown
        missing.append(_make_missing("/event/trusted_confirmation", "unavailable", f"Upstream trust status {event.trust_claim_status!r} does not support an impact claim."))
    elif not event.current:
        exposure = Exposure.unknown if not found else Exposure.potential
    elif not event.owner_confirmed and found:
        exposure = Exposure.potential
    if profile.contradictions:
        missing.append(_make_missing("/profile/contradictions", "contradictory", "The supplied profile contains unresolved statements."))
    match = Match(
        match_id=f"match-{event.event_ref.object_id}-{company_id}-{mode}",
        event_ref=event.event_ref,
        company=profile.company,
        exposure=exposure,
        affected_components=sorted(components),
        edge_paths=paths,
        evidence_refs=[evidence_refs[k] for k in sorted(evidence_refs)],
        missing_data=_unique_missing(missing)[:100],
        provenance=Provenance(
            origin="synthetic",
            source_refs=[],
            input_statement_refs=[],
            producer_run_id=None,
            derivation_method=METHOD,
            evidence_refs=[evidence_refs[k] for k in sorted(evidence_refs)],
            origin_verified=False,
        ),
    )
    return match


def match_context(
    event: EventContext,
    graph: GraphSubgraph,
    profiles: Sequence[BusinessSnapshot],
    mode: str,
    limit: int = 20,
) -> MatchingOutput:
    """Core T13 matching policy over explicitly supplied event, graph, and profiles."""
    if mode not in MODE_POLICY:
        raise ValueError(f"unsupported mode: {mode}")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 through 100")
    scope = sorted(profile.company.entity_id for profile in profiles)
    if len(scope) != len(set(scope)):
        raise ValueError("duplicate company IDs in supplied profile scope")
    matches = [_make_match(event, profile, graph, mode) for profile in profiles]
    # none_found is represented by an empty match list; unknown is retained for sparse inputs.
    matches = [match for match in matches if match.exposure != Exposure.none_found]
    matches.sort(key=lambda match: match.company.entity_id)
    truncated_by_limit = len(matches) > limit
    matches = matches[:limit]
    missing_items = [datum for match in matches for datum in match.missing_data]
    if truncated_by_limit:
        missing_items.append(_make_missing("/matches", "not_observed", "The output was truncated by the caller-provided limit."))
    missing = _unique_missing(missing_items)
    complete = (
        graph.snapshot.completeness.value == "complete_for_declared_slice"
        and graph.freshness.value == "current"
        and not graph.traversal_truncated
        and not graph.missing_slices
        and not truncated_by_limit
        and all(_profile_slice_is_in_graph(graph, profile) for profile in profiles)
        and all(not profile.missing_data and not profile.contradictions for profile in profiles)
    )
    return MatchingOutput(
        matches=matches,
        candidate_scope=scope,
        search_complete_for_scope=complete,
        missing_data=missing[:1000],
    )


def match_contract(request: MatchingInput) -> MatchingOutput:
    event = EventContext.from_record(request.event)
    response = match_context(event=event, graph=request.graph, profiles=request.profiles, mode=request.mode.value, limit=request.limit)
    validate_matching_pair(request, response)
    return response
