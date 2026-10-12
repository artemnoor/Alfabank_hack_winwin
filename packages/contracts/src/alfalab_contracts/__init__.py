"""Executable contracts for the AlfaBank hackathon framework."""

from . import models as _models

SCHEMA_NAMES = _models.SCHEMA_NAMES
SCHEMA_TYPES = _models.SCHEMA_TYPES

__all__ = [*SCHEMA_NAMES, "SCHEMA_NAMES", "SCHEMA_TYPES"]


def __getattr__(name: str):
    try:
        return SCHEMA_TYPES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
