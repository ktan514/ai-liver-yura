from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.activities.activity_result import ActivityResult
from app.domain.activities.activity_status import ActivityStatus
from app.domain.activities.activity_turn import ActivityTurn
from app.domain.activity_turn_result import ActivityOutputResult, CharacterGenerationResult
from app.domain.character_response import ActivityExecutionResult


@dataclass(frozen=True, slots=True)
class OngoingActivity:
    """複数のユーザー入力にまたがって保持する活動状態。"""

    activity_type: str
    goal: str
    expected_input: str
    end_condition: str
    status: ActivityStatus = ActivityStatus.ACTIVE
    last_result: ActivityResult | None = None
    last_execution_result: ActivityExecutionResult | None = None
    turns: tuple[ActivityTurn, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    ongoing_activity_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def updated(
        self,
        *,
        result: ActivityResult | None = None,
        expected_input: str | None = None,
        context_updates: dict[str, Any] | None = None,
    ) -> OngoingActivity:
        context = {**self.context, **(context_updates or {})}
        turns = self.turns
        if result is not None and turns and turns[-1].status == ActivityStatus.ACTIVE:
            turns = (*turns[:-1], turns[-1].completed(result))
        return replace(
            self,
            last_result=result if result is not None else self.last_result,
            expected_input=(expected_input if expected_input is not None else self.expected_input),
            context=context,
            turns=turns,
            updated_at=datetime.now(timezone.utc),
        )

    def begin_turn(
        self,
        input_text: str,
        source_event_id: str | None,
        *,
        operation: str | None = None,
        constraints_snapshot: dict[str, object] | None = None,
    ) -> OngoingActivity:
        turn = ActivityTurn(
            sequence=len(self.turns) + 1,
            input_text=input_text,
            source_event_id=source_event_id,
            operation=operation,
            constraints_snapshot=dict(constraints_snapshot or {}),
        )
        return replace(
            self,
            status=ActivityStatus.ACTIVE,
            turns=(*self.turns, turn),
            updated_at=datetime.now(timezone.utc),
        )

    def record_execution(
        self,
        result: ActivityExecutionResult,
        *,
        expected_input: str | None = None,
        context_updates: dict[str, Any] | None = None,
        waiting_input: bool = True,
    ) -> OngoingActivity:
        turns = self.turns
        if turns and turns[-1].status == ActivityStatus.ACTIVE:
            turns = (*turns[:-1], turns[-1].with_execution_result(result))
        return replace(
            self,
            status=ActivityStatus.WAITING if waiting_input else ActivityStatus.ACTIVE,
            last_execution_result=result,
            expected_input=expected_input if expected_input is not None else self.expected_input,
            context={**self.context, **(context_updates or {})},
            turns=turns,
            updated_at=datetime.now(timezone.utc),
        )

    def record_character(self, result: CharacterGenerationResult) -> OngoingActivity:
        turns = self.turns
        if turns and turns[-1].turn_id == result.activity_turn_id:
            turns = (*turns[:-1], turns[-1].with_character_result(result))
        return replace(self, turns=turns, updated_at=datetime.now(timezone.utc))

    def record_output(self, result: ActivityOutputResult) -> OngoingActivity:
        turns = self.turns
        if turns and turns[-1].turn_id == result.activity_turn_id:
            turns = (*turns[:-1], turns[-1].with_output_result(result))
        return replace(self, turns=turns, updated_at=datetime.now(timezone.utc))

    def completed(self) -> OngoingActivity:
        return replace(
            self,
            status=ActivityStatus.COMPLETED,
            updated_at=datetime.now(timezone.utc),
        )

    def canceled(self) -> OngoingActivity:
        return replace(
            self,
            status=ActivityStatus.CANCELED,
            updated_at=datetime.now(timezone.utc),
        )

    def paused(self) -> OngoingActivity:
        return replace(
            self,
            status=ActivityStatus.SUSPENDED,
            updated_at=datetime.now(timezone.utc),
        )
