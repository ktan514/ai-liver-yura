from __future__ import annotations

import asyncio

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.domain.activity_turn_result import ActionExecutionStatus
from app.runtime.action_scheduler import ActionScheduler


class FakeActionExecutor:
    def __init__(self) -> None:
        self.executed: list[ActionPlan] = []

    async def execute(self, action_plan: ActionPlan) -> None:
        self.executed.append(action_plan)


@pytest.mark.asyncio
async def test_empty_action_plan_group_does_nothing() -> None:
    executor = FakeActionExecutor()
    scheduler = ActionScheduler(executor)

    await scheduler.execute(ActionPlanGroup())

    assert executor.executed == []


@pytest.mark.asyncio
async def test_actions_with_different_resources_are_executed() -> None:
    executor = FakeActionExecutor()
    scheduler = ActionScheduler(executor)
    group = ActionPlanGroup(
        action_plans=[
            ActionPlan(
                action_type=ActionType.SPEAK,
                text="hello",
                required_resources={ActionResource.MOUTH},
            ),
            ActionPlan(
                action_type=ActionType.CHANGE_EXPRESSION,
                text="smile",
                required_resources={ActionResource.FACE},
            ),
        ]
    )

    await scheduler.execute(group)

    executed_action_types = [
        action_plan.action_type for action_plan in executor.executed
    ]

    assert sorted(executed_action_types) == sorted(
        [ActionType.SPEAK, ActionType.CHANGE_EXPRESSION]
    )


@pytest.mark.asyncio
async def test_action_without_required_resources_is_executed() -> None:
    executor = FakeActionExecutor()
    scheduler = ActionScheduler(executor)
    group = ActionPlanGroup(
        action_plans=[
            ActionPlan(
                action_type=ActionType.OBSERVE,
                text="",
            ),
        ]
    )

    await scheduler.execute(group)

    assert [action_plan.action_type for action_plan in executor.executed] == [
        ActionType.OBSERVE
    ]


@pytest.mark.asyncio
async def test_actions_with_same_resource_do_not_run_at_the_same_time() -> None:
    running_mouth_actions = 0
    max_running_mouth_actions = 0
    executed: list[str] = []

    class SlowMouthActionExecutor:
        async def execute(self, action_plan: ActionPlan) -> None:
            nonlocal running_mouth_actions
            nonlocal max_running_mouth_actions

            if ActionResource.MOUTH in action_plan.required_resources:
                running_mouth_actions += 1
                max_running_mouth_actions = max(
                    max_running_mouth_actions,
                    running_mouth_actions,
                )

            await asyncio.sleep(0.01)
            executed.append(action_plan.text)

            if ActionResource.MOUTH in action_plan.required_resources:
                running_mouth_actions -= 1

    scheduler = ActionScheduler(SlowMouthActionExecutor())
    group = ActionPlanGroup(
        action_plans=[
            ActionPlan(
                action_type=ActionType.SPEAK,
                text="first",
                required_resources={ActionResource.MOUTH},
            ),
            ActionPlan(
                action_type=ActionType.SPEAK,
                text="second",
                required_resources={ActionResource.MOUTH},
            ),
        ]
    )

    await scheduler.execute(group)

    assert sorted(executed) == ["first", "second"]
    assert max_running_mouth_actions == 1


@pytest.mark.asyncio
async def test_speech_output_keeps_subtitle_and_expression_in_the_same_unit() -> None:
    first_speech_started = asyncio.Event()
    release_first_speech = asyncio.Event()
    execution_order: list[tuple[str | None, ActionType, str]] = []

    class BlockingSpeechExecutor:
        async def execute(self, action_plan: ActionPlan) -> None:
            execution_order.append(
                (action_plan.output_unit_id, action_plan.action_type, action_plan.text)
            )
            if (
                action_plan.action_type == ActionType.SPEAK
                and action_plan.text == "first"
            ):
                first_speech_started.set()
                await release_first_speech.wait()

    scheduler = ActionScheduler(BlockingSpeechExecutor())

    def output_group(text: str) -> ActionPlanGroup:
        group = ActionPlanGroup()
        plans = [
            ActionPlan(
                action_type=ActionType.SPEAK,
                text=text,
                required_resources={ActionResource.MOUTH},
                output_unit_id=group.group_id,
            ),
            ActionPlan(
                action_type=ActionType.UPDATE_SUBTITLE,
                text=text,
                required_resources={ActionResource.SUBTITLE},
                output_unit_id=group.group_id,
            ),
            ActionPlan(
                action_type=ActionType.CHANGE_EXPRESSION,
                text=f"{text}-expression",
                required_resources={ActionResource.FACE},
                output_unit_id=group.group_id,
            ),
        ]
        return ActionPlanGroup(action_plans=plans, group_id=group.group_id)

    first_group = output_group("first")
    second_group = output_group("second")
    first_task = asyncio.create_task(scheduler.execute(first_group))
    await first_speech_started.wait()
    second_task = asyncio.create_task(scheduler.execute(second_group))
    await asyncio.sleep(0)

    assert all(text != "second" for _, _, text in execution_order)

    release_first_speech.set()
    await asyncio.gather(first_task, second_task)

    assert execution_order == [
        (first_group.group_id, ActionType.UPDATE_SUBTITLE, "first"),
        (first_group.group_id, ActionType.CHANGE_EXPRESSION, "first-expression"),
        (first_group.group_id, ActionType.SPEAK, "first"),
        (second_group.group_id, ActionType.UPDATE_SUBTITLE, "second"),
        (second_group.group_id, ActionType.CHANGE_EXPRESSION, "second-expression"),
        (second_group.group_id, ActionType.SPEAK, "second"),
    ]


@pytest.mark.asyncio
async def test_reaction_segments_execute_in_declared_order() -> None:
    executed: list[tuple[int, ActionType, str]] = []

    class RecordingExecutor:
        async def execute(self, action_plan: ActionPlan) -> None:
            executed.append(
                (
                    int(action_plan.metadata["reaction_segment_index"]),
                    action_plan.action_type,
                    action_plan.text,
                )
            )

    group = ActionPlanGroup()
    plans = []
    for index, speech in enumerate(("first", "second")):
        metadata = {"reaction_segment_index": index}
        plans.extend(
            [
                ActionPlan(ActionType.SPEAK, speech, metadata=metadata),
                ActionPlan(ActionType.UPDATE_SUBTITLE, speech, metadata=metadata),
                ActionPlan(
                    ActionType.CHANGE_EXPRESSION,
                    f"expression-{index}",
                    metadata=metadata,
                ),
            ]
        )
    group = ActionPlanGroup(action_plans=plans, group_id=group.group_id)

    await ActionScheduler(RecordingExecutor()).execute(group)

    assert executed == [
        (0, ActionType.UPDATE_SUBTITLE, "first"),
        (0, ActionType.CHANGE_EXPRESSION, "expression-0"),
        (0, ActionType.SPEAK, "first"),
        (1, ActionType.UPDATE_SUBTITLE, "second"),
        (1, ActionType.CHANGE_EXPRESSION, "expression-1"),
        (1, ActionType.SPEAK, "second"),
    ]


@pytest.mark.asyncio
async def test_user_input_cancels_only_segments_after_current_speech() -> None:
    first_speech_started = asyncio.Event()
    release_first_speech = asyncio.Event()
    executed: list[tuple[int, ActionType]] = []

    class BlockingExecutor:
        async def execute(self, action_plan: ActionPlan) -> None:
            executed.append(
                (
                    int(action_plan.metadata["reaction_segment_index"]),
                    action_plan.action_type,
                )
            )
            if action_plan.action_type == ActionType.SPEAK:
                first_speech_started.set()
                await release_first_speech.wait()

    activity_id = "autonomous-activity"
    plans: list[ActionPlan] = []
    for index in range(2):
        metadata = {"reaction_segment_index": index}
        plans.extend(
            (
                ActionPlan(ActionType.UPDATE_SUBTITLE, str(index), metadata=metadata),
                ActionPlan(ActionType.CHANGE_EXPRESSION, "smile", metadata=metadata),
                ActionPlan(ActionType.SPEAK, str(index), metadata=metadata),
            )
        )
    group = ActionPlanGroup(
        action_plans=plans,
        source_activity_id=activity_id,
    )
    scheduler = ActionScheduler(BlockingExecutor())

    execution = asyncio.create_task(scheduler.execute(group))
    await first_speech_started.wait()
    scheduler.cancel_pending_segments(activity_id)
    release_first_speech.set()
    result = await execution

    assert executed == [
        (0, ActionType.UPDATE_SUBTITLE),
        (0, ActionType.CHANGE_EXPRESSION),
        (0, ActionType.SPEAK),
    ]
    assert [item.status for item in result.action_results] == [
        ActionExecutionStatus.COMPLETED,
        ActionExecutionStatus.COMPLETED,
        ActionExecutionStatus.COMPLETED,
        ActionExecutionStatus.CANCELED,
        ActionExecutionStatus.CANCELED,
        ActionExecutionStatus.CANCELED,
    ]


@pytest.mark.asyncio
async def test_user_speech_overtakes_waiting_autonomous_speech_without_reordering_users() -> (
    None
):
    active_speech_started = asyncio.Event()
    release_active_speech = asyncio.Event()
    execution_order: list[str] = []

    class BlockingExecutor:
        async def execute(self, action_plan: ActionPlan) -> None:
            execution_order.append(action_plan.text)
            if action_plan.text == "active-autonomous":
                active_speech_started.set()
                await release_active_speech.wait()

    scheduler = ActionScheduler(BlockingExecutor())

    def speech_group(text: str, priority: int) -> ActionPlanGroup:
        return ActionPlanGroup(
            action_plans=[
                ActionPlan(
                    action_type=ActionType.SPEAK,
                    text=text,
                    required_resources={ActionResource.MOUTH},
                )
            ],
            output_priority=priority,
        )

    tasks = [
        asyncio.create_task(scheduler.execute(speech_group("active-autonomous", 10)))
    ]
    await active_speech_started.wait()
    tasks.append(
        asyncio.create_task(scheduler.execute(speech_group("waiting-autonomous", 10)))
    )
    await asyncio.sleep(0.01)
    tasks.append(asyncio.create_task(scheduler.execute(speech_group("user-1", 100))))
    await asyncio.sleep(0.01)
    tasks.append(asyncio.create_task(scheduler.execute(speech_group("user-2", 100))))
    await asyncio.sleep(0.01)

    release_active_speech.set()
    await asyncio.gather(*tasks)

    assert execution_order == [
        "active-autonomous",
        "user-1",
        "user-2",
        "waiting-autonomous",
    ]
