

from __future__ import annotations

import asyncio

import pytest

from app.adapters.llm import DummyResponseGenerator
from app.domain.actions import ActionType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import ActionPlanner, ActivityManager, EventQueue, RuntimeCoordinator
from app.usecases import ExecuteActionUsecase


def _create_runtime() -> RuntimeCoordinator:
    return RuntimeCoordinator(
        event_queue=EventQueue(),
        activity_manager=ActivityManager(),
        action_planner=ActionPlanner(response_generator=DummyResponseGenerator()),
        action_executor=ExecuteActionUsecase(),
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
        action_plan.action_type == ActionType.OBSERVE
        for action_plan in first_action.action_plans
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
        action_plan.action_type == ActionType.OBSERVE
        for action_plan in second_action.action_plans
    )

    assert third_action is None



@pytest.mark.asyncio
async def test_run_processes_published_event_until_stopped(capsys: pytest.CaptureFixture[str]) -> None:
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