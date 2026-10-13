"""Typed Documents.register operation adapter."""

from __future__ import annotations

from alfalab_contracts import RegisterDocumentInput, RegisterDocumentOutput

from alfalab.execution.errors import SafeExecutionError, invalid_input

from ..storage.context import OperationContext
from ..storage.errors import (
    DocumentsPolicyDenied,
    DocumentsStorageError,
    ExpectedRevisionConflict,
    IdempotencyConflict,
    ScopeDenied,
)
from ..storage.replay import RegisterBeforeState, RegisterBeforeStateRequest
from ..storage.service import DocumentsStorage


class RegisterOperation:
    """Adapt the public operation protocol to Documents-owned storage."""

    def __init__(self, storage: DocumentsStorage) -> None:
        self._storage = storage

    def execute(
        self,
        payload: RegisterDocumentInput,
        context: OperationContext,
        /,
    ) -> RegisterDocumentOutput:
        if context.idempotency_key is None:
            raise invalid_input("idempotency_key")
        before_request = RegisterBeforeStateRequest(
            document_id=payload.document_id,
            expected_revision=payload.expected_revision,
            idempotency_key=context.idempotency_key,
        )
        snapshot = context.dependency_gateway.invoke(
            "documents.register.before_state", before_request
        )
        if type(snapshot) is not RegisterBeforeState:
            raise SafeExecutionError(
                status_code=502,
                code="DEPENDENCY_FAILED",
                category="dependency",
                safe_message="Documents before-state capture returned an invalid response.",
            )
        if getattr(context, "execution_mode", "live") == "replay":
            try:
                self._storage.restore_register_before_state(
                    snapshot, before_request, context
                )
            except DocumentsPolicyDenied as exc:
                raise SafeExecutionError(
                    status_code=409,
                    code="REPLAY_INCOMPATIBLE",
                    category="replay",
                    safe_message="The recorded command state cannot be restored safely.",
                ) from exc
            except DocumentsStorageError as exc:
                raise SafeExecutionError(
                    status_code=409,
                    code="REPLAY_MISS",
                    category="replay",
                    safe_message="The recorded command state failed integrity validation.",
                ) from exc
        try:
            return self._storage.register(payload, context)
        except DocumentsPolicyDenied as exc:
            raise SafeExecutionError(
                status_code=403,
                code="DATA_POLICY_DENIED",
                category="policy",
                safe_message="The active data policy does not allow saving this content.",
            ) from exc
        except ScopeDenied as exc:
            raise SafeExecutionError(
                status_code=403,
                code="ACCESS_DENIED",
                category="access",
                safe_message="The authenticated principal cannot access this document scope.",
            ) from exc
        except ExpectedRevisionConflict as exc:
            raise SafeExecutionError(
                status_code=409,
                code="VERSION_CONFLICT",
                category="conflict",
                safe_message="The document revision changed before registration.",
                outcome="not_applied",
            ) from exc
        except IdempotencyConflict as exc:
            raise SafeExecutionError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                category="conflict",
                safe_message="The idempotency key is already bound to another command.",
                outcome="not_applied",
            ) from exc
        except ValueError as exc:
            raise invalid_input("payload.prepared") from exc
        except OSError as exc:
            raise SafeExecutionError(
                status_code=503,
                code="STORAGE_UNAVAILABLE",
                category="unavailable",
                safe_message="Documents storage is temporarily unavailable.",
                retryable=True,
                outcome="unknown",
            ) from exc
        except DocumentsStorageError as exc:
            raise SafeExecutionError(
                status_code=500,
                code="OWNER_STORAGE_FAILED",
                category="internal",
                safe_message="Documents storage rejected the operation safely.",
                outcome="unknown",
            ) from exc
