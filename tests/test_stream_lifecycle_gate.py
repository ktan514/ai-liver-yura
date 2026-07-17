from __future__ import annotations

import pytest

from app.adapters.streaming import (
    InMemoryStreamMainSegmentRepository,
    InMemoryStreamOpeningRepository,
)
from app.adapters.streaming.in_memory_session_repository import InMemoryStreamSessionRepository
from app.domain.streaming import (
    LifecycleOperation,
    StreamLifecycleClass,
    StreamOpeningActivity,
    StreamOpeningStatus,
    StreamSession,
    StreamSessionStatus,
    classify_lifecycle,
)
from app.usecases import StreamLifecycleGate

ACTIVE = {
    "obs_output": "active",
    "youtube_stream": "active",
    "youtube_broadcast": "live",
    "stream_session": "live",
}


def gate(
    status: StreamSessionStatus = StreamSessionStatus.LIVE,
) -> tuple[
    StreamLifecycleGate,
    StreamSession,
    InMemoryStreamSessionRepository,
    InMemoryStreamOpeningRepository,
    list[str],
]:
    sessions = InMemoryStreamSessionRepository()
    session = sessions.create(StreamSession("trace", "broadcast", "title", status=status))
    openings = InMemoryStreamOpeningRepository()
    events: list[str] = []
    lifecycle = StreamLifecycleGate(
        sessions=sessions,
        openings=openings,
        main_segments=InMemoryStreamMainSegmentRepository(),
        publisher=lambda event, _data, _trace: events.append(event),
    )
    return lifecycle, session, sessions, openings, events


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (StreamSessionStatus.READY, StreamLifecycleClass.PRE_LIVE),
        (StreamSessionStatus.LIVE, StreamLifecycleClass.LIVE_ACTIVE),
        (StreamSessionStatus.CLOSING, StreamLifecycleClass.NORMAL_ENDING),
        (StreamSessionStatus.EMERGENCY_STOPPING, StreamLifecycleClass.EMERGENCY_ENDING),
        (StreamSessionStatus.COMPLETED, StreamLifecycleClass.TERMINAL),
        (StreamSessionStatus.STOP_FAILED, StreamLifecycleClass.FAILED),
    ],
)
def test_lifecycle_classification(
    status: StreamSessionStatus, category: StreamLifecycleClass
) -> None:
    assert classify_lifecycle(status) == category


def test_live_external_policy_and_opening_dependency() -> None:
    lifecycle, session, _sessions, openings, _events = gate()
    unknown = lifecycle.evaluate(LifecycleOperation.START_MAIN_SEGMENT, session.session_id)
    assert not unknown.allowed and unknown.reason_code == "lifecycle.opening_not_completed"
    openings.create(
        StreamOpeningActivity(
            session.session_id,
            "trace",
            "opening",
            status=StreamOpeningStatus.COMPLETED,
        )
    )
    still_unknown = lifecycle.evaluate(LifecycleOperation.START_MAIN_SEGMENT, session.session_id)
    assert still_unknown.reason_code == "lifecycle.external_state_unknown"
    lifecycle.update_external_state(session.session_id, ACTIVE)
    assert lifecycle.evaluate(LifecycleOperation.START_MAIN_SEGMENT, session.session_id).allowed
    lifecycle.update_external_state(session.session_id, {**ACTIVE, "obs_output": "idle"})
    mismatch = lifecycle.evaluate(LifecycleOperation.CONTINUE_COMMENT_POLLING, session.session_id)
    assert mismatch.reason_code == "lifecycle.external_state_mismatch"


@pytest.mark.parametrize(
    "status",
    [
        StreamSessionStatus.LIVE,
        StreamSessionStatus.CLOSING_REQUESTED,
        StreamSessionStatus.CLOSING,
        StreamSessionStatus.STOPPING,
        StreamSessionStatus.STOP_FAILED,
    ],
)
def test_emergency_is_allowed_across_end_states(status: StreamSessionStatus) -> None:
    lifecycle, session, _sessions, _openings, _events = gate(status)
    assert lifecycle.evaluate(LifecycleOperation.START_EMERGENCY_STOP, session.session_id).allowed


def test_closing_allows_only_closing_output_and_terminal_blocks_actions() -> None:
    lifecycle, session, sessions, _openings, _events = gate(StreamSessionStatus.CLOSING)
    assert lifecycle.evaluate(
        LifecycleOperation.ENQUEUE_ACTION,
        session.session_id,
        activity_type="stream_closing_greeting",
    ).allowed
    blocked = lifecycle.evaluate(
        LifecycleOperation.ENQUEUE_ACTION,
        session.session_id,
        activity_type="stream_main_segment",
    )
    assert blocked.reason_code == "lifecycle.ending"
    terminal = sessions.save(session.transition(StreamSessionStatus.STOPPING))
    terminal = sessions.save(terminal.transition(StreamSessionStatus.COMPLETED))
    assert (
        lifecycle.evaluate(LifecycleOperation.ENQUEUE_ACTION, terminal.session_id).reason_code
        == "lifecycle.terminal"
    )


def test_duplicate_notifications_are_suppressed_and_snapshot_lists_operations() -> None:
    lifecycle, session, _sessions, _openings, events = gate()
    lifecycle.evaluate(LifecycleOperation.START_COMMENT_POLLING, session.session_id)
    first_count = len(events)
    lifecycle.evaluate(LifecycleOperation.START_COMMENT_POLLING, session.session_id)
    assert len(events) == first_count
    snapshot = lifecycle.snapshot(session.session_id)
    assert snapshot["lifecycle_class"] == "live_active"
    assert "start_emergency_stop" in snapshot["operations"]  # type: ignore[operator]


def test_version_and_stale_session_are_rejected() -> None:
    lifecycle, session, _sessions, _openings, _events = gate()
    decision = lifecycle.evaluate(
        LifecycleOperation.START_NORMAL_END,
        session.session_id,
        expected_version=99,
    )
    assert decision.reason_code == "lifecycle.version_mismatch"
    stale = lifecycle.evaluate(LifecycleOperation.START_NORMAL_END, "missing")
    assert stale.reason_code == "lifecycle.stale_session"
