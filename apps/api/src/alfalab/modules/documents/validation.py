"""Cross-field validation for persisted RawMaterial/PreparedMaterial pairs."""

from __future__ import annotations

from alfalab_contracts import PreparedMaterial, RawMaterial
from alfalab_contracts.semantics import validate_dto


class DocumentContentInvalid(ValueError):
    """A document body or span map is not a lossless prepare result."""


def validate_registered_content(
    raw: RawMaterial, prepared: PreparedMaterial | None
) -> None:
    """Verify exact hashes, preserved metadata, and each mapped code point."""
    try:
        validate_dto(raw)
        if prepared is None:
            return
        validate_dto(prepared)
    except ValueError as exc:
        raise DocumentContentInvalid(
            "document content failed contract validation"
        ) from exc

    if prepared.raw_hash != raw.content_hash:
        raise DocumentContentInvalid("prepared raw hash does not match raw content")
    raw_identity = raw.model_dump(mode="json", exclude={"text", "content_hash"})
    prepared_identity = prepared.material.model_dump(
        mode="json", exclude={"text", "content_hash"}
    )
    if raw_identity != prepared_identity:
        raise DocumentContentInvalid(
            "prepare changed raw material provenance or metadata"
        )

    raw_text = raw.text
    prepared_text = prepared.material.text
    if not prepared_text:
        if (
            prepared.quality != "rejected"
            or prepared.span_map
            or prepared.warnings != ["empty_text"]
        ):
            raise DocumentContentInvalid(
                "empty prepared content has invalid quality metadata"
            )
        return
    if prepared.quality != "valid" or prepared.warnings:
        raise DocumentContentInvalid(
            "non-empty prepared content has invalid quality metadata"
        )

    actual_mapping: list[tuple[str, int, int]] = []
    for span in prepared.span_map:
        output = prepared_text[span.prepared_start : span.prepared_end]
        source = raw_text[span.raw_start : span.raw_end]
        if len(output) == len(source):
            for offset, (out_char, source_char) in enumerate(
                zip(output, source, strict=True)
            ):
                if out_char != source_char and not (
                    out_char == "\n" and source_char == "\r"
                ):
                    raise DocumentContentInvalid(
                        "span map does not preserve source code points"
                    )
                actual_mapping.append(
                    (out_char, span.raw_start + offset, span.raw_start + offset + 1)
                )
        elif len(output) == 1 and output == "\n" and source == "\r\n":
            actual_mapping.append(("\n", span.raw_start, span.raw_end))
        else:
            raise DocumentContentInvalid(
                "span map contains an unsupported normalization"
            )

    def expected_mapping(normalize_newlines: bool, trim_outer: bool):
        points: list[tuple[str, int, int]] = []
        index = 0
        while index < len(raw_text):
            character = raw_text[index]
            if normalize_newlines and character == "\r":
                if index + 1 < len(raw_text) and raw_text[index + 1] == "\n":
                    points.append(("\n", index, index + 2))
                    index += 2
                else:
                    points.append(("\n", index, index + 1))
                    index += 1
            else:
                points.append((character, index, index + 1))
                index += 1
        if trim_outer:
            start = 0
            end = len(points)
            while start < end and points[start][0].isspace():
                start += 1
            while end > start and points[end - 1][0].isspace():
                end -= 1
            points = points[start:end]
        return points

    candidates = [
        expected_mapping(normalize_newlines, trim_outer)
        for normalize_newlines in (False, True)
        for trim_outer in (False, True)
    ]
    if not any(
        prepared_text == "".join(character for character, _, _ in candidate)
        and actual_mapping == candidate
        for candidate in candidates
    ):
        raise DocumentContentInvalid(
            "prepared content is not a permitted normalization of the raw text"
        )
