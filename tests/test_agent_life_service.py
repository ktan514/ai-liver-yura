from datetime import datetime, timezone

from app.domain.activities import ActivityStatus
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import ActivityManager, AgentLifeService


def test_agent_life_service_has_default_agent_state() -> None:
    activity_manager = ActivityManager()

    agent_life_service = AgentLifeService(activity_manager)

    assert agent_life_service.agent_state.stream_status == "idle"
    assert agent_life_service.agent_state.active_activity is None


def test_agent_life_service_marks_user_input_received() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    agent_state = agent_life_service.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    assert agent_state.last_user_input_at is not None


def test_agent_life_service_marks_youtube_comment_as_user_input() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    agent_state = agent_life_service.handle_event(
        AgentEvent(
            event_type=AgentEventType.YOUTUBE_COMMENT,
            payload={"comment": "初見です"},
        )
    )

    assert agent_state.last_user_input_at is not None


def test_agent_life_service_marks_speech_started() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    agent_state = agent_life_service.handle_event(
        AgentEvent(event_type=AgentEventType.SPEECH_STARTED)
    )

    assert agent_state.last_speech_started_at is not None


def test_agent_life_service_marks_speech_finished() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    agent_state = agent_life_service.handle_event(
        AgentEvent(event_type=AgentEventType.SPEECH_FINISHED)
    )

    assert agent_state.last_speech_finished_at is not None


def test_agent_life_service_updates_drive_by_speech_finished_event() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    agent_life_service.update_drive(
        DriveState(curiosity=0.8, engagement=0.5, boredom=0.6, energy=0.8)
    )
    before_drive = agent_life_service.agent_state.current_drive

    agent_state = agent_life_service.handle_event(
        AgentEvent(event_type=AgentEventType.SPEECH_FINISHED)
    )

    assert agent_state.current_drive.curiosity < before_drive.curiosity
    assert agent_state.current_drive.engagement > before_drive.engagement
    assert agent_state.current_drive.boredom < before_drive.boredom
    assert agent_state.current_drive.energy < before_drive.energy


def test_agent_life_service_updates_emotion() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    emotion = EmotionState(mood=MoodType.EXCITED, talkativeness=0.9)

    agent_state = agent_life_service.update_emotion(emotion)

    assert agent_state.current_emotion == emotion


def test_agent_life_service_updates_drive_by_user_input_event() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    before_drive = agent_life_service.agent_state.current_drive

    agent_state = agent_life_service.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    assert agent_state.current_drive.curiosity > before_drive.curiosity
    assert agent_state.current_drive.engagement > before_drive.engagement
    assert agent_state.current_drive.boredom <= before_drive.boredom
    assert agent_state.current_drive.energy < before_drive.energy


def test_agent_life_service_syncs_active_activity_from_activity_manager() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    agent_state = agent_life_service.sync_from_activity_manager()

    assert agent_state.active_activity is not None
    assert agent_state.active_activity.status == ActivityStatus.ACTIVE


def test_agent_life_service_syncs_pending_activity_from_activity_manager() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )
    activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT)
    )

    agent_state = agent_life_service.sync_from_activity_manager()

    assert len(agent_state.pending_activities) == 1
    assert agent_state.pending_activities[0].status == ActivityStatus.PENDING


def test_agent_life_service_syncs_suspended_activity_from_activity_manager() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT)
    )
    activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    agent_state = agent_life_service.sync_from_activity_manager()

    assert len(agent_state.suspended_activities) == 1
    assert agent_state.suspended_activities[0].status == ActivityStatus.SUSPENDED


def test_agent_life_service_plan_next_event_returns_curiosity_peak_when_internal_drive_is_strong() -> None:
    activity_manager = ActivityManager()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    agent_life_service = AgentLifeService(activity_manager, now=now)
    agent_life_service.update_drive(DriveState(curiosity=0.9))

    event = agent_life_service.plan_next_event(now=now)

    assert event is not None
    assert event.event_type == AgentEventType.CURIOSITY_PEAK
    assert event.payload == {"reason": "internal_drive", "drive": "curiosity"}
    assert event.discardable is True
    assert event.replace_key == "agent_life_service:curiosity_peak"


def test_agent_life_service_plan_next_event_returns_none_when_internal_drive_is_weak() -> None:
    activity_manager = ActivityManager()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    agent_life_service = AgentLifeService(activity_manager, now=now)

    assert agent_life_service.plan_next_event(now=now) is None


def test_agent_life_service_plan_next_event_returns_curiosity_peak_after_elapsed_time_updates_drive() -> None:
    activity_manager = ActivityManager()
    initial_time = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    agent_life_service = AgentLifeService(activity_manager, now=initial_time)
    later_time = datetime(2026, 7, 5, 12, 7, 0, tzinfo=timezone.utc)

    event = agent_life_service.plan_next_event(now=later_time)

    assert event is not None
    assert event.event_type == AgentEventType.CURIOSITY_PEAK
    assert event.payload["reason"] == "internal_drive"


def test_agent_life_service_plan_next_event_returns_none_when_active_activity_exists() -> None:
    activity_manager = ActivityManager()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    agent_life_service = AgentLifeService(activity_manager, now=now)
    agent_life_service.update_drive(DriveState(curiosity=0.9))

    activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    assert agent_life_service.plan_next_event(now=now) is None


def test_agent_life_service_plan_next_event_returns_none_immediately_after_speech_finished() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    agent_life_service.update_drive(DriveState(curiosity=0.9))

    agent_life_service.handle_event(AgentEvent(event_type=AgentEventType.SPEECH_FINISHED))
    now = datetime.now(timezone.utc)

    assert agent_life_service.plan_next_event(now=now) is None


def test_agent_life_service_plan_next_event_returns_none_immediately_after_user_input() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    agent_life_service.update_drive(DriveState(curiosity=0.9))

    agent_life_service.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )
    now = datetime.now(timezone.utc)

    assert agent_life_service.plan_next_event(now=now) is None


def test_agent_life_service_plan_next_event_returns_none_when_emotion_reduces_speech() -> None:
    activity_manager = ActivityManager()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    agent_life_service = AgentLifeService(activity_manager, now=now)
    emotion = EmotionState(talkativeness=0.1)
    drive = DriveState(curiosity=0.9)

    agent_life_service.update_emotion(emotion)
    agent_life_service.update_drive(drive)

    assert agent_life_service.plan_next_event(now=now) is None