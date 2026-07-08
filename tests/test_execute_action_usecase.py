import pytest

from app.domain.actions import ActionPlan, ActionType
from app.domain.events import AgentEvent, AgentEventType
from app.usecases import ExecuteActionUsecase



class FakeEventPublisher:
    def __init__(self) -> None:
        self.published_events: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.published_events.append(event)


@pytest.mark.asyncio
async def test_speak_action_publishes_speech_started_and_finished_events() -> None:
    event_publisher = FakeEventPublisher()
    usecase = ExecuteActionUsecase(event_publisher=event_publisher)
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="こんにちは",
        source_activity_id="activity-1",
    )

    await usecase.execute(action_plan)

    assert [event.event_type for event in event_publisher.published_events] == [
        AgentEventType.SPEECH_STARTED,
        AgentEventType.SPEECH_FINISHED,
    ]
    assert event_publisher.published_events[0].payload == {
        "action_id": action_plan.action_id,
        "source_activity_id": "activity-1",
        "text": "こんにちは",
    }
    assert event_publisher.published_events[1].payload == {
        "action_id": action_plan.action_id,
        "source_activity_id": "activity-1",
        "text": "こんにちは",
    }


@pytest.mark.asyncio
async def test_speak_action_without_event_publisher_does_not_raise_error() -> None:
    usecase = ExecuteActionUsecase()
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="こんにちは",
    )

    await usecase.execute(action_plan)


@pytest.mark.asyncio
async def test_non_speak_action_does_not_publish_speech_events() -> None:
    event_publisher = FakeEventPublisher()
    usecase = ExecuteActionUsecase(event_publisher=event_publisher)
    action_plan = ActionPlan(
        action_type=ActionType.UPDATE_SUBTITLE,
        text="字幕です",
    )

    await usecase.execute(action_plan)

    assert event_publisher.published_events == []