from datetime import datetime, timezone

from app.domain.drives import DriveState
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.drive_state_updater import DriveStateUpdater


def test_update_by_user_text_increases_engagement_and_curiosity() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.4, engagement=0.4, boredom=0.5, energy=0.8)
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"}
    )

    updated_drive = updater.update_by_event(drive, event)

    assert updated_drive.curiosity > drive.curiosity
    assert updated_drive.engagement > drive.engagement
    assert updated_drive.boredom < drive.boredom
    assert updated_drive.energy < drive.energy


def test_update_by_youtube_comment_increases_engagement_and_curiosity() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.4, engagement=0.4, boredom=0.5, energy=0.8)
    event = AgentEvent(
        event_type=AgentEventType.YOUTUBE_COMMENT,
        payload={"comment": "初見です"},
    )

    updated_drive = updater.update_by_event(drive, event)

    assert updated_drive.curiosity > drive.curiosity
    assert updated_drive.engagement > drive.engagement
    assert updated_drive.boredom < drive.boredom
    assert updated_drive.energy < drive.energy


# New tests for app and stream started events
def test_update_by_app_started_increases_startup_drive() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.4, engagement=0.4, boredom=0.2, energy=0.7)
    event = AgentEvent(event_type=AgentEventType.APP_STARTED)

    updated_drive = updater.update_by_event(drive, event)

    assert updated_drive.curiosity > drive.curiosity
    assert updated_drive.engagement > drive.engagement
    assert updated_drive.boredom > drive.boredom
    assert updated_drive.energy > drive.energy


def test_update_by_stream_started_increases_engagement_more_than_app_started() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.4, engagement=0.4, boredom=0.2, energy=0.7)
    app_started = AgentEvent(event_type=AgentEventType.APP_STARTED)
    stream_started = AgentEvent(event_type=AgentEventType.STREAM_STARTED)

    updated_by_app_started = updater.update_by_event(drive, app_started)
    updated_by_stream_started = updater.update_by_event(drive, stream_started)

    assert updated_by_stream_started.curiosity > updated_by_app_started.curiosity
    assert updated_by_stream_started.engagement > updated_by_app_started.engagement
    assert updated_by_stream_started.energy > updated_by_app_started.energy


def test_update_by_speech_finished_reduces_curiosity_and_boredom() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.8, engagement=0.5, boredom=0.6, energy=0.8)
    event = AgentEvent(event_type=AgentEventType.SPEECH_FINISHED)

    updated_drive = updater.update_by_event(drive, event)

    assert updated_drive.curiosity < drive.curiosity
    assert updated_drive.engagement > drive.engagement
    assert updated_drive.boredom < drive.boredom
    assert updated_drive.energy < drive.energy


def test_update_by_action_failed_increases_boredom_and_reduces_engagement() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.5, engagement=0.5, boredom=0.2, energy=0.8)
    event = AgentEvent(event_type=AgentEventType.ACTION_FAILED)

    updated_drive = updater.update_by_event(drive, event)

    assert updated_drive.curiosity > drive.curiosity
    assert updated_drive.engagement < drive.engagement
    assert updated_drive.boredom > drive.boredom
    assert updated_drive.energy < drive.energy


def test_update_by_unknown_event_returns_same_drive() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.5, engagement=0.5, boredom=0.2, energy=0.8)
    event = AgentEvent(event_type=AgentEventType.CAMERA_FRAME)

    updated_drive = updater.update_by_event(drive, event)

    assert updated_drive == drive


def test_update_by_elapsed_time_increases_boredom_and_curiosity() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.4, engagement=0.6, boredom=0.2, energy=0.8)

    updated_drive = updater.update_by_elapsed_time(drive, elapsed_seconds=120.0)

    assert updated_drive.curiosity > drive.curiosity
    assert updated_drive.engagement < drive.engagement
    assert updated_drive.boredom > drive.boredom
    assert updated_drive.energy < drive.energy


def test_update_by_elapsed_time_ignores_negative_elapsed_seconds() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.4, engagement=0.6, boredom=0.2, energy=0.8)

    updated_drive = updater.update_by_elapsed_time(drive, elapsed_seconds=-60.0)

    assert updated_drive == drive


def test_update_by_timestamps_uses_elapsed_seconds() -> None:
    updater = DriveStateUpdater()
    drive = DriveState(curiosity=0.4, engagement=0.6, boredom=0.2, energy=0.8)
    previous_time = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    current_time = datetime(2026, 7, 5, 12, 2, 0, tzinfo=timezone.utc)

    updated_drive = updater.update_by_timestamps(
        drive,
        previous_time=previous_time,
        current_time=current_time,
    )

    assert updated_drive.curiosity > drive.curiosity
    assert updated_drive.engagement < drive.engagement
    assert updated_drive.boredom > drive.boredom
    assert updated_drive.energy < drive.energy
