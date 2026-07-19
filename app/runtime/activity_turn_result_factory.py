from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.actions import ActionPlanGroup
from app.domain.activities import Activity
from app.domain.activity_turn_result import (
    ActivityOutputResult,
    ActivityOutputStatus,
    ActivityTurnResult,
    CharacterGenerationResult,
    CharacterGenerationStatus,
)
from app.domain.character_response import ActivityExecutionResult
from app.utils.llm_trace import build_llm_trace_context


def action_planning_failure_group(
    activity: Activity, error: Exception
) -> ActionPlanGroup:
    """Action計画例外をTurn失敗へ変換し、Runtimeを継続可能にする。"""

    turn = activity.context.get("activity_turn")
    ongoing = activity.context.get("ongoing_activity")
    activity_turn_id = str(
        getattr(turn, "turn_id", None)
        or activity.context.get("activity_turn_id")
        or activity.activity_id
    )
    ongoing_activity_id_value = getattr(ongoing, "ongoing_activity_id", None)
    ongoing_activity_id = (
        str(ongoing_activity_id_value)
        if ongoing_activity_id_value is not None
        else None
    )
    execution_value = activity.context.get("activity_execution_result")
    payload = activity.context.get("event_payload")
    if not isinstance(execution_value, ActivityExecutionResult) and isinstance(
        payload, dict
    ):
        execution_value = payload.get("activity_execution_result")
    execution_result = (
        execution_value
        if isinstance(execution_value, ActivityExecutionResult)
        else None
    )
    now = datetime.now(timezone.utc)
    trace = build_llm_trace_context(activity).trace_context
    character_value = activity.context.get("character_generation_result")
    character_result = (
        character_value
        if isinstance(character_value, CharacterGenerationResult)
        else CharacterGenerationResult(
            status=CharacterGenerationStatus.NOT_STARTED,
            activity_turn_id=activity_turn_id,
            ongoing_activity_id=ongoing_activity_id,
            source_event_id=activity.source_event_id,
            error="action_planning_failed_before_character_result_was_committed",
            started_at=now,
            finished_at=now,
            trace_id=trace.trace_id,
            parent_trace_id=trace.parent_trace_id,
            behavior_plan_id=trace.behavior_plan_id,
        )
    )
    output_unit_id = str(uuid4())
    output_result = ActivityOutputResult(
        status=ActivityOutputStatus.FAILED,
        output_unit_id=output_unit_id,
        activity_turn_id=activity_turn_id,
        ongoing_activity_id=ongoing_activity_id,
        source_event_id=activity.source_event_id,
        failure_stage="action_planning",
        error=f"{type(error).__name__}: {error}",
        started_at=now,
        finished_at=now,
        trace_id=trace.trace_id,
        parent_trace_id=trace.parent_trace_id,
        behavior_plan_id=trace.behavior_plan_id,
    )
    aggregate = ActivityTurnResult(
        activity_turn_id=activity_turn_id,
        activity_type=(
            execution_result.activity_type
            if execution_result is not None
            else activity.activity_type.value
        ),
        source_event_id=activity.source_event_id,
        ongoing_activity_id=ongoing_activity_id,
        operation=execution_result.operation if execution_result is not None else None,
        execution_result=execution_result,
        character_result=character_result,
        trace_id=trace.trace_id,
        parent_trace_id=trace.parent_trace_id,
        behavior_plan_id=trace.behavior_plan_id,
    ).with_output(output_result)
    return ActionPlanGroup(
        source_activity_id=activity.activity_id,
        group_id=output_unit_id,
        activity_turn_result=aggregate,
    )


def canceled_output_group(group: ActionPlanGroup, *, reason: str) -> ActionPlanGroup:
    """Output開始前のActivity取消を段階別Resultへ変換する。"""

    base = group.activity_turn_result
    if base is None:
        return ActionPlanGroup(source_activity_id=group.source_activity_id)
    now = datetime.now(timezone.utc)
    output = ActivityOutputResult(
        status=ActivityOutputStatus.CANCELED,
        output_unit_id=group.group_id,
        activity_turn_id=base.activity_turn_id,
        ongoing_activity_id=base.ongoing_activity_id,
        source_event_id=base.source_event_id,
        failure_stage="action_execution",
        error=reason,
        activity_result_id=(
            base.output_result.activity_result_id
            if base.output_result is not None
            else str(uuid4())
        ),
        started_at=(
            base.output_result.started_at if base.output_result is not None else now
        ),
        finished_at=now,
        trace_id=base.trace_id,
        parent_trace_id=base.parent_trace_id,
        behavior_plan_id=base.behavior_plan_id,
    )
    return ActionPlanGroup(
        source_activity_id=group.source_activity_id,
        group_id=group.group_id,
        output_priority=group.output_priority,
        activity_turn_result=base.with_output(output),
    )
