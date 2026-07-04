from __future__ import annotations

import pytest

from app.adapters.llm import DummyResponseGenerator
from app.domain.actions import ActionType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import ActionPlanner, ActivityManager, EventQueue, RuntimeCoordinator
from app.usecases import ExecuteActionUsecase


@pytest.mark.asyncio
async def test_runtime_handles_user_text_event() -> None:
    runtime = RuntimeCoordinator(
        event_queue=EventQueue(),
        activity_manager=ActivityManager(),
        action_planner=ActionPlanner(response_generator=DummyResponseGenerator()),
        action_executor=ExecuteActionUsecase(),
    )

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "テスト"},
            priority=10,
        )
    )

    action_plan_group = await runtime.run_once()

    assert action_plan_group is not None

    speak_plans = [
        action_plan
        for action_plan in action_plan_group.action_plans
        if action_plan.action_type == ActionType.SPEAK
    ]

    assert len(speak_plans) == 1
    assert speak_plans[0].text == "ダミー応答: テスト"
