from __future__ import annotations

import asyncio

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.runtime.action_scheduler import ActionScheduler


@pytest.mark.asyncio
async def test_empty_action_plan_group_does_nothing() -> None:
    executed: list[ActionType] = []

    async def executor(action_plan: ActionPlan) -> None:
        executed.append(action_plan.action_type)

    scheduler = ActionScheduler(executor)

    await scheduler.execute(ActionPlanGroup())

    assert executed == []


@pytest.mark.asyncio
async def test_actions_with_different_resources_are_executed() -> None:
    executed: list[ActionType] = []

    async def executor(action_plan: ActionPlan) -> None:
        executed.append(action_plan.action_type)

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

    assert sorted(executed) == sorted([ActionType.SPEAK, ActionType.CHANGE_EXPRESSION])


@pytest.mark.asyncio
async def test_action_without_required_resources_is_executed() -> None:
    executed: list[ActionType] = []

    async def executor(action_plan: ActionPlan) -> None:
        executed.append(action_plan.action_type)

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

    assert executed == [ActionType.OBSERVE]


@pytest.mark.asyncio
async def test_actions_with_same_resource_do_not_run_at_the_same_time() -> None:
    running_mouth_actions = 0
    max_running_mouth_actions = 0
    executed: list[str] = []

    async def executor(action_plan: ActionPlan) -> None:
        nonlocal running_mouth_actions
        nonlocal max_running_mouth_actions

        if ActionResource.MOUTH in action_plan.required_resources:
            running_mouth_actions += 1
            max_running_mouth_actions = max(max_running_mouth_actions, running_mouth_actions)

        await asyncio.sleep(0.01)
        executed.append(action_plan.text)

        if ActionResource.MOUTH in action_plan.required_resources:
            running_mouth_actions -= 1

    scheduler = ActionScheduler(executor)
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
