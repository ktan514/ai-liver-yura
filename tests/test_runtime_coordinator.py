from __future__ import annotations

import asyncio
from queue import Queue

import pytest

from app.adapters.llm import DummyResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.domain.actions import ActionPlan, ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.drives import DriveState
from app.domain.events import AgentEvent, AgentEventType
from app.ports.response_generator import ResponseGenerator
from app.runtime import (
    ActionPlanner,
    ActivityManager,
    AgentLifeService,
    EventQueue,
    RuntimeCoordinator,
)
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
    ActivityPlanningService,
)
from app.runtime.planned_activity_queue import PlannedActivityQueue


class BlockingAutonomousResponseGenerator:
    def __init__(self) -> None:
        self.autonomous_started = asyncio.Event()
        self.release_autonomous = asyncio.Event()

    async def generate_response(self, activity: Activity) -> str:
        if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            self.autonomous_started.set()
            await self.release_autonomous.wait()
            return "自律発話"
        return f"ユーザー応答: {activity.context['event_payload']['text']}"


class FakeActionExecutor:
    async def execute(self, action_plan: ActionPlan) -> None:
        if action_plan.text:
            print(f"[{action_plan.action_type.value}] {action_plan.text}")


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


def _create_runtime(
    activity_manager: ActivityManager | None = None,
    agent_life_service: AgentLifeService | None = None,
    response_generator: ResponseGenerator | None = None,
) -> RuntimeCoordinator:
    activity_manager = activity_manager or ActivityManager()
    agent_life_service = agent_life_service or AgentLifeService(activity_manager)
    activity_planning_request_queue: Queue[ActivityPlanningRequest] = Queue()
    planned_activity_queue = PlannedActivityQueue()
    response_generator = response_generator or DummyResponseGenerator(
        character_profile=_create_character_profile(),
        prompt_builder=SimplePromptBuilder(),
    )
    action_planner = ActionPlanner(response_generator=response_generator)
    action_scheduler = ActionScheduler(action_executor=FakeActionExecutor())
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

    return RuntimeCoordinator(
        event_queue=EventQueue(),
        activity_manager=activity_manager,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        activity_planning_request_queue=activity_planning_request_queue,
        activity_planner_thread=activity_planner_thread,
        activity_executor_thread=activity_executor_thread,
        agent_life_service=agent_life_service,
    )


async def _drain_runtime(runtime: RuntimeCoordinator) -> list[str]:
    texts: list[str] = []

    while True:
        action_plan_group = await runtime.run_once()
        if action_plan_group is None:
            break

        speak_plans = [
            action_plan
            for action_plan in action_plan_group.action_plans
            if action_plan.action_type == ActionType.SPEAK
        ]
        texts.extend(action_plan.text for action_plan in speak_plans)

    return texts


@pytest.mark.asyncio
async def test_publish_events_keeps_all_user_text_events() -> None:
    runtime = _create_runtime()

    await runtime.publish_events(
        [
            AgentEvent(
                event_type=AgentEventType.USER_TEXT,
                payload={"text": "1つ目"},
            ),
            AgentEvent(
                event_type=AgentEventType.USER_TEXT,
                payload={"text": "2つ目"},
            ),
        ]
    )

    texts = await _drain_runtime(runtime)

    assert texts == [
        "ダミー応答: 1つ目",
        "ダミー応答: 2つ目",
    ]


@pytest.mark.asyncio
async def test_publish_user_text_immediately_suspends_foreground_autonomous() -> None:
    activity_manager = ActivityManager()
    autonomous = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8)
    )
    runtime = _create_runtime(activity_manager=activity_manager)
    user_event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "しりとりしたい"},
        priority=50,
    )

    await runtime.publish_event(user_event)

    activity = activity_manager.get_activity(autonomous.activity_id)
    assert activity is not None
    assert activity.status.value == "suspended"
    assert activity_manager.foreground_activity is not None
    assert activity_manager.foreground_activity.activity_type.value == "conversation_with_user"

    action_group = await runtime.run_once()
    assert action_group is not None
    assert any(action.text == "ダミー応答: しりとりしたい" for action in action_group.action_plans)


@pytest.mark.asyncio
async def test_user_input_during_autonomous_planning_prevents_autonomous_actions() -> None:
    response_generator = BlockingAutonomousResponseGenerator()
    runtime = _create_runtime(response_generator=response_generator)
    await runtime.publish_event(AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8))
    autonomous_task = asyncio.create_task(runtime.run_once())
    await response_generator.autonomous_started.wait()

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "しりとりしたい"},
            priority=50,
        )
    )
    response_generator.release_autonomous.set()
    autonomous_result = await autonomous_task
    user_result = await runtime.run_once()

    assert autonomous_result is not None
    assert autonomous_result.is_empty()
    assert user_result is not None
    assert any(action.text == "ユーザー応答: しりとりしたい" for action in user_result.action_plans)


@pytest.mark.asyncio
async def test_publish_events_replaces_camera_frame_with_latest_only() -> None:
    runtime = _create_runtime()

    await runtime.publish_events(
        [
            AgentEvent(
                event_type=AgentEventType.CAMERA_FRAME,
                payload={"frame_id": "old"},
            ),
            AgentEvent(
                event_type=AgentEventType.CAMERA_FRAME,
                payload={"frame_id": "new"},
            ),
        ]
    )

    first_action = await runtime.run_once()
    second_action = await runtime.run_once()

    assert first_action is not None
    assert any(
        action_plan.action_type == ActionType.OBSERVE for action_plan in first_action.action_plans
    )
    assert second_action is None


@pytest.mark.asyncio
async def test_publish_events_keeps_user_text_and_latest_camera_frame() -> None:
    runtime = _create_runtime()

    await runtime.publish_events(
        [
            AgentEvent(
                event_type=AgentEventType.CAMERA_FRAME,
                payload={"frame_id": "old"},
            ),
            AgentEvent(
                event_type=AgentEventType.USER_TEXT,
                payload={"text": "こんにちは"},
            ),
            AgentEvent(
                event_type=AgentEventType.CAMERA_FRAME,
                payload={"frame_id": "new"},
            ),
        ]
    )

    first_action = await runtime.run_once()
    second_action = await runtime.run_once()
    third_action = await runtime.run_once()

    assert first_action is not None
    speak_plans = [
        action_plan
        for action_plan in first_action.action_plans
        if action_plan.action_type == ActionType.SPEAK
    ]
    assert len(speak_plans) == 1
    assert speak_plans[0].text == "ダミー応答: こんにちは"

    assert second_action is not None
    assert any(
        action_plan.action_type == ActionType.OBSERVE for action_plan in second_action.action_plans
    )

    assert third_action is None


@pytest.mark.asyncio
async def test_run_processes_published_event_until_stopped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = _create_runtime()

    run_task = asyncio.create_task(runtime.run())

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "常時稼働テスト"},
        )
    )

    await asyncio.sleep(0.05)
    runtime.stop()
    await run_task

    captured = capsys.readouterr()
    assert "[speak] ダミー応答: 常時稼働テスト" in captured.out


@pytest.mark.asyncio
async def test_run_can_be_stopped_without_events() -> None:
    runtime = _create_runtime()

    run_task = asyncio.create_task(runtime.run())

    await asyncio.sleep(0.02)
    runtime.stop()
    await run_task

    assert run_task.done()


@pytest.mark.asyncio
async def test_run_once_updates_agent_life_loop_state() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    runtime = _create_runtime(
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
    )

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "状態更新テスト"},
        )
    )

    await runtime.run_once()

    assert agent_life_service.agent_state.last_user_input_at is not None
    assert agent_life_service.agent_state.active_activity is None


@pytest.mark.asyncio
async def test_speech_lifecycle_event_updates_agent_life_loop_only() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    runtime = _create_runtime(
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
    )

    await runtime.publish_event(AgentEvent(event_type=AgentEventType.SPEECH_STARTED))

    action_plan_group = await runtime.run_once()

    assert action_plan_group is not None
    assert action_plan_group.is_empty()
    assert agent_life_service.agent_state.last_speech_started_at is not None
    assert agent_life_service.agent_state.active_activity is None


# Additional tests for autonomous event planning


@pytest.mark.asyncio
async def test_run_once_plans_autonomous_event_when_event_queue_is_empty() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    agent_life_service.update_drive(DriveState(curiosity=0.9))
    runtime = _create_runtime(
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
    )

    action_plan_group = await runtime.run_once()

    assert action_plan_group is None
    assert runtime._activity_planning_request_queue.qsize() == 1  # noqa: SLF001
    assert agent_life_service.agent_state.active_activity is None


@pytest.mark.asyncio
async def test_run_once_plans_autonomous_event_even_when_event_queue_has_event() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    agent_life_service.update_drive(DriveState(curiosity=0.9))
    runtime = _create_runtime(
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
    )

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.CAMERA_FRAME,
            payload={"frame_id": "latest"},
        )
    )

    first_action_plan_group = await runtime.run_once()
    second_action_plan_group = await runtime.run_once()

    assert first_action_plan_group is not None
    assert any(
        action_plan.action_type == ActionType.OBSERVE
        for action_plan in first_action_plan_group.action_plans
    )
    assert second_action_plan_group is None
    assert runtime._activity_planning_request_queue.qsize() == 1  # noqa: SLF001


@pytest.mark.asyncio
async def test_run_once_does_not_plan_autonomous_event_when_active_activity_exists() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    runtime = _create_runtime(
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
    )

    await runtime.publish_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )
    await runtime.run_once()

    assert agent_life_service.agent_state.active_activity is None
