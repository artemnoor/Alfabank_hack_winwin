"""Bounded deterministic Graph.query prototype over supplied snapshots."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Mapping, Sequence

from alfalab_contracts.models import (
    CommandReceipt,
    CodeRef,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphSubgraph,
    KnowledgeSlice,
    MissingDatum,
    ObjectRef,
    QueryGraphInput,
    ReceiptQuery,
    ReceiptResult,
    StatementRef,
    SubgraphResult,
)

logger = logging.getLogger(__name__)
StatementIdentity = tuple[str, str, int, str, int]


class GraphQueryError(ValueError):
    """A graph query cannot safely satisfy the requested selection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _slice_key(item: KnowledgeSlice) -> tuple[str, str, str]:
    return (str(item.owner), item.partition_id, item.selection_key)


def _slice_index(items: Sequence[KnowledgeSlice]) -> dict[tuple[str, str, str], KnowledgeSlice]:
    index: dict[tuple[str, str, str], KnowledgeSlice] = {}
    for item in items:
        key = _slice_key(item)
        if key in index:
            raise GraphQueryError("SEMANTIC_VALIDATION", "query slices must be unique by owner/partition/selection")
        index[key] = item
    return index


def _same_cut(left: object, right: object) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def _statement_identity(reference: StatementRef) -> StatementIdentity:
    """Return the StatementRef identity within its owning aggregate.

    The aggregate hash is deliberately not part of this dictionary key:
    references with the same aggregate owner/object/revision and local
    statement ID/revision but different hashes must collide here, then fail
    the full-reference equality check. Distinct aggregate hashes do not turn
    one aggregate revision into a second statement namespace.
    """
    aggregate = reference.aggregate_ref
    return (
        str(aggregate.owner),
        aggregate.object_id,
        aggregate.revision,
        reference.statement_id,
        reference.revision,
    )


def _statement_slice_key(
    snapshot: GraphSnapshot,
    reference: StatementRef,
) -> tuple[str, str, str] | None:
    aggregate = reference.aggregate_ref
    matches = [
        item
        for item in snapshot.manifest.input_slices
        if str(item.owner) == str(aggregate.owner)
        and item.partition_id == aggregate.object_id
        and item.revision == aggregate.revision
    ]
    if len(matches) != 1:
        return None
    return _slice_key(matches[0])


def _object_slice_key(
    snapshot: GraphSnapshot,
    reference: ObjectRef,
) -> tuple[str, str, str] | None:
    matches = [
        item
        for item in snapshot.manifest.input_slices
        if str(item.owner) == str(reference.owner)
        and item.partition_id == reference.object_id
        and item.revision == reference.revision
    ]
    if len(matches) != 1:
        return None
    return _slice_key(matches[0])


def _edge_slice_keys(
    snapshot: GraphSnapshot,
    edge: GraphEdge,
) -> tuple[set[tuple[str, str, str]], bool]:
    references = [*edge.statement_refs, *edge.provenance.input_statement_refs]
    if not references:
        return set(), False
    keys: set[tuple[str, str, str]] = set()
    seen: dict[StatementIdentity, StatementRef] = {}
    for reference in references:
        identity = _statement_identity(reference)
        prior = seen.get(identity)
        if prior is not None and prior != reference:
            return keys, False
        seen[identity] = reference
        key = _statement_slice_key(snapshot, reference)
        if key is None:
            return keys, False
        keys.add(key)
    return keys, True


def _safe_edges(snapshot: GraphSnapshot) -> tuple[list[GraphEdge], list[GraphEdge]]:
    """Separate edges with uniquely resolvable lineage from unsafe edges.

    Query selection controls graph content through seeds, relations and depth.
    Freshness scope must not decide which graph edges exist. An edge without
    lineage, or with lineage that cannot be mapped uniquely to the manifest,
    is excluded before traversal under every freshness policy.
    """
    candidates: list[GraphEdge] = []
    invalid: dict[str, GraphEdge] = {}
    ref_uses: dict[StatementIdentity, list[tuple[StatementRef, set[str]]]] = defaultdict(list)

    for edge in snapshot.edges:
        if edge.epistemic_status == "disproved":
            continue
        _keys, resolved = _edge_slice_keys(snapshot, edge)
        if not resolved:
            invalid[edge.edge_id] = edge
            continue
        candidates.append(edge)
        for reference in [*edge.statement_refs, *edge.provenance.input_statement_refs]:
            identity = _statement_identity(reference)
            groups = ref_uses[identity]
            for known, edge_ids in groups:
                if known == reference:
                    edge_ids.add(edge.edge_id)
                    break
            else:
                groups.append((reference, {edge.edge_id}))

    # A statement identity must not point at competing source refs from
    # different graph edges. Quarantine every edge carrying that identity.
    for groups in ref_uses.values():
        if len(groups) > 1:
            for _reference, edge_ids in groups:
                invalid.update(
                    (edge.edge_id, edge)
                    for edge in candidates
                    if edge.edge_id in edge_ids
                )

    safe = [edge for edge in candidates if edge.edge_id not in invalid]
    return safe, [invalid[key] for key in sorted(invalid)]


def _freshness(
    snapshot: GraphSnapshot,
    selection: object,
    current_slices: Sequence[KnowledgeSlice] | None,
    selected_nodes: Sequence[GraphNode],
    selected_edges: Sequence[GraphEdge],
    scope_unresolved: bool,
) -> tuple[str, list[KnowledgeSlice]]:
    manifest_cut = snapshot.manifest.as_of
    manifest = _slice_index(snapshot.manifest.input_slices)
    required = _slice_index(selection.required_slices)
    missing: dict[tuple[str, str, str], KnowledgeSlice] = {}
    changed: dict[tuple[str, str, str], KnowledgeSlice] = {}
    unresolved_lineage = scope_unresolved

    # StatementRef.aggregate_ref does not carry KnowledgeSlice.selection_key.
    # Resolve its exact owner/partition/revision against this snapshot's
    # manifest; zero or multiple matches cannot prove scoped freshness.
    dependency_slice_keys: set[tuple[str, str, str]] = set()
    exact_refs: dict[StatementIdentity, StatementRef] = {}
    for item in [*selected_nodes, *selected_edges]:
        references = [*item.statement_refs, *item.provenance.input_statement_refs]
        for ref in references:
            statement_key = _statement_identity(ref)
            prior = exact_refs.get(statement_key)
            if prior is not None and prior != ref:
                unresolved_lineage = True
            exact_refs[statement_key] = ref
            key = _statement_slice_key(snapshot, ref)
            if key is None:
                unresolved_lineage = True
            else:
                dependency_slice_keys.add(key)

        # Business/Events refs can identify materialized graph input slices.
        # Other source refs are upstream provenance pointers: Graph.query's
        # current scoped revisions come from the projection manifest and
        # StatementRefs, not hidden reads of arbitrary source artifacts.
        # Preserve those pointers intact in the returned graph.
        for reference in item.provenance.source_refs:
            if str(reference.owner) not in {"Business", "Events"}:
                continue
            key = _object_slice_key(snapshot, reference)
            if key is None:
                unresolved_lineage = True
            else:
                dependency_slice_keys.add(key)

    if current_slices is None:
        current: dict[tuple[str, str, str], KnowledgeSlice] | None = None
    else:
        current = _slice_index(current_slices)

    # required_slices declares freshness inputs; it never filters graph
    # content. Every selected edge source must be included in that scope.
    if not required:
        unresolved_lineage = True
    for key in dependency_slice_keys:
        if key not in required:
            manifest_item = manifest.get(key)
            if manifest_item is not None:
                missing[key] = manifest_item
            unresolved_lineage = True

    for key, required_item in required.items():
        manifest_item = manifest.get(key)
        if manifest_item is None:
            missing[key] = required_item
            unresolved_lineage = True
            continue
        if required_item != manifest_item:
            changed[key] = required_item
            continue
        if current is None:
            missing[key] = manifest_item
            continue
        current_item = current.get(key)
        if current_item is None:
            missing[key] = manifest_item
        elif current_item != manifest_item:
            changed[key] = current_item

    if selection.freshness_policy == "historical":
        if not _same_cut(selection.as_of, manifest_cut):
            raise GraphQueryError(
                "VERSION_CONFLICT",
                "historical query TimeSlice must exactly match the graph manifest",
            )
        if unresolved_lineage:
            return "unknown", [missing[key] for key in sorted(missing)]
        return "historical", []
    if unresolved_lineage:
        return "unknown", [missing[key] for key in sorted(missing)]
    if not _same_cut(selection.as_of, manifest_cut):
        return "stale", [changed[key] for key in sorted(changed)]
    if changed:
        return "stale", [changed[key] for key in sorted(changed)]
    if missing:
        return "unknown", [missing[key] for key in sorted(missing)]
    return "current", []


def _relation_key(code: CodeRef) -> tuple[str, str, str]:
    return (code.namespace, code.version, code.code)


def _bounded_bfs(snapshot: GraphSnapshot, selection: object) -> tuple[set[str], bool]:
    node_ids = {node.node_id for node in snapshot.nodes}
    if selection.seed_ids:
        unknown = sorted(set(selection.seed_ids) - node_ids)
        if unknown:
            raise GraphQueryError("NOT_FOUND", "one or more graph query seeds are absent from this revision")
        seeds = sorted(set(selection.seed_ids))
        selected = set(seeds[: selection.max_nodes])
        truncated = len(seeds) > selection.max_nodes
    else:
        ordered = sorted(node_ids)
        selected = set(ordered[: selection.max_nodes])
        truncated = len(ordered) > selection.max_nodes
        return selected, truncated

    allowed_relations = {_relation_key(item) for item in selection.relations}
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in snapshot.edges:
        if edge.epistemic_status == "disproved":
            continue
        if allowed_relations and _relation_key(edge.relation) not in allowed_relations:
            continue
        adjacency[edge.source_node_id].append((edge.target_node_id, edge.edge_id))
        adjacency[edge.target_node_id].append((edge.source_node_id, edge.edge_id))
    for edges in adjacency.values():
        edges.sort()

    queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in sorted(selected))
    while queue:
        node_id, depth = queue.popleft()
        if depth >= selection.max_depth:
            if any(neighbor not in selected for neighbor, _ in adjacency[node_id]):
                truncated = True
            continue
        for neighbor, _edge_id in adjacency[node_id]:
            if neighbor in selected:
                continue
            if len(selected) >= selection.max_nodes:
                truncated = True
                continue
            selected.add(neighbor)
            queue.append((neighbor, depth + 1))
    return selected, truncated


def query_graph(
    request: QueryGraphInput,
    *,
    snapshots: Mapping[tuple[str, int], GraphSnapshot],
    current_slices: Sequence[KnowledgeSlice] | None,
    receipts: Mapping[tuple[str, str], CommandReceipt] | None = None,
) -> SubgraphResult | ReceiptResult:
    """Return a strict contract result from materialized snapshot inputs.

    No owner read or storage access occurs here. `current_slices` must be an
    explicit materialized read result; passing None means freshness is unknown.
    Subgraph traversal is weakly connected BFS: an edge can be followed either
    way to discover neighboring nodes, while its declared direction is kept.
    """
    selection = request.query
    if isinstance(selection, ReceiptQuery) or getattr(selection, "kind", None) == "receipt":
        result = None
        if receipts is not None:
            result = receipts.get((selection.operation_id, selection.idempotency_key))
        return ReceiptResult(kind="receipt", receipt=result)

    key = (selection.graph_id, selection.revision)
    snapshot = snapshots.get(key)
    if snapshot is None:
        return SubgraphResult(kind="subgraph", subgraph=None)

    safe_edges, invalid_edges = _safe_edges(snapshot)
    traversal_snapshot = snapshot.model_copy(update={"edges": safe_edges})
    selected_ids, truncated = _bounded_bfs(traversal_snapshot, selection)
    node_by_id = {node.node_id: node for node in snapshot.nodes}
    nodes = [node_by_id[node_id] for node_id in sorted(selected_ids)]
    required_keys = set(_slice_index(selection.required_slices))
    scope_unresolved = not required_keys
    if selection.seed_ids and required_keys:
        for seed_id in selection.seed_ids:
            seed = node_by_id[seed_id]
            refs = [*seed.statement_refs, *seed.provenance.input_statement_refs]
            mapped = [_statement_slice_key(snapshot, ref) for ref in refs]
            if not refs or any(key is None for key in mapped) or not any(
                key in required_keys for key in mapped if key is not None
            ):
                scope_unresolved = True
    relation_filter = {_relation_key(item) for item in selection.relations}
    unresolved_edges = [
        edge
        for edge in invalid_edges
        if edge.epistemic_status != "disproved"
        and (edge.source_node_id in selected_ids or edge.target_node_id in selected_ids)
        and (not relation_filter or _relation_key(edge.relation) in relation_filter)
    ]
    scope_unresolved = scope_unresolved or bool(unresolved_edges)
    edges = [
        edge
        for edge in traversal_snapshot.edges
        if edge.epistemic_status != "disproved"
        and edge.source_node_id in selected_ids
        and edge.target_node_id in selected_ids
        and (not relation_filter or _relation_key(edge.relation) in relation_filter)
    ]
    edges.sort(key=lambda edge: edge.edge_id)

    freshness, missing_slices = _freshness(
        snapshot,
        selection,
        current_slices,
        nodes,
        edges,
        scope_unresolved,
    )
    if selection.freshness_policy == "current_required" and freshness != "current":
        raise GraphQueryError("VERSION_CONFLICT", f"current graph freshness is {freshness}")

    missing_data = list(snapshot.missing_data)
    for edge in unresolved_edges:
        datum = MissingDatum(
            path=f"/edges/{edge.edge_id}/statement_refs",
            reason="not_observed",
            detail=(
                "Edge excluded because its StatementRef lineage is missing, conflicting, "
                "or cannot be mapped uniquely to the graph manifest."
            ),
        )
        if datum not in missing_data:
            missing_data.append(datum)

    projected = GraphSnapshot(
        graph_id=snapshot.graph_id,
        revision=snapshot.revision,
        nodes=nodes,
        edges=edges,
        manifest=snapshot.manifest,
        completeness=snapshot.completeness,
        missing_data=missing_data,
    )
    scope = sorted({slice_.partition_id for slice_ in selection.required_slices})
    subgraph = GraphSubgraph(
        snapshot=projected,
        freshness=freshness,
        missing_slices=missing_slices,
        traversal_truncated=truncated,
        query_scope=scope,
    )
    logger.debug(
        "T12 query completed: graph_id=%s revision=%d nodes=%d edges=%d freshness=%s truncated=%s",
        snapshot.graph_id,
        snapshot.revision,
        len(nodes),
        len(edges),
        freshness,
        truncated,
    )
    return SubgraphResult(kind="subgraph", subgraph=subgraph)
