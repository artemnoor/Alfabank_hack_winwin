"""Safe, payload-free storage boundary errors."""


class DocumentsStorageError(RuntimeError):
    """Base class for expected owner storage failures."""


class ScopeDenied(DocumentsStorageError):
    """The trusted principal cannot use the requested scope."""


class IdempotencyConflict(DocumentsStorageError):
    """An idempotency key was already used for different command semantics."""


class ExpectedRevisionConflict(DocumentsStorageError):
    """The current aggregate revision differs from the requested revision."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected revision {expected}; current revision is {actual}")


class ArtifactIntegrityError(DocumentsStorageError):
    """An immutable artifact does not match its content-addressed reference."""
