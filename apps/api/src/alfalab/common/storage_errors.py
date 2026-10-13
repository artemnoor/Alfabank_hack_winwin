"""Shared, payload-free storage utility errors."""


class ArtifactIntegrityError(RuntimeError):
    """An immutable artifact does not match its content-addressed reference."""
