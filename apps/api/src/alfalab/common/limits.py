"""Shared execution response limits."""

MAX_ARTIFACT_RESPONSE_BYTES = 2 * 1024 * 1024
ARTIFACT_RESPONSE_ENVELOPE_RESERVE_BYTES = 64 * 1024
# Legacy Documents rows predate persisted artifact sizes. Keep their reads bounded
# until those rows are rewritten through Documents.register.
MAX_LEGACY_DOCUMENT_ARTIFACT_READ_BYTES = 32 * 1024 * 1024
