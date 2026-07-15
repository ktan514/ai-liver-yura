from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.activities.activity_result import ActivityResult
from app.domain.activities.activity_status import ActivityStatus
from app.domain.activity_turn_result import (
    ActivityOutputResult,
    ActivityOutputStatus,
    ActivityTurnResult,
    CharacterGenerationResult,
)
from app.domain.character_response import ActivityExecutionResult


@dataclass(frozen=True, slots=True)
class ActivityTurn:
    """継続Activity内で一つの入力を処理する実行単位。"""

    sequence: int
    input_text: str
    source_event_id: str | None = None
    status: ActivityStatus = ActivityStatus.ACTIVE
    result: ActivityResult | None = None
    operation: str | None = None
    constraints_snapshot: dict[str, object] = field(default_factory=dict)
    execution_result: ActivityExecutionResult | None = None
    turn_result: ActivityTurnResult | None = None
    turn_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def completed(self, result: ActivityResult) -> ActivityTurn:
        completed_at = datetime.now(timezone.utc)
        return replace(
            self,
            status=ActivityStatus.COMPLETED,
            result=result,
            updated_at=completed_at,
            completed_at=completed_at,
        )

    def with_execution_result(
        self,
        result: ActivityExecutionResult,
    ) -> ActivityTurn:
        updated_at = datetime.now(timezone.utc)
        aggregate = self.turn_result or ActivityTurnResult(
            activity_turn_id=self.turn_id,
            activity_type=result.activity_type,
            source_event_id=self.source_event_id,
            ongoing_activity_id=result.ongoing_activity_id,
            operation=self.operation,
        )
        return replace(
            self,
            execution_result=result,
            turn_result=aggregate.with_execution(result),
            updated_at=updated_at,
        )

    def with_character_result(self, result: CharacterGenerationResult) -> ActivityTurn:
        aggregate = self._aggregate().with_character(result)
        return replace(self, turn_result=aggregate, updated_at=datetime.now(timezone.utc))

    def with_output_result(self, result: ActivityOutputResult) -> ActivityTurn:
        aggregate = self._aggregate().with_output(result)
        terminal = result.status not in {
            ActivityOutputStatus.NOT_STARTED,
            ActivityOutputStatus.PLANNED,
        }
        completed_at = datetime.now(timezone.utc) if terminal else None
        return replace(
            self,
            status=ActivityStatus.COMPLETED if terminal else self.status,
            turn_result=aggregate,
            updated_at=completed_at or datetime.now(timezone.utc),
            completed_at=completed_at,
        )

    def _aggregate(self) -> ActivityTurnResult:
        if self.turn_result is not None:
            return self.turn_result
        return ActivityTurnResult(
            activity_turn_id=self.turn_id,
            activity_type=self.execution_result.activity_type
            if self.execution_result is not None
            else "unknown",
            source_event_id=self.source_event_id,
            ongoing_activity_id=self.execution_result.ongoing_activity_id
            if self.execution_result is not None
            else None,
            operation=self.operation,
            execution_result=self.execution_result,
        )
