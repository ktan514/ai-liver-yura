from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.adapters.streaming import InMemoryStreamOpeningRepository
from app.adapters.streaming.in_memory_session_repository import InMemoryStreamSessionRepository
from app.domain.activity_turn_result import (
    ActionExecutionResult,
    ActionExecutionStatus,
    ActivityOutputResult,
    ActivityOutputStatus,
    ActivityTurnResult,
)
from app.domain.streaming import (
    RetryOpeningCommand,
    RunOfShowSegment,
    StreamOpeningRejected,
    StreamOpeningStatus,
    StreamReadiness,
    StreamSession,
    StreamSessionStatus,
    StreamStartResult,
)
from app.usecases import StreamOpeningUsecase


class RunOfShow:
    def __init__(self, segment: RunOfShowSegment | None = None) -> None:
        self.segment = segment

    def get_opening_segment(self, _run_of_show_id: str) -> RunOfShowSegment | None:
        return self.segment


def live_session(sessions: InMemoryStreamSessionRepository) -> StreamSession:
    session = StreamSession(
        trace_id="trace",
        selected_broadcast_id="broadcast",
        title="テスト配信",
        status=StreamSessionStatus.LIVE,
        readiness=StreamReadiness.UNKNOWN,
        run_of_show_id="show",
    )
    return sessions.create(session)


def start_result(session_id: str, **updates: object) -> StreamStartResult:
    values: dict[str, object] = {
        "session_id": session_id,
        "trace_id": "trace",
        "command_id": "start",
        "status": "completed",
        "successful": True,
        "failed_step": None,
        "obs_status": "active",
        "youtube_stream_status": "active",
        "youtube_broadcast_status": "live",
        "failure_code": None,
        "manual_intervention_required": False,
        "started_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
    }
    values.update(updates)
    return StreamStartResult(**values)  # type: ignore[arg-type]


def segment() -> RunOfShowSegment:
    return RunOfShowSegment("opening", "opening", "開始挨拶", 60, True, "llm", "v1")


def turn(status: ActionExecutionStatus = ActionExecutionStatus.COMPLETED) -> ActivityTurnResult:
    action = ActionExecutionResult("speak-1", "speak", status, "output", "turn")
    output_status = (
        ActivityOutputStatus.COMPLETED
        if status == ActionExecutionStatus.COMPLETED
        else ActivityOutputStatus.FAILED
    )
    return ActivityTurnResult(
        "turn",
        "stream_opening_greeting",
        output_result=ActivityOutputResult(
            output_status,
            "output",
            "turn",
            action_results=(action,),
            failure_stage=None if status == ActionExecutionStatus.COMPLETED else "tts",
        ),
    )


@pytest.mark.asyncio
async def test_live_verified_session_runs_once_and_emits_ordered_events() -> None:
    sessions = InMemoryStreamSessionRepository()
    session = live_session(sessions)
    events: list[str] = []

    async def execute(payload: dict[str, object], trace_id: str) -> ActivityTurnResult:
        assert payload["verified_stream_state"] == {
            "obs_output": "active",
            "youtube_stream": "active",
            "youtube_broadcast": "live",
            "stream_session": "live",
        }
        assert trace_id == "trace"
        return turn()

    usecase = StreamOpeningUsecase(
        sessions=sessions,
        openings=InMemoryStreamOpeningRepository(),
        run_of_show=RunOfShow(segment()),  # type: ignore[arg-type]
        executor=execute,
        event_publisher=lambda event, _data, _trace: events.append(event),
    )
    result = await usecase.start(
        session.session_id,
        start_result(session.session_id),
        adapter_types=("fake", "fake"),
        test_mode=True,
    )

    assert result.status == StreamOpeningStatus.COMPLETED
    assert result.attempt == 1
    assert sessions.get(session.session_id).opening_activity_id == result.activity_id  # type: ignore[union-attr]
    assert events == [
        "stream_opening.started",
        "stream_opening.segment_started",
        "stream_opening.generation_started",
        "stream_opening.output_started",
        "stream_opening.speech_started",
        "stream_opening.completed",
    ]
    with pytest.raises(StreamOpeningRejected, match="opening.session.duplicate"):
        await usecase.start(
            session.session_id,
            start_result(session.session_id),
            adapter_types=("fake", "fake"),
            test_mode=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"obs_status": "inactive"}, "opening.stream_state.unverified"),
        ({"youtube_stream_status": "ready"}, "opening.stream_state.unverified"),
        ({"youtube_broadcast_status": "testing"}, "opening.stream_state.unverified"),
    ],
)
async def test_unverified_external_state_is_rejected(update: dict[str, object], code: str) -> None:
    sessions = InMemoryStreamSessionRepository()
    session = live_session(sessions)
    usecase = StreamOpeningUsecase(
        sessions=sessions,
        openings=InMemoryStreamOpeningRepository(),
        run_of_show=RunOfShow(segment()),  # type: ignore[arg-type]
        executor=lambda _payload, _trace: turn(),  # type: ignore[arg-type,return-value]
    )
    with pytest.raises(StreamOpeningRejected, match=code):
        await usecase.start(
            session.session_id,
            start_result(session.session_id, **update),
            adapter_types=("real", "real"),
        )


@pytest.mark.asyncio
async def test_tts_failure_keeps_session_live_and_retry_is_idempotent() -> None:
    sessions = InMemoryStreamSessionRepository()
    session = live_session(sessions)
    calls = 0

    async def execute(_payload: dict[str, object], _trace: str) -> ActivityTurnResult:
        nonlocal calls
        calls += 1
        return turn(ActionExecutionStatus.FAILED if calls == 1 else ActionExecutionStatus.COMPLETED)

    usecase = StreamOpeningUsecase(
        sessions=sessions,
        openings=InMemoryStreamOpeningRepository(),
        run_of_show=RunOfShow(segment()),  # type: ignore[arg-type]
        executor=execute,
    )
    failed = await usecase.start(
        session.session_id,
        start_result(session.session_id),
        adapter_types=("real", "real"),
    )
    assert failed.status == StreamOpeningStatus.FAILED
    assert failed.manual_intervention_required
    assert sessions.get(session.session_id).status == StreamSessionStatus.LIVE  # type: ignore[union-attr]

    command = RetryOpeningCommand("retry", session.session_id, failed.version)
    completed = await usecase.retry(command)
    duplicate = await usecase.retry(command)
    assert completed.status == StreamOpeningStatus.COMPLETED
    assert duplicate == completed
    assert calls == 2


@pytest.mark.asyncio
async def test_missing_required_segment_fails_without_generating_greeting() -> None:
    sessions = InMemoryStreamSessionRepository()
    session = live_session(sessions)
    called = False

    async def execute(_payload: dict[str, object], _trace: str) -> ActivityTurnResult:
        nonlocal called
        called = True
        return turn()

    usecase = StreamOpeningUsecase(
        sessions=sessions,
        openings=InMemoryStreamOpeningRepository(),
        run_of_show=RunOfShow(),  # type: ignore[arg-type]
        executor=execute,
    )
    result = await usecase.start(
        session.session_id,
        start_result(session.session_id),
        adapter_types=("real", "real"),
    )
    assert result.status == StreamOpeningStatus.FAILED
    assert result.failure_code == "opening.segment.required_missing"
    assert not called


def test_opening_activity_rejects_invalid_transition() -> None:
    from app.domain.streaming import StreamOpeningActivity

    activity = StreamOpeningActivity("session", "trace", "opening")
    with pytest.raises(ValueError, match="invalid opening transition"):
        activity.transition(StreamOpeningStatus.COMPLETED)
