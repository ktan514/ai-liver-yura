from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionType
from app.domain.activities import Activity, ActivityStatus, ActivityType
from app.domain.activity_turn_result import (
    ActionExecutionStatus,
    ActivityOutputStatus,
    ActivityTurnResult,
    CharacterGenerationResult,
    CharacterGenerationStatus,
)
from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_turn_result_factory import action_planning_failure_group


def _execution(status: ActivityExecutionStatus) -> ActivityExecutionResult:
    return ActivityExecutionResult(
        activity_type="external_search",
        operation="start",
        status=status,
        payload={"summary": "実処理の結果"},
    )


def _character(turn_id: str, status: CharacterGenerationStatus) -> CharacterGenerationResult:
    now = datetime.now(timezone.utc)
    return CharacterGenerationResult(
        status=status,
        activity_turn_id=turn_id,
        adopted_text="結果を伝えます",
        started_at=now,
        finished_at=now,
    )


def test_confirmation_correlation_is_copied_to_activity_turn_result() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="確認する",
        source_event_id="resolution-event",
        context={
            "event_payload": {
                "pending_confirmation": {
                    "confirmation_id": "confirmation-1",
                    "source_event_id": "source-event",
                    "resolution_event_id": "resolution-event",
                    "candidate_activity_type": "shiritori",
                    "candidate_operation": "start",
                    "resolution": "affirmative",
                    "final_behavior_plan_id": "plan-1",
                }
            }
        },
    )

    result = ActionPlanner._turn_result(activity, None)

    assert result.confirmation_id == "confirmation-1"
    assert result.confirmation_source_event_id == "source-event"
    assert result.resolution_event_id == "resolution-event"
    assert result.candidate_activity_type == "shiritori"
    assert result.candidate_operation == "start"
    assert result.confirmation_resolution == "affirmative"
    assert result.final_behavior_plan_id == "plan-1"


@pytest.mark.asyncio
async def test_all_stages_succeed_and_correlations_are_preserved() -> None:
    execution = _execution(ActivityExecutionStatus.SUCCEEDED)
    aggregate = ActivityTurnResult(
        activity_turn_id="turn-1",
        activity_type="external_search",
        source_event_id="event-1",
        execution_result=execution,
        character_result=_character("turn-1", CharacterGenerationStatus.VALIDATED),
    )

    class Executor:
        async def execute(self, action_plan: ActionPlan) -> None:
            return None

    group = ActionPlanGroup(
        action_plans=[ActionPlan(action_type=ActionType.UPDATE_SUBTITLE, text="result")],
        source_activity_id="activity-1",
        activity_turn_result=aggregate,
    )
    output = await ActionScheduler(Executor()).execute(group)
    completed = aggregate.with_output(output)

    assert completed.final_status == "completed"
    assert completed.execution_result is execution
    assert output.activity_turn_id == "turn-1"
    assert output.source_event_id == "event-1"
    assert output.action_results[0].output_unit_id == group.group_id
    assert output.action_results[0].status == ActionExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_plugin_rejection_and_successful_explanation_remain_distinct() -> None:
    aggregate = ActivityTurnResult(
        activity_turn_id="turn-rejected",
        activity_type="stream_control",
        execution_result=_execution(ActivityExecutionStatus.REJECTED),
        character_result=_character("turn-rejected", CharacterGenerationStatus.VALIDATED),
    )

    class Executor:
        async def execute(self, action_plan: ActionPlan) -> None:
            return None

    group = ActionPlanGroup(
        action_plans=[ActionPlan(action_type=ActionType.SPEAK, text="今は操作できません")],
        activity_turn_result=aggregate,
    )
    output = await ActionScheduler(Executor()).execute(group)
    result = aggregate.with_output(output)

    assert result.execution_result is not None
    assert result.execution_result.status == ActivityExecutionStatus.REJECTED
    assert result.output_result is not None
    assert result.output_result.status == ActivityOutputStatus.COMPLETED
    assert result.final_status == "execution_rejected"


@pytest.mark.asyncio
async def test_tts_failure_produces_partial_output_without_rewriting_execution() -> None:
    aggregate = ActivityTurnResult(
        activity_turn_id="turn-partial",
        activity_type="shiritori",
        execution_result=_execution(ActivityExecutionStatus.SUCCEEDED),
        character_result=_character("turn-partial", CharacterGenerationStatus.FALLBACK_USED),
    )

    class Executor:
        async def execute(self, action_plan: ActionPlan) -> None:
            if action_plan.action_type == ActionType.SPEAK:
                raise RuntimeError("tts unavailable")

    group = ActionPlanGroup(
        action_plans=[
            ActionPlan(action_type=ActionType.UPDATE_SUBTITLE, text="表示"),
            ActionPlan(action_type=ActionType.CHANGE_EXPRESSION, text="smile"),
            ActionPlan(action_type=ActionType.SPEAK, text="発話"),
        ],
        activity_turn_result=aggregate,
    )
    output = await ActionScheduler(Executor()).execute(group)
    result = aggregate.with_output(output)

    assert output.status == ActivityOutputStatus.PARTIALLY_COMPLETED
    assert [item.status for item in output.action_results].count(
        ActionExecutionStatus.COMPLETED
    ) == 2
    assert [item.status for item in output.action_results].count(ActionExecutionStatus.FAILED) == 1
    assert result.execution_result is not None
    assert result.execution_result.status == ActivityExecutionStatus.SUCCEEDED
    assert result.failure_stage == "action_execution"


@pytest.mark.asyncio
async def test_output_cancel_does_not_cancel_plugin_execution() -> None:
    aggregate = ActivityTurnResult(
        activity_turn_id="turn-cancel",
        activity_type="external_search",
        execution_result=_execution(ActivityExecutionStatus.SUCCEEDED),
    )

    class Executor:
        async def execute(self, action_plan: ActionPlan) -> None:
            raise asyncio.CancelledError

    output = await ActionScheduler(Executor()).execute(
        ActionPlanGroup(
            action_plans=[ActionPlan(action_type=ActionType.OBSERVE)],
            activity_turn_result=aggregate,
        )
    )

    assert output.status == ActivityOutputStatus.CANCELED
    assert aggregate.execution_result is not None
    assert aggregate.execution_result.status == ActivityExecutionStatus.SUCCEEDED


def test_action_planning_failure_is_a_turn_result_not_a_runtime_exception() -> None:
    execution = _execution(ActivityExecutionStatus.SUCCEEDED)
    character = _character("activity-plan", CharacterGenerationStatus.VALIDATED)
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="検索結果を説明する",
        source_event_id="event-plan",
        context={
            "activity_execution_result": execution,
            "character_generation_result": character,
            "activity_turn_id": "activity-plan",
        },
    )

    group = action_planning_failure_group(activity, ValueError("invalid action"))
    result = group.activity_turn_result

    assert result is not None
    assert result.execution_result is execution
    assert result.character_result is not None
    assert result.character_result is character
    assert result.character_result.status == CharacterGenerationStatus.VALIDATED
    assert result.output_result is not None
    assert result.output_result.status == ActivityOutputStatus.FAILED
    assert result.failure_stage == "action_planning"


@pytest.mark.asyncio
async def test_ongoing_activity_keeps_session_when_output_is_partial() -> None:
    manager = ActivityManager()
    ongoing = manager.start_ongoing_activity(
        activity_type="shiritori",
        goal="しりとりを続ける",
        expected_input="次の単語",
        end_condition="終了指示",
    )
    updated = manager.begin_ongoing_turn(
        input_text="ごまあざらし",
        source_event_id="event-game",
        operation="continue",
    )
    assert updated is not None
    ongoing = updated
    turn_id = ongoing.turns[-1].turn_id
    execution = ActivityExecutionResult(
        activity_type="shiritori",
        operation="continue",
        status=ActivityExecutionStatus.SUCCEEDED,
    )
    manager.record_ongoing_execution(execution, waiting_input=True)
    aggregate = ActivityTurnResult(
        activity_turn_id=turn_id,
        ongoing_activity_id=ongoing.ongoing_activity_id,
        source_event_id="event-game",
        activity_type="shiritori",
        execution_result=execution,
        character_result=_character(turn_id, CharacterGenerationStatus.VALIDATED),
    )

    class Executor:
        async def execute(self, action_plan: ActionPlan) -> None:
            if action_plan.action_type == ActionType.SPEAK:
                raise RuntimeError("tts failed")

    group = ActionPlanGroup(
        action_plans=[
            ActionPlan(action_type=ActionType.UPDATE_SUBTITLE),
            ActionPlan(action_type=ActionType.SPEAK),
        ],
        activity_turn_result=aggregate,
    )
    output = await ActionScheduler(Executor()).execute(group)
    manager.record_output_result(aggregate, output)
    current = manager.ongoing_activity

    assert current is not None
    assert current.status == ActivityStatus.WAITING
    assert current.turns[-1].turn_result is not None
    assert current.turns[-1].turn_result.output_result is not None
    assert (
        current.turns[-1].turn_result.output_result.status
        == ActivityOutputStatus.PARTIALLY_COMPLETED
    )


@pytest.mark.parametrize("activity_type", ["shiritori", "external_search", "stream_control"])
def test_result_model_is_activity_type_agnostic(activity_type: str) -> None:
    result = ActivityTurnResult(
        activity_turn_id=f"turn-{activity_type}",
        activity_type=activity_type,
        execution_result=ActivityExecutionResult(
            activity_type=activity_type,
            operation="start",
            status=ActivityExecutionStatus.SUCCEEDED,
        ),
    )

    assert result.activity_type == activity_type
    assert result.final_status == "in_progress"
