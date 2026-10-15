"""Cross-platform hashes for source-controlled UTF-8 text artifacts.

Git normalizes text files to LF in this repository. These helpers apply the
same normalization before hashing so Windows CRLF checkouts and LF checkouts
produce identical pins. Use ordinary hashlib for binary data and wire payloads.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def canonical_text_bytes(raw: bytes) -> bytes:
    """Normalize UTF-8 text line endings to LF without changing other bytes."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def sha256_text_bytes(raw: bytes) -> str:
    """Hash UTF-8 text independently of the checkout's line-ending style."""
    return hashlib.sha256(canonical_text_bytes(raw)).hexdigest()


def sha256_text_file(path: Path) -> str:
    """Hash a UTF-8 text file using the repository's LF canonical form."""
    return sha256_text_bytes(path.read_bytes())
