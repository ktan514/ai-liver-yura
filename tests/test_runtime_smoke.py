from __future__ import annotations

from queue import Queue

import pytest

from app.adapters.llm import DummyResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.domain.actions import ActionType
from app.domain.character import CharacterProfile
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import ActionPlanner, ActivityManager, EventQueue, RuntimeCoordinator
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
    ActivityPlanningService,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.planned_activity_queue import PlannedActivityQueue
from app.usecases import ExecuteActionUsecase


def _create_character_profile() -> CharacterProfile:
    return CharacterProfile(
        name="ミナト",
        personality="明るく好奇心が強い",
        speaking_style="親しみやすく、少しくだけた口調",
        streaming_style="視聴者と一緒に楽しむ雑談配信",
        likes=["海の生き物", "ゲーム"],
        dislikes=["攻撃的な話題"],
        behavior_policy=["短く自然に返答する"],
    )


@pytest.mark.asyncio
async def test_runtime_handles_user_text_event() -> None:
    event_queue = EventQueue()
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    activity_planning_request_queue: Queue[ActivityPlanningRequest] = Queue()
    planned_activity_queue = PlannedActivityQueue()
    action_planner = ActionPlanner(
        response_generator=DummyResponseGenerator(
            character_profile=_create_character_profile(),
            prompt_builder=SimplePromptBuilder(),
        )
    )
    action_scheduler = ActionScheduler(action_executor=ExecuteActionUsecase())
    activity_planning_service = ActivityPlanningService(
        agent_life_service=agent_life_service,
        activity_manager=activity_manager,
    )
    activity_planner_thread = ActivityPlannerThread(
        request_queue=activity_planning_request_queue,
        planned_activity_queue=planned_activity_queue,
        planning_service=activity_planning_service,
    )
    activity_executor_thread = ActivityExecutorThread(
        planned_activity_queue=planned_activity_queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
    )
    runtime = RuntimeCoordinator(
        event_queue=event_queue,
        activity_manager=activity_manager,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        activity_planning_request_queue=activity_planning_request_queue,
        activity_planner_thread=activity_planner_thread,
        activity_executor_thread=activity_executor_thread,
        agent_life_service=agent_life_service,
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
