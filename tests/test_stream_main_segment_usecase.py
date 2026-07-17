from __future__ import annotations

import pytest

from app.adapters.streaming import InMemoryStreamMainSegmentRepository
from app.adapters.streaming.in_memory_session_repository import InMemoryStreamSessionRepository
from app.domain.actions import ActionType
from app.domain.activity_turn_result import (
    ActionExecutionResult,
    ActionExecutionStatus,
    ActivityOutputResult,
    ActivityOutputStatus,
    ActivityTurnResult,
)
from app.domain.streaming import (
    RetryMainSegmentCommand,
    RunOfShowSegment,
    StreamMainSegmentRejected,
    StreamMainSegmentStatus,
    StreamOpeningActivity,
    StreamOpeningStatus,
    StreamSession,
    StreamSessionStatus,
)
from app.usecases import StreamMainSegmentUsecase

STATE = {
    "obs_output": "active",
    "youtube_stream": "active",
    "youtube_broadcast": "live",
    "stream_session": "live",
}


class Ros:
    def __init__(self, segments: list[RunOfShowSegment]) -> None:
        self.segments = segments

    def get_first_main_segment(self, _id: str) -> RunOfShowSegment | None:
        items = sorted(
            (item for item in self.segments if item.segment_type == "main"),
            key=lambda item: item.order,
        )
        return items[0] if items else None


def setup() -> tuple[InMemoryStreamSessionRepository, StreamSession, StreamOpeningActivity]:
    sessions = InMemoryStreamSessionRepository()
    session = sessions.create(
        StreamSession(
            "trace", "broadcast", "配信", status=StreamSessionStatus.LIVE, run_of_show_id="show"
        )
    )
    opening = StreamOpeningActivity(
        session.session_id,
        "trace",
        "opening",
        status=StreamOpeningStatus.COMPLETED,
        result={"summary": "開始挨拶完了"},
    )
    return sessions, session, opening


def main(order: int = 10, topic: str | None = "今日の話題") -> RunOfShowSegment:
    return RunOfShowSegment(
        f"main-{order}", "main", "本編", 600, True, "llm", "main-v1", order, "紹介", topic
    )


def turn(status: ActionExecutionStatus = ActionExecutionStatus.COMPLETED) -> ActivityTurnResult:
    action = ActionExecutionResult("action", ActionType.SPEAK.value, status, "out", "turn")
    return ActivityTurnResult(
        "turn",
        "stream_main_segment",
        output_result=ActivityOutputResult(
            ActivityOutputStatus.COMPLETED
            if status == ActionExecutionStatus.COMPLETED
            else ActivityOutputStatus.FAILED,
            "out",
            "turn",
            action_results=(action,),
            failure_stage="tts" if status == ActionExecutionStatus.FAILED else None,
        ),
    )


@pytest.mark.asyncio
async def test_completed_opening_runs_first_ordered_main_and_events() -> None:
    sessions, session, opening = setup()
    events: list[str] = []
    payloads: list[dict[str, object]] = []

    async def execute(payload: dict[str, object], _trace: str) -> ActivityTurnResult:
        payloads.append(payload)
        return turn()

    usecase = StreamMainSegmentUsecase(
        sessions=sessions,
        activities=InMemoryStreamMainSegmentRepository(),
        run_of_show=Ros([main(20), main(10)]),  # type: ignore[arg-type]
        executor=execute,
        event_publisher=lambda event, _data, _trace: events.append(event),
    )
    result = await usecase.start(opening, STATE)
    assert result.status == StreamMainSegmentStatus.COMPLETED
    assert result.segment_id == "main-10"
    assert payloads[0]["current_topic"] == "今日の話題"
    assert sessions.get(session.session_id).current_segment_id == "main-10"  # type: ignore[union-attr]
    assert events == [
        "stream_main_segment.started",
        "stream_main_segment.topic_selected",
        "stream_main_segment.generation_started",
        "stream_main_segment.output_started",
        "stream_main_segment.speech_started",
        "stream_main_segment.completed",
    ]
    with pytest.raises(StreamMainSegmentRejected, match="main_segment.duplicate"):
        await usecase.start(opening, STATE)


@pytest.mark.asyncio
async def test_requires_completed_opening_live_session_and_verified_state() -> None:
    sessions, _session, opening = setup()
    usecase = StreamMainSegmentUsecase(
        sessions=sessions,
        activities=InMemoryStreamMainSegmentRepository(),
        run_of_show=Ros([main()]),  # type: ignore[arg-type]
        executor=lambda _payload, _trace: turn(),  # type: ignore[arg-type,return-value]
    )
    with pytest.raises(StreamMainSegmentRejected, match="opening.not_completed"):
        await usecase.start(
            StreamOpeningActivity(
                opening.session_id, "trace", "opening", status=StreamOpeningStatus.FAILED
            ),
            STATE,
        )
    with pytest.raises(StreamMainSegmentRejected, match="stream_state.unverified"):
        await usecase.start(opening, {**STATE, "obs_output": "inactive"})


@pytest.mark.asyncio
async def test_topic_selector_fallback_and_failed_retry_are_idempotent() -> None:
    sessions, session, opening = setup()
    calls = 0

    async def execute(_payload: dict[str, object], _trace: str) -> ActivityTurnResult:
        nonlocal calls
        calls += 1
        return turn(ActionExecutionStatus.FAILED if calls == 1 else ActionExecutionStatus.COMPLETED)

    usecase = StreamMainSegmentUsecase(
        sessions=sessions,
        activities=InMemoryStreamMainSegmentRepository(),
        run_of_show=Ros([main(topic=None)]),  # type: ignore[arg-type]
        executor=execute,
        topic_selector=lambda intent, _title, recent: f"{intent}:{len(recent)}",
    )
    failed = await usecase.start(opening, STATE)
    assert failed.status == StreamMainSegmentStatus.FAILED
    assert sessions.get(session.session_id).status == StreamSessionStatus.LIVE  # type: ignore[union-attr]
    command = RetryMainSegmentCommand(
        "retry", session.session_id, failed.activity_id, failed.version
    )
    completed = await usecase.retry(command)
    assert await usecase.retry(command) == completed
    assert completed.status == StreamMainSegmentStatus.COMPLETED
    assert calls == 2


@pytest.mark.asyncio
async def test_missing_required_main_fails_without_llm() -> None:
    sessions, _session, opening = setup()
    usecase = StreamMainSegmentUsecase(
        sessions=sessions,
        activities=InMemoryStreamMainSegmentRepository(),
        run_of_show=Ros([]),  # type: ignore[arg-type]
        executor=lambda _payload, _trace: turn(),  # type: ignore[arg-type,return-value]
    )
    result = await usecase.start(opening, STATE)
    assert result.status == StreamMainSegmentStatus.FAILED
    assert result.failure_code == "main_segment.required_missing"
