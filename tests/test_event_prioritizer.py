from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType, InputAuthority
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


def test_administrator_input_outranks_viewer_input() -> None:
    admin = AgentEvent(
        AgentEventType.USER_TEXT,
        {"text": "本題に入って"},
        authority=InputAuthority.ADMINISTRATOR,
    )
    viewer = AgentEvent(
        AgentEventType.YOUTUBE_COMMENT,
        {"comment": "本題に入って"},
        authority=InputAuthority.VIEWER,
    )

    prioritizer = DefaultEventPrioritizer()

    assert (
        prioritizer.prioritize(admin).priority > prioritizer.prioritize(viewer).priority
    )
