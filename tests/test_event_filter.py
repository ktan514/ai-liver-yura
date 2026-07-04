

from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_filter import DefaultEventFilter


def test_user_text_is_not_discardable() -> None:
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )

    filtered = DefaultEventFilter().filter(event)

    assert filtered is not None
    assert filtered.event_type == AgentEventType.USER_TEXT
    assert filtered.discardable is False
    assert filtered.replace_key is None


def test_camera_frame_is_discardable_and_replaceable() -> None:
    event = AgentEvent(
        event_type=AgentEventType.CAMERA_FRAME,
        payload={"frame_id": "dummy"},
    )

    filtered = DefaultEventFilter().filter(event)

    assert filtered is not None
    assert filtered.event_type == AgentEventType.CAMERA_FRAME
    assert filtered.discardable is True
    assert filtered.replace_key == "camera_frame"


def test_silence_timeout_is_discardable_and_replaceable() -> None:
    event = AgentEvent(
        event_type=AgentEventType.SILENCE_TIMEOUT,
        payload={},
    )

    filtered = DefaultEventFilter().filter(event)

    assert filtered is not None
    assert filtered.event_type == AgentEventType.SILENCE_TIMEOUT
    assert filtered.discardable is True
    assert filtered.replace_key == "silence_timeout"