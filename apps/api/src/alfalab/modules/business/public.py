"""Public operation interfaces owned by Business."""

from __future__ import annotations

from typing import Protocol

from alfalab_contracts import (
    ApplyBusinessInput,
    ApplyBusinessOutput,
    ProfileInput,
    ProfileOutput,
    QuestionsInput,
    QuestionsOutput,
    ReadBusinessInput,
    ReadBusinessOutput,
)

from alfalab.common.protocols import OperationContext, OperationImplementation


class ProposeProfileOperation(OperationImplementation[ProfileInput, ProfileOutput], Protocol):
    def execute(self, payload: ProfileInput, context: OperationContext, /) -> ProfileOutput: ...


class ProposeQuestionsOperation(OperationImplementation[QuestionsInput, QuestionsOutput], Protocol):
    def execute(self, payload: QuestionsInput, context: OperationContext, /) -> QuestionsOutput: ...


class ApplyOperation(OperationImplementation[ApplyBusinessInput, ApplyBusinessOutput], Protocol):
    def execute(self, payload: ApplyBusinessInput, context: OperationContext, /) -> ApplyBusinessOutput: ...


class ReadOperation(OperationImplementation[ReadBusinessInput, ReadBusinessOutput], Protocol):
    def execute(self, payload: ReadBusinessInput, context: OperationContext, /) -> ReadBusinessOutput: ...


OPERATION_BINDINGS = {
    "Business.propose_profile": ProposeProfileOperation,
    "Business.propose_questions": ProposeQuestionsOperation,
    "Business.apply": ApplyOperation,
    "Business.read": ReadOperation,
}

__all__ = [
    "ProposeProfileOperation",
    "ProposeQuestionsOperation",
    "ApplyOperation",
    "ReadOperation",
    "OPERATION_BINDINGS",
]
