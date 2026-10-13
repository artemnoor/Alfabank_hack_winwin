"""Deterministic Documents.prepare real and baseline implementations."""

from __future__ import annotations

import hashlib

from alfalab_contracts import PrepareInput, PrepareOutput, PreparedMaterial, RawMaterial, SpanMap

from alfalab.common.protocols import OperationContext


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_points(text: str, normalize_newlines: bool) -> list[tuple[str, int, int]]:
    points: list[tuple[str, int, int]] = []
    index = 0
    while index < len(text):
        character = text[index]
        if normalize_newlines and character == "\r":
            if index + 1 < len(text) and text[index + 1] == "\n":
                points.append(("\n", index, index + 2))
                index += 2
            else:
                points.append(("\n", index, index + 1))
                index += 1
        else:
            points.append((character, index, index + 1))
            index += 1
    return points


def _span_map(points: list[tuple[str, int, int]]) -> list[SpanMap]:
    """Coalesce only exact 1:1 runs; newline substitutions keep exact bounds."""
    spans: list[SpanMap] = []
    group_start = 0
    group_raw_start = 0
    group_raw_end = 0

    for output_index, (_, raw_start, raw_end) in enumerate(points):
        exact_one_to_one = raw_end - raw_start == 1
        can_extend = (
            output_index > group_start
            and exact_one_to_one
            and group_raw_end - group_raw_start == output_index - group_start
            and group_raw_end == raw_start
        )
        if output_index == group_start:
            group_raw_start, group_raw_end = raw_start, raw_end
            if exact_one_to_one:
                continue
        elif can_extend:
            group_raw_end = raw_end
            continue
        else:
            spans.append(
                SpanMap(
                    prepared_start=group_start,
                    prepared_end=output_index,
                    raw_start=group_raw_start,
                    raw_end=group_raw_end,
                )
            )
            group_start = output_index
            group_raw_start, group_raw_end = raw_start, raw_end

    if points:
        spans.append(
            SpanMap(
                prepared_start=group_start,
                prepared_end=len(points),
                raw_start=group_raw_start,
                raw_end=group_raw_end,
            )
        )
    return spans


def prepare(payload: PrepareInput) -> PrepareOutput:
    """Apply only the explicitly selected newline and outer-whitespace rules."""
    points = _normalized_points(payload.material.text, payload.normalize_newlines)
    if payload.trim_outer_whitespace:
        first = 0
        last = len(points)
        while first < last and points[first][0].isspace():
            first += 1
        while last > first and points[last - 1][0].isspace():
            last -= 1
        points = points[first:last]

    prepared_text = "".join(character for character, _, _ in points)
    prepared_material = payload.material.model_copy(
        update={
            "text": prepared_text,
            "content_hash": _sha256_text(prepared_text),
        }
    )
    prepared = PreparedMaterial(
        material=prepared_material,
        raw_hash=payload.material.content_hash,
        prepared_hash=_sha256_text(prepared_text),
        quality="valid" if prepared_text else "rejected",
        span_map=_span_map(points),
        warnings=[] if prepared_text else ["empty_text"],
    )
    return PrepareOutput(prepared=prepared)


class RealPrepare:
    """Reference deterministic implementation described by framework v1."""

    def execute(self, payload: PrepareInput, context: OperationContext, /) -> PrepareOutput:
        output = prepare(payload)
        context.trace_recorder.record_safe_event(
            "documents.prepare.completed",
            {
                "input_codepoints": len(payload.material.text),
                "output_codepoints": len(output.prepared.material.text),
                "quality": output.prepared.quality,
                "normalize_newlines": payload.normalize_newlines,
                "trim_outer_whitespace": payload.trim_outer_whitespace,
            },
        )
        return output


class BaselineMockPrepare:
    """Baseline mock that preserves the prepare operation's semantic rules."""

    def execute(self, payload: PrepareInput, context: OperationContext, /) -> PrepareOutput:
        del context
        return prepare(payload)
