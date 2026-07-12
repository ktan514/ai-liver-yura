from __future__ import annotations

import pytest

from app.domain.actions import ActionResource, ActionType
from app.domain.activities import Activity, ActivityType
from app.runtime.action_planner import ActionPlanner


class FakeResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return f"generated: {activity.goal}"


@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_conversation() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert {plan.output_unit_id for plan in action_plan_group.action_plans} == {
        action_plan_group.group_id
    }
    assert action_plan_group.output_priority == 100
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert action_plan_group.action_plans[0].text == "generated: ユーザー入力に応答する"
    assert action_plan_group.action_plans[0].required_resources == {ActionResource.MOUTH}
    assert action_plan_group.action_plans[1].text == "generated: ユーザー入力に応答する"
    assert action_plan_group.action_plans[1].required_resources == {ActionResource.SUBTITLE}
    assert action_plan_group.action_plans[2].text == "smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


# Additional tests for startup, stream opening, and stream closing greetings
@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_startup_reaction() -> None:
    activity = Activity(
        activity_type=ActivityType.STARTUP_REACTION,
        goal="起動直後の状況に反応する",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert action_plan_group.output_priority == 50
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert action_plan_group.action_plans[0].text == "generated: 起動直後の状況に反応する"
    assert action_plan_group.action_plans[0].required_resources == {ActionResource.MOUTH}
    assert action_plan_group.action_plans[1].text == "generated: 起動直後の状況に反応する"
    assert action_plan_group.action_plans[1].required_resources == {ActionResource.SUBTITLE}
    assert action_plan_group.action_plans[2].text == "smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_stream_opening_greeting() -> None:
    activity = Activity(
        activity_type=ActivityType.STREAM_OPENING_GREETING,
        goal="配信開始時のあいさつをする",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert action_plan_group.action_plans[0].text == "generated: 配信開始時のあいさつをする"
    assert action_plan_group.action_plans[0].required_resources == {ActionResource.MOUTH}
    assert action_plan_group.action_plans[1].text == "generated: 配信開始時のあいさつをする"
    assert action_plan_group.action_plans[1].required_resources == {ActionResource.SUBTITLE}
    assert action_plan_group.action_plans[2].text == "smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_stream_closing_greeting() -> None:
    activity = Activity(
        activity_type=ActivityType.STREAM_CLOSING_GREETING,
        goal="配信終了前のあいさつをする",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert action_plan_group.action_plans[0].text == "generated: 配信終了前のあいさつをする"
    assert action_plan_group.action_plans[0].required_resources == {ActionResource.MOUTH}
    assert action_plan_group.action_plans[1].text == "generated: 配信終了前のあいさつをする"
    assert action_plan_group.action_plans[1].required_resources == {ActionResource.SUBTITLE}
    assert action_plan_group.action_plans[2].text == "soft_smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_autonomous_talk() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert action_plan_group.output_priority == 10
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
    ]
    assert action_plan_group.action_plans[0].text == "generated: 自律的に話題を出して話す"
    assert action_plan_group.action_plans[0].required_resources == {ActionResource.MOUTH}
    assert action_plan_group.action_plans[1].text == "generated: 自律的に話題を出して話す"
    assert action_plan_group.action_plans[1].required_resources == {ActionResource.SUBTITLE}


@pytest.mark.asyncio
async def test_action_planner_returns_observe_plan_for_other_activity() -> None:
    activity = Activity(
        activity_type=ActivityType.IDLE_OBSERVATION,
        goal="状態を観察する",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert len(action_plan_group.action_plans) == 1
    assert action_plan_group.action_plans[0].action_type == ActionType.OBSERVE
    assert action_plan_group.action_plans[0].required_resources == {ActionResource.EYES}
