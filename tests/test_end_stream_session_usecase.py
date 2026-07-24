from __future__ import annotations

import pytest

from app.adapters.streaming import InMemoryStreamMainSegmentRepository
from app.adapters.streaming.fake_streaming_control import (
    FakeObsStreamingControlAdapter,
    FakeYouTubeStreamingControlAdapter,
)
from app.adapters.streaming.in_memory_session_repository import (
    InMemoryStreamSessionRepository,
)
from app.domain.activity_turn_result import (
    ActionExecutionResult,
    ActionExecutionStatus,
    ActivityOutputResult,
    ActivityOutputStatus,
    ActivityTurnResult,
)
from app.plugins.youtube_streaming.application import EndStreamSessionUsecase
from app.plugins.youtube_streaming.domain import (
    ApproveNormalStreamEndCommand,
    EmergencyStopStreamCommand,
    RunOfShowSegment,
    StreamEndRejected,
    StreamMainSegmentActivity,
    StreamMainSegmentStatus,
    StreamSession,
    StreamSessionStatus,
)


class Ros:
    def __init__(self, closing: RunOfShowSegment | None = None) -> None:
        self.closing = closing

    def get_closing_segment(self, _id: str) -> RunOfShowSegment | None:
        return self.closing


def closing() -> RunOfShowSegment:
    return RunOfShowSegment(
        "closing", "closing", "締め", 60, True, "llm", "closing-v1", 20, "感謝"
    )


def turn(success: bool = True) -> ActivityTurnResult:
    action = ActionExecutionResult(
        "speak",
        "speak",
        ActionExecutionStatus.COMPLETED if success else ActionExecutionStatus.FAILED,
        "out",
        "turn",
    )
    return ActivityTurnResult(
        "turn",
        "stream_closing_greeting",
        output_result=ActivityOutputResult(
            ActivityOutputStatus.COMPLETED if success else ActivityOutputStatus.FAILED,
            "out",
            "turn",
            action_results=(action,),
            failure_stage=None if success else "tts",
        ),
    )


def fixture(
    closing_segment: RunOfShowSegment | None = None,
) -> tuple[
    EndStreamSessionUsecase,
    InMemoryStreamSessionRepository,
    StreamSession,
    list[str],
    FakeObsStreamingControlAdapter,
    FakeYouTubeStreamingControlAdapter,
]:
    sessions = InMemoryStreamSessionRepository()
    session = sessions.create(
        StreamSession(
            "trace",
            "broadcast",
            "配信",
            selected_stream_id="stream",
            status=StreamSessionStatus.LIVE,
            run_of_show_id="show",
        )
    )
    mains = InMemoryStreamMainSegmentRepository()
    mains.create(
        StreamMainSegmentActivity(
            session.session_id,
            "trace",
            "main",
            10,
            status=StreamMainSegmentStatus.COMPLETED,
        )
    )
    obs = FakeObsStreamingControlAdapter(statuses=["active", "idle"])
    youtube = FakeYouTubeStreamingControlAdapter(
        stream_statuses=["inactive"], broadcast_statuses=["live", "complete"]
    )
    events: list[str] = []

    async def execute(_payload: dict[str, object], _trace: str) -> ActivityTurnResult:
        return turn()

    usecase = EndStreamSessionUsecase(
        sessions=sessions,
        main_segments=mains,
        run_of_show=Ros(closing_segment),  # type: ignore[arg-type]
        obs=obs,
        youtube=youtube,
        closing_executor=execute,
        output_canceler=lambda: True,
        event_publisher=lambda event, _data, _trace: events.append(event),
        test_mode=True,
    )
    return usecase, sessions, session, events, obs, youtube


@pytest.mark.asyncio
async def test_normal_end_runs_closing_then_stops_external_services() -> None:
    usecase, sessions, session, events, obs, youtube = fixture(closing())
    command = ApproveNormalStreamEndCommand(
        "end", "end-trace", session.session_id, 0, "operator"
    )
    result = await usecase.normal(command)
    assert result.successful and result.end_mode == "normal"
    assert sessions.get(session.session_id).status == StreamSessionStatus.COMPLETED  # type: ignore[union-attr]
    assert obs.stop_calls == 1 and youtube.complete_calls == 1
    assert events == [
        "stream_end.approved",
        "stream_closing.started",
        "stream_closing.output_started",
        "stream_closing.completed",
        "stream_end.stopping",
        "stream_end.broadcast_complete",
        "stream_end.obs_idle",
        "stream_end.completed",
    ]
    assert await usecase.normal(command) == result


@pytest.mark.asyncio
async def test_emergency_skips_closing_and_cancels_output() -> None:
    usecase, sessions, session, events, obs, youtube = fixture(closing())
    command = EmergencyStopStreamCommand(
        "emergency", "trace-e", session.session_id, 0, "operator", "danger"
    )
    result = await usecase.emergency(command)
    assert result.successful and result.end_mode == "emergency"
    assert sessions.get(session.session_id).status == StreamSessionStatus.EMERGENCY_STOPPED  # type: ignore[union-attr]
    assert "stream_closing.started" not in events
    assert "stream_emergency_stop.output_cancel_requested" in events
    assert obs.stop_calls == 1 and youtube.complete_calls == 1


@pytest.mark.asyncio
async def test_missing_closing_fails_but_keeps_external_stream_live() -> None:
    usecase, sessions, session, _events, obs, youtube = fixture(None)
    result = await usecase.normal(
        ApproveNormalStreamEndCommand("end", "trace", session.session_id, 0, "operator")
    )
    assert not result.successful and result.failed_step == "closing"
    assert sessions.get(session.session_id).status == StreamSessionStatus.STOP_FAILED  # type: ignore[union-attr]
    assert obs.stop_calls == 0 and youtube.complete_calls == 0


@pytest.mark.asyncio
async def test_version_and_main_completion_are_required() -> None:
    usecase, _sessions, session, _events, _obs, _youtube = fixture(closing())
    with pytest.raises(StreamEndRejected, match="version_mismatch"):
        await usecase.normal(
            ApproveNormalStreamEndCommand(
                "end", "trace", session.session_id, 9, "operator"
            )
        )


def test_end_state_machine_rejects_invalid_transition() -> None:
    session = StreamSession("trace", "broadcast", "title")
    with pytest.raises(ValueError):
        session.transition(StreamSessionStatus.COMPLETED)
