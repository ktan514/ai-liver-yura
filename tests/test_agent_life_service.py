from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.domain.activities import ActivityStatus
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime import ActivityManager, AgentLifeService
from app.runtime.agent_state import AgentState
from app.utils.trace import TraceLogger


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


def test_idle_timeout_skip_is_debug_only(tmp_path) -> None:
    now = datetime(2026, 7, 14, 11, 0, tzinfo=timezone.utc)
    info_file = tmp_path / "runtime_trace.log"
    debug_file = tmp_path / "runtime_debug.log"
    TraceLogger.configure(
        level="INFO",
        trace_file_path=info_file,
        debug_file_enabled=True,
        debug_file_path=debug_file,
    )
    service = AgentLifeService(
        ActivityManager(),
        initial_state=AgentState(last_user_input_at=now),
        now=now,
        conversation_idle_timeout_seconds=30.0,
    )

    try:
        result = service.plan_next_event(now=now + timedelta(seconds=1))

        assert result is None
        assert not info_file.exists()
        assert "conversation_idle_timeout_not_reached" in debug_file.read_text(
            encoding="utf-8"
        )
    finally:
        TraceLogger.configure(
            level="INFO",
            trace_file_path=tmp_path / "restored.log",
        )


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
    activity_manager.handle_event(AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT))

    agent_state = agent_life_service.sync_from_activity_manager()

    assert len(agent_state.pending_activities) == 1
    assert agent_state.pending_activities[0].status == ActivityStatus.PENDING


def test_agent_life_service_syncs_suspended_activity_from_activity_manager() -> None:
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)

    activity_manager.handle_event(AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT))
    activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    agent_state = agent_life_service.sync_from_activity_manager()

    assert len(agent_state.suspended_activities) == 1
    assert agent_state.suspended_activities[0].status == ActivityStatus.SUSPENDED


def test_agent_life_service_plan_next_event_returns_curiosity_peak_when_internal_drive_is_strong(
) -> None:
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


def test_agent_life_service_plan_next_event_returns_curiosity_peak_after_elapsed_time_updates_drive(
) -> None:
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


def test_agent_life_service_plan_next_event_returns_none_immediately_after_speech_finished() -> (
    None
):
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


def test_autonomous_talk_waits_for_conversation_idle_timeout() -> None:
    activity_manager = ActivityManager()
    user_input_at = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    initial_state = replace(
        AgentState(current_drive=DriveState(curiosity=0.9)),
        last_user_input_at=user_input_at,
    )
    service = AgentLifeService(
        activity_manager,
        initial_state=initial_state,
        now=user_input_at,
        conversation_idle_timeout_seconds=30.0,
    )

    before_timeout = service.plan_next_event(now=user_input_at + timedelta(seconds=29))
    after_timeout = service.plan_next_event(now=user_input_at + timedelta(seconds=30))

    assert before_timeout is None
    assert after_timeout is not None
    assert after_timeout.payload["resume_reason"] == "conversation_idle_timeout"


def test_ongoing_activity_suppresses_autonomous_talk_until_activity_ends() -> None:
    activity_manager = ActivityManager()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    ongoing = activity_manager.start_ongoing_activity(
        activity_type="shiritori",
        goal="しりとりを続ける",
        expected_input="単語",
        end_condition="終了希望",
    )
    service = AgentLifeService(activity_manager, now=now)
    service.update_drive(DriveState(curiosity=0.9))

    while_active = service.plan_next_event(now=now + timedelta(minutes=10))
    activity_manager.end_ongoing_activity(reason="user_requested_end")
    after_end = service.plan_next_event(now=now + timedelta(minutes=10, seconds=1))

    assert while_active is None
    assert after_end is not None
    assert after_end.payload["resume_reason"] == (
        f"ongoing_activity_completed:{ongoing.ongoing_activity_id}"
    )


def test_explicit_conversation_end_allows_autonomous_talk_and_records_reason() -> None:
    activity_manager = ActivityManager()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    initial_state = replace(
        AgentState(current_drive=DriveState(curiosity=0.9)),
        last_user_input_at=now,
    )
    service = AgentLifeService(activity_manager, initial_state=initial_state, now=now)

    service.end_conversation(reason="user_said_goodbye")
    event = service.plan_next_event(now=now + timedelta(seconds=1))

    assert event is not None
    assert event.payload["resume_reason"] == "conversation_ended:user_said_goodbye"


def test_interrupted_important_topic_is_evaluated_and_added_to_event() -> None:
    activity_manager = ActivityManager()
    now = datetime.now(timezone.utc)
    service = AgentLifeService(activity_manager, now=now)
    service.update_drive(DriveState(curiosity=0.9, engagement=0.8))
    service.record_autonomous_output(
        activity_id="autonomous-1",
        text="将来の配信でやってみたいことが三つあって、まず一つ目は……",
        context={
            "topic_metrics": {
                "importance": 0.9,
                "interest": 0.9,
                "incompleteness": 0.95,
            }
        },
    )
    service.interrupt_autonomous_topic(
        activity_id="autonomous-1",
        fallback_text="自律トーク",
        now=now,
    )
    service.handle_event(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "続きも聞きたい"})
    )

    event = service.plan_next_event(now=now + timedelta(seconds=31))

    assert event is not None
    assert event.payload["continuation_decision"] == "resume_original"
    assert event.payload["reintroduction_required"] is True
    assert event.payload["interrupted_topic"].startswith("将来の配信")
    assert "resume_score_high" in event.payload["continuation_reasons"]


def test_agent_life_service_plan_next_event_returns_none_when_emotion_reduces_speech() -> None:
    activity_manager = ActivityManager()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    agent_life_service = AgentLifeService(activity_manager, now=now)
    emotion = EmotionState(talkativeness=0.1)
    drive = DriveState(curiosity=0.9)

    agent_life_service.update_emotion(emotion)
    agent_life_service.update_drive(drive)

    assert agent_life_service.plan_next_event(now=now) is None
