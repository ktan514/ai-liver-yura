

from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_buffer import EventBuffer


def test_normal_events_are_kept_in_order() -> None:
    buffer = EventBuffer()

    first = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "1つ目"},
    )
    second = AgentEvent(
        event_type=AgentEventType.YOUTUBE_COMMENT,
        payload={"comment": "2つ目"},
    )

    buffer.put(first)
    buffer.put(second)

    drained = buffer.drain()

    assert drained == [first, second]
    assert buffer.is_empty() is True


def test_replaceable_event_keeps_latest_only() -> None:
    buffer = EventBuffer()

    old_frame = AgentEvent(
        event_type=AgentEventType.CAMERA_FRAME,
        payload={"frame_id": "old"},
        replace_key="camera_frame",
    )
    new_frame = AgentEvent(
        event_type=AgentEventType.CAMERA_FRAME,
        payload={"frame_id": "new"},
        replace_key="camera_frame",
    )

    buffer.put(old_frame)
    buffer.put(new_frame)

    drained = buffer.drain()

    assert drained == [new_frame]
    assert buffer.is_empty() is True


def test_normal_and_replaceable_events_are_drained_together() -> None:
    buffer = EventBuffer()

    user_text = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )
    silence_timeout = AgentEvent(
        event_type=AgentEventType.SILENCE_TIMEOUT,
        payload={},
        replace_key="silence_timeout",
    )

    buffer.put(user_text)
    buffer.put(silence_timeout)

    drained = buffer.drain()

    assert drained == [user_text, silence_timeout]
    assert buffer.is_empty() is True