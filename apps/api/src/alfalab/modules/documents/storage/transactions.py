"""Atomic owner-local command transactions and typed idempotency receipts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Generic, Mapping, TypeVar

from alfalab_contracts import CommandReceipt, ObjectRef
from pydantic import BaseModel
from sqlalchemy import Connection, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from .canonical import canonical_hash
from .context import OwnerCommandContext, validate_scope
from .errors import DocumentsStorageError, IdempotencyConflict

V = TypeVar("V")
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class OwnerTables:
    """Tables that implement the common command protocol for one owner."""

    claims: Table
    receipts: Table
    audits: Table


@dataclass(frozen=True, slots=True)
class OwnerCommandEffect(Generic[V]):
    """Owner-specific mutation result produced inside the transaction."""

    value: V
    applied: bool
    changed_refs: tuple[ObjectRef, ...]
    before_refs: tuple[ObjectRef, ...]
    after_refs: tuple[ObjectRef, ...]


@dataclass(frozen=True, slots=True)
class OwnerCommandResult(Generic[T]):
    """Typed response payload plus whether this invoke applied the command."""

    response: T
    receipt: CommandReceipt
    replayed_receipt: bool


class OwnerCommandRunner:
    """Run an owner mutation with a unique claim, audit, and durable receipt.

    The in-flight claim and all domain writes are in one PostgreSQL transaction.
    A claim is deleted before commit and the completed receipt is non-nullable;
    crashes before commit therefore leave neither a partial mutation nor a
    successful-looking receipt. A second caller with the same key waits on the
    unique constraint and then reads the first committed response.
    """

    def __init__(self, engine: Engine, tables: OwnerTables) -> None:
        self._engine = engine
        self._tables = tables

    def execute(
        self,
        *,
        context: OwnerCommandContext,
        operation_id: str,
        contract_major: int,
        idempotency_key: str,
        command_payload: Mapping[str, Any],
        response_model: type[T],
        response_schema_id: str,
        response_schema_version: str,
        mutate: Callable[[Connection], OwnerCommandEffect[V]],
        build_response: Callable[[V, CommandReceipt], T],
    ) -> OwnerCommandResult[T]:
        """Execute or replay a command while storing its typed output payload."""

        validate_scope(context.scope)
        command_hash = _command_hash(context, operation_id, contract_major, command_payload)
        key = {
            "tenant_id": context.scope.tenant_id,
            "sandbox_id": context.scope.sandbox_id,
            "operation_id": operation_id,
            "contract_major": contract_major,
            "idempotency_key": idempotency_key,
        }
        claim = dict(key)

        with self._engine.begin() as connection:
            inserted = connection.execute(
                pg_insert(self._tables.claims)
                .values(**claim)
                .on_conflict_do_nothing(
                    index_elements=[
                        self._tables.claims.c.tenant_id,
                        self._tables.claims.c.sandbox_id,
                        self._tables.claims.c.operation_id,
                        self._tables.claims.c.contract_major,
                        self._tables.claims.c.idempotency_key,
                    ]
                )
                .returning(self._tables.claims.c.idempotency_key)
            )
            claimed_key = inserted.scalar_one_or_none()
            existing = connection.execute(
                select(self._tables.receipts).where(*_key_predicates(self._tables.receipts, key))
            ).mappings().one_or_none()

            if existing is not None:
                if existing["command_hash"] != command_hash:
                    raise IdempotencyConflict("idempotency key is already bound to another command")
                if (
                    existing["response_schema_id"] != response_schema_id
                    or existing["response_schema_version"] != response_schema_version
                ):
                    raise DocumentsStorageError("stored receipt response schema is unsupported")
                response_json = existing["response_payload_json"]
                validated = response_model.model_validate(response_json)
                if canonical_hash(validated.model_dump(mode="json")) != existing["response_hash"]:
                    raise DocumentsStorageError("stored receipt response failed integrity verification")
                receipt = CommandReceipt.model_validate(existing["receipt_json"])
                if (
                    receipt.operation_id != operation_id
                    or receipt.idempotency_key != idempotency_key
                    or receipt.command_hash != command_hash
                    or receipt.audit_id != existing["audit_id"]
                    or receipt.original_run_id != existing["original_run_id"]
                    or getattr(validated, "receipt", receipt) != receipt
                ):
                    raise DocumentsStorageError("stored receipt metadata failed integrity verification")
                connection.execute(delete(self._tables.claims).where(*_key_predicates(self._tables.claims, key)))
                return OwnerCommandResult(validated, receipt, replayed_receipt=True)

            if claimed_key is None:
                raise DocumentsStorageError("owner receipt claim exists without a committed receipt")

            effect = mutate(connection)
            committed_at = connection.execute(select(func.clock_timestamp())).scalar_one()
            if not isinstance(committed_at, datetime):
                raise DocumentsStorageError("database returned an invalid transaction timestamp")
            audit_id = str(uuid.uuid4())
            receipt = CommandReceipt(
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                command_hash=command_hash,
                applied=effect.applied,
                changed_refs=list(effect.changed_refs),
                audit_id=audit_id,
                committed_at=_utc_timestamp(committed_at),
                original_run_id=context.run_id,
            )
            response = build_response(effect.value, receipt)
            response_json = response.model_dump(mode="json")
            response_hash = canonical_hash(response_json)
            committed_values = {
                **key,
                "command_hash": command_hash,
                "original_run_id": context.run_id,
                "audit_id": audit_id,
                "committed_at": committed_at,
                "receipt_json": receipt.model_dump(mode="json"),
                "response_schema_id": response_schema_id,
                "response_schema_version": response_schema_version,
                "response_hash": response_hash,
                "response_payload_json": response_json,
            }
            connection.execute(insert(self._tables.audits).values(
                tenant_id=context.scope.tenant_id,
                sandbox_id=context.scope.sandbox_id,
                audit_id=audit_id,
                actor_id=context.actor_id,
                operation_id=operation_id,
                command_hash=command_hash,
                before_refs=[ref.model_dump(mode="json") for ref in effect.before_refs],
                after_refs=[ref.model_dump(mode="json") for ref in effect.after_refs],
                committed_at=committed_at,
            ))
            connection.execute(insert(self._tables.receipts).values(**committed_values))
            connection.execute(delete(self._tables.claims).where(*_key_predicates(self._tables.claims, key)))

        return OwnerCommandResult(response, receipt, replayed_receipt=False)


def _key_predicates(table: Table, key: Mapping[str, Any]) -> list[Any]:
    return [getattr(table.c, name) == value for name, value in key.items()]


def _command_hash(
    context: OwnerCommandContext,
    operation_id: str,
    contract_major: int,
    command_payload: Mapping[str, Any],
) -> str:
    semantic_command = {
        "operation_id": operation_id,
        "contract_major": contract_major,
        "tenant_id": context.scope.tenant_id,
        "sandbox_id": context.scope.sandbox_id,
        "actor_id": context.actor_id,
        "permissions": sorted(context.permissions),
        "implementation": context.implementation_fingerprint,
        "payload": command_payload,
    }
    return canonical_hash(semantic_command)


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise DocumentsStorageError("database timestamp has no timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
