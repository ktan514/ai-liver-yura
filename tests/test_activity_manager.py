from __future__ import annotations

from app.domain.activities import ActivityStatus, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager


def test_user_text_becomes_foreground_activity() -> None:
    manager = ActivityManager()

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは"},
            priority=50,
        )
    )

    assert foreground.activity_type == ActivityType.CONVERSATION_WITH_USER
    assert foreground.status == ActivityStatus.ACTIVE
    assert manager.foreground_activity == foreground
    assert manager.pending_activities() == []
    assert manager.suspended_activities() == []


def test_app_started_becomes_startup_reaction_activity() -> None:
    manager = ActivityManager()

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.APP_STARTED,
            payload={"source": "test"},
            priority=20,
        )
    )

    assert foreground.activity_type == ActivityType.STARTUP_REACTION
    assert foreground.status == ActivityStatus.ACTIVE
    assert foreground.interruptible is False
    assert manager.foreground_activity == foreground


def test_stream_started_becomes_opening_greeting_activity() -> None:
    manager = ActivityManager()

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.STREAM_STARTED,
            payload={"source": "test"},
            priority=20,
        )
    )

    assert foreground.activity_type == ActivityType.STREAM_OPENING_GREETING
    assert foreground.status == ActivityStatus.ACTIVE
    assert foreground.interruptible is False
    assert manager.foreground_activity == foreground


def test_stream_ending_becomes_closing_greeting_activity() -> None:
    manager = ActivityManager()

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.STREAM_ENDING,
            payload={"source": "test"},
            priority=20,
        )
    )

    assert foreground.activity_type == ActivityType.STREAM_CLOSING_GREETING
    assert foreground.status == ActivityStatus.ACTIVE
    assert foreground.interruptible is False
    assert manager.foreground_activity == foreground


def test_user_text_interrupts_curiosity_peak_autonomous_talk() -> None:
    manager = ActivityManager()

    autonomous = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload={},
            priority=8,
        )
    )

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "話しかける"},
            priority=50,
        )
    )

    suspended = manager.suspended_activities()

    assert autonomous.activity_type == ActivityType.AUTONOMOUS_TALK
    assert foreground.activity_type == ActivityType.CONVERSATION_WITH_USER
    assert foreground.status == ActivityStatus.ACTIVE
    assert manager.foreground_activity == foreground
    assert len(suspended) == 1
    assert suspended[0].activity_type == ActivityType.AUTONOMOUS_TALK
    assert suspended[0].status == ActivityStatus.SUSPENDED


def test_conversation_is_not_interrupted_by_silence_timeout_observation() -> None:
    manager = ActivityManager()

    conversation = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは"},
            priority=50,
        )
    )

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.SILENCE_TIMEOUT,
            payload={},
            priority=8,
        )
    )

    pending = manager.pending_activities()

    assert foreground.activity_type == ActivityType.IDLE_OBSERVATION
    assert foreground.status == ActivityStatus.PENDING
    assert manager.foreground_activity == conversation
    assert len(pending) == 1
    assert pending[0] == foreground
    assert pending[0].activity_type == ActivityType.IDLE_OBSERVATION
    assert pending[0].status == ActivityStatus.PENDING


def test_lower_priority_activity_becomes_pending() -> None:
    manager = ActivityManager()

    autonomous = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload={},
            priority=30,
        )
    )

    lower_priority_observation = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.CAMERA_FRAME,
            payload={"frame_id": "dummy"},
            priority=3,
        )
    )

    pending = manager.pending_activities()

    assert lower_priority_observation.activity_type == ActivityType.IDLE_OBSERVATION
    assert lower_priority_observation.status == ActivityStatus.PENDING
    assert manager.foreground_activity == autonomous
    assert len(pending) == 1
    assert pending[0] == lower_priority_observation
    assert pending[0].activity_type == ActivityType.IDLE_OBSERVATION
    assert pending[0].status == ActivityStatus.PENDING


def test_complete_activity_marks_activity_completed() -> None:
    manager = ActivityManager()

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは"},
            priority=50,
        )
    )

    completed = manager.complete_activity(foreground.activity_id)

    assert completed is not None
    assert completed.activity_id == foreground.activity_id
    assert completed.status == ActivityStatus.COMPLETED
    assert manager.foreground_activity is None


def test_complete_foreground_activity_resumes_pending_activity() -> None:
    manager = ActivityManager()

    conversation = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは"},
            priority=50,
        )
    )

    pending_autonomous = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload={},
            priority=8,
        )
    )

    completed = manager.complete_foreground_activity()

    assert completed is not None
    assert completed.activity_id == conversation.activity_id
    assert completed.status == ActivityStatus.COMPLETED
    assert manager.foreground_activity is not None
    assert manager.foreground_activity.activity_id == pending_autonomous.activity_id
    assert manager.foreground_activity.status == ActivityStatus.ACTIVE
    assert manager.pending_activities() == []


def test_complete_foreground_activity_without_pending_clears_foreground() -> None:
    manager = ActivityManager()

    foreground = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは"},
            priority=50,
        )
    )

    completed = manager.complete_foreground_activity()

    assert completed is not None
    assert completed.activity_id == foreground.activity_id
    assert completed.status == ActivityStatus.COMPLETED
    assert manager.foreground_activity is None


def test_resume_next_pending_selects_highest_priority_activity() -> None:
    manager = ActivityManager()

    conversation = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは"},
            priority=50,
        )
    )

    low_priority_pending = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.CAMERA_FRAME,
            payload={"frame_id": "dummy"},
            priority=3,
        )
    )

    high_priority_pending = manager.handle_event(
        AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload={},
            priority=8,
        )
    )

    completed = manager.complete_activity(conversation.activity_id)
    resumed = manager.resume_next_pending()

    assert completed is not None
    assert resumed is not None
    assert resumed.activity_id == high_priority_pending.activity_id
    assert resumed.status == ActivityStatus.ACTIVE
    assert manager.foreground_activity == resumed
    assert low_priority_pending in manager.pending_activities()