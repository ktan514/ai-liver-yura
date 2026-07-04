

from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_prioritizer import DefaultEventPrioritizer


def test_user_text_priority_is_boosted() -> None:
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
        priority=10,
    )

    prioritized = DefaultEventPrioritizer().prioritize(event)

    assert prioritized.priority == 60


def test_youtube_comment_priority_is_boosted() -> None:
    event = AgentEvent(
        event_type=AgentEventType.YOUTUBE_COMMENT,
        payload={"comment": "初見です"},
        priority=10,
    )

    prioritized = DefaultEventPrioritizer().prioritize(event)

    assert prioritized.priority == 50


def test_camera_frame_priority_boost_is_small() -> None:
    event = AgentEvent(
        event_type=AgentEventType.CAMERA_FRAME,
        payload={"frame_id": "dummy"},
        priority=10,
    )

    prioritized = DefaultEventPrioritizer().prioritize(event)

    assert prioritized.priority == 13