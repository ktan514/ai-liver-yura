from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus


class CharacterGenerationStatus(str, Enum):
    NOT_STARTED = "not_started"
    FAILED = "failed"
    VALIDATED = "validated"
    FALLBACK_USED = "fallback_used"


class ActivityOutputStatus(str, Enum):
    NOT_STARTED = "not_started"
    PLANNED = "planned"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ActionExecutionStatus(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class CharacterGenerationResult:
    status: CharacterGenerationStatus
    activity_turn_id: str
    ongoing_activity_id: str | None = None
    source_event_id: str | None = None
    adopted_text: str | None = None
    validation_reason: str | None = None
    error: str | None = None
    attempts: int = 0
    result_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    action_id: str
    action_type: str
    status: ActionExecutionStatus
    output_unit_id: str
    activity_turn_id: str
    error: str | None = None
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActivityOutputResult:
    status: ActivityOutputStatus
    output_unit_id: str
    activity_turn_id: str
    ongoing_activity_id: str | None = None
    source_event_id: str | None = None
    action_results: tuple[ActionExecutionResult, ...] = ()
    failure_stage: str | None = None
    error: str | None = None
    activity_result_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActivityTurnResult:
    activity_turn_id: str
    activity_type: str
    source_event_id: str | None = None
    ongoing_activity_id: str | None = None
    operation: str | None = None
    confirmation_id: str | None = None
    confirmation_source_event_id: str | None = None
    resolution_event_id: str | None = None
    candidate_activity_type: str | None = None
    candidate_operation: str | None = None
    confirmation_resolution: str | None = None
    final_behavior_plan_id: str | None = None
    execution_result: ActivityExecutionResult | None = None
    character_result: CharacterGenerationResult | None = None
    output_result: ActivityOutputResult | None = None
    created_at: datetime = field(default_factory=_now)
    completed_at: datetime | None = None

    @property
    def final_status(self) -> str:
        execution = self.execution_result
        character = self.character_result
        output = self.output_result
        if output is not None and output.status == ActivityOutputStatus.CANCELED:
            return "canceled"
        if execution is not None and execution.status == ActivityExecutionStatus.REJECTED:
            return "execution_rejected"
        if execution is not None and execution.status == ActivityExecutionStatus.FAILED:
            return "execution_failed"
        if output is not None and output.status in {
            ActivityOutputStatus.FAILED,
            ActivityOutputStatus.PARTIALLY_COMPLETED,
        }:
            return f"execution_{self._execution_label()}_output_{output.status.value}"
        if character is not None and character.status == CharacterGenerationStatus.FALLBACK_USED:
            if output is not None and output.status == ActivityOutputStatus.COMPLETED:
                return "execution_succeeded_character_fallback"
            return "character_fallback"
        if output is not None and output.status == ActivityOutputStatus.COMPLETED:
            return "completed"
        return "in_progress"

    @property
    def failure_stage(self) -> str | None:
        if self.output_result is not None and self.output_result.failure_stage is not None:
            return self.output_result.failure_stage
        if (
            self.character_result is not None
            and self.character_result.status == CharacterGenerationStatus.FAILED
        ):
            return "character_generation"
        if self.execution_result is not None and self.execution_result.status in {
            ActivityExecutionStatus.FAILED,
            ActivityExecutionStatus.REJECTED,
        }:
            return "activity_execution"
        return None

    def with_execution(self, result: ActivityExecutionResult) -> ActivityTurnResult:
        return replace(self, execution_result=result)

    def with_character(self, result: CharacterGenerationResult) -> ActivityTurnResult:
        return replace(self, character_result=result)

    def with_output(self, result: ActivityOutputResult) -> ActivityTurnResult:
        completed_at = (
            result.finished_at
            if result.status
            not in {
                ActivityOutputStatus.NOT_STARTED,
                ActivityOutputStatus.PLANNED,
            }
            else None
        )
        return replace(self, output_result=result, completed_at=completed_at)

    def _execution_label(self) -> str:
        if self.execution_result is None:
            return "not_started"
        return self.execution_result.status.value
