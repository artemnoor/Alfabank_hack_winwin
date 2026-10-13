"""Deterministic, network-free implementation of Sources.fetch."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC

from alfalab_contracts import FetchInput, FetchOutput, Provenance, RawMaterial

from alfalab.common.protocols import OperationContext
from alfalab.execution.errors import SafeExecutionError, invalid_input
from alfalab.execution.temporal import parse_utc_timestamp

from ..fixture_catalog import FixtureSourceCatalog


def _cursor_query_hash(payload: FetchInput) -> str:
    body = json.dumps(
        {"source_id": payload.source_id, "since": payload.since},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _cursor(payload: FetchInput) -> int:
    if payload.cursor is None:
        return 0
    parts = payload.cursor.split(":")
    if len(parts) != 3 or parts[0] != "v1" or parts[1] != _cursor_query_hash(payload):
        raise invalid_input("payload.cursor")
    try:
        offset = int(parts[2])
    except ValueError as exc:
        raise invalid_input("payload.cursor") from exc
    if offset < 0:
        raise invalid_input("payload.cursor")
    return offset


def _next_cursor(payload: FetchInput, offset: int) -> str:
    return f"v1:{_cursor_query_hash(payload)}:{offset}"


def _timestamp(context: OperationContext) -> str:
    value = context.analytical_clock.now().astimezone(UTC)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


class FixtureSourceFetch:
    """Use an approved local dataset; the input never controls a URL or path."""

    def __init__(self, catalog: FixtureSourceCatalog) -> None:
        self._catalog = catalog

    def fetch(self, payload: FetchInput, context: OperationContext, /) -> FetchOutput:
        source = self._catalog.resolve(payload.source_id)
        if source is None:
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The requested source is not registered by this server.",
            )

        warning_values: list[str] = []
        materials = []
        since = (
            parse_utc_timestamp(payload.since) if payload.since is not None else None
        )
        for fixture in source.materials:
            if since is not None:
                if fixture.published_at is None:
                    warning_values.append("source_item_without_published_at_excluded")
                    continue
                if parse_utc_timestamp(fixture.published_at) < since:
                    continue
            materials.append(fixture)

        offset = _cursor(payload)
        if offset > len(materials):
            raise invalid_input("payload.cursor")
        page = materials[offset : offset + payload.limit]
        collected_at = _timestamp(context)
        output_materials = [
            RawMaterial(
                material_id=item.material_id,
                source_id=item.source_id,
                source_url=item.source_url,
                title=item.title,
                text=item.text,
                published_at=item.published_at,
                collected_at=collected_at,
                content_hash=item.content_hash,
                language=item.language,
                provenance=Provenance(
                    origin="synthetic",
                    source_refs=[],
                    input_statement_refs=[],
                    producer_run_id=context.run_id,
                    derivation_method=None,
                    evidence_refs=[],
                    origin_verified=True,
                ),
            )
            for item in page
        ]
        next_offset = offset + len(page)
        next_cursor = (
            _next_cursor(payload, next_offset) if next_offset < len(materials) else None
        )
        if warning_values:
            warning_values = list(dict.fromkeys(warning_values))
        return FetchOutput(
            materials=output_materials,
            next_cursor=next_cursor,
            warnings=warning_values,
        )


class FetchOperation:
    """Call the allowlisted source adapter through the shared Dependency Gateway."""

    def execute(self, payload: FetchInput, context: OperationContext, /) -> FetchOutput:
        response = context.dependency_gateway.invoke("sources.fixture", payload)
        if type(response) is not FetchOutput:
            raise SafeExecutionError(
                status_code=502,
                code="DEPENDENCY_FAILED",
                category="dependency",
                safe_message="The registered source returned an invalid response.",
                retryable=False,
                outcome="not_applied",
            )
        return FetchOutput(
            materials=[
                material.model_copy(
                    update={
                        "provenance": material.provenance.model_copy(
                            update={"producer_run_id": context.run_id}
                        )
                    }
                )
                for material in response.materials
            ],
            next_cursor=response.next_cursor,
            warnings=response.warnings,
        )
