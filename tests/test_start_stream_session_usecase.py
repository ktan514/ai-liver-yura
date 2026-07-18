from __future__ import annotations

from dataclasses import replace

import pytest

from app.adapters.streaming.fake_streaming_control import (
    FakeObsStreamingControlAdapter,
    FakeYouTubeStreamingControlAdapter,
)
from app.adapters.streaming.in_memory_session_repository import (
    InMemoryStreamSessionRepository,
)
from app.domain.streaming import (
    ApproveStreamStartCommand,
    StreamSession,
    StreamSessionStatus,
    StreamStartRejected,
)
from app.usecases import StartStreamSessionUsecase


def ready_session(repository: InMemoryStreamSessionRepository) -> StreamSession:
    created = repository.create(
        StreamSession(trace_id="prepare", selected_broadcast_id="broadcast", title="title")
    )
    preparing = repository.save(created.transition(StreamSessionStatus.PREPARING))
    return repository.save(
        preparing.transition(StreamSessionStatus.READY, selected_stream_id="stream")
    )


def command(session: StreamSession, command_id: str = "command") -> ApproveStreamStartCommand:
    return ApproveStreamStartCommand(
        command_id,
        "trace",
        session.session_id,
        session.state_version,
        "operator",
    )


def usecase(
    repository: InMemoryStreamSessionRepository,
    obs: FakeObsStreamingControlAdapter | None = None,
    youtube: FakeYouTubeStreamingControlAdapter | None = None,
    events: list[str] | None = None,
) -> StartStreamSessionUsecase:
    obs_value = obs or FakeObsStreamingControlAdapter()
    youtube_value = youtube or FakeYouTubeStreamingControlAdapter()
    obs_value.adapter_type = "obs_websocket"
    youtube_value.adapter_type = "google"
    return StartStreamSessionUsecase(
        sessions=repository,
        obs=obs_value,
        youtube=youtube_value,
        event_publisher=(
            (lambda event, data, trace: events.append(event)) if events is not None else None
        ),
        poll_interval_seconds=0.001,
        step_timeout_seconds=0.005,
    )


@pytest.mark.asyncio
async def test_ready_approval_reaches_live_and_records_audit_and_event_order() -> None:
    repository = InMemoryStreamSessionRepository()
    session = ready_session(repository)
    events: list[str] = []
    value = usecase(repository, events=events)
    result = await value.execute(command(session))
    assert result.successful is True
    assert (result.obs_status, result.youtube_stream_status, result.youtube_broadcast_status) == (
        "active",
        "active",
        "live",
    )
    current = repository.get(session.session_id)
    assert current is not None
    assert current.status == StreamSessionStatus.LIVE
    assert current.start_approved_by == "operator"
    assert events == [
        "stream_start.approved",
        "stream_start.started",
        "stream_start.step_updated",
        "stream_start.obs_active",
        "stream_start.youtube_stream_active",
        "stream_start.broadcast_transition_requested",
        "stream_start.broadcast_live",
        "stream_start.completed",
    ]


@pytest.mark.asyncio
async def test_duplicate_command_returns_cached_result_without_external_calls() -> None:
    repository = InMemoryStreamSessionRepository()
    session = ready_session(repository)
    obs = FakeObsStreamingControlAdapter()
    value = usecase(repository, obs=obs)
    first = await value.execute(command(session))
    duplicate = await value.execute(command(session))
    assert first.successful is True
    assert duplicate.duplicate is True
    assert obs.start_calls == 1


@pytest.mark.asyncio
async def test_fake_adapter_version_and_not_ready_are_rejected() -> None:
    repository = InMemoryStreamSessionRepository()
    session = ready_session(repository)
    fake = FakeObsStreamingControlAdapter()
    value = StartStreamSessionUsecase(
        sessions=repository,
        obs=fake,
        youtube=FakeYouTubeStreamingControlAdapter(),
    )
    with pytest.raises(StreamStartRejected, match="stream.start.test_adapter"):
        await value.execute(command(session))

    real = usecase(repository)
    with pytest.raises(StreamStartRejected, match="stream.start.version_mismatch"):
        await real.execute(replace(command(session), expected_state_version=999))

    other_repository = InMemoryStreamSessionRepository()
    created = other_repository.create(
        StreamSession(trace_id="trace", selected_broadcast_id="broadcast", title="title")
    )
    with pytest.raises(StreamStartRejected, match="stream.start.not_ready"):
        await usecase(other_repository).execute(command(created))


@pytest.mark.asyncio
async def test_fake_youtube_is_allowed_only_with_explicit_real_obs_vertical_mode() -> None:
    repository = InMemoryStreamSessionRepository()
    session = ready_session(repository)
    obs = FakeObsStreamingControlAdapter(["idle", "active", "active"])
    obs.adapter_type = "obs_websocket"
    youtube = FakeYouTubeStreamingControlAdapter()
    value = StartStreamSessionUsecase(
        sessions=repository,
        obs=obs,
        youtube=youtube,
        allow_fake_youtube=True,
        poll_interval_seconds=0,
    )

    result = await value.execute(command(session))

    assert result.successful is True
    assert result.youtube_stream_status == "active"
    assert result.youtube_broadcast_status == "live"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("obs_statuses", "stream_statuses", "broadcast_statuses", "failure_code"),
    [
        (["unknown"], ["active"], ["ready"], "stream.start.obs_failed"),
        (["idle", "starting"], ["active"], ["ready"], "stream.start.obs_active_timeout"),
        (["active", "active"], ["inactive"], ["ready"], "stream.start.youtube_stream_timeout"),
        (
            ["active", "active"],
            ["active"],
            ["complete"],
            "stream.start.broadcast_transition_failed",
        ),
        (["active", "active"], ["active"], ["ready"], "stream.start.broadcast_live_timeout"),
    ],
)
async def test_each_external_failure_is_explicit(
    obs_statuses: list[str],
    stream_statuses: list[str],
    broadcast_statuses: list[str],
    failure_code: str,
) -> None:
    repository = InMemoryStreamSessionRepository()
    session = ready_session(repository)
    obs = FakeObsStreamingControlAdapter(obs_statuses)
    youtube = FakeYouTubeStreamingControlAdapter(stream_statuses, broadcast_statuses)
    result = await usecase(repository, obs, youtube).execute(command(session))
    assert result.successful is False
    assert result.failure_code == failure_code
    assert repository.get(session.session_id).status == StreamSessionStatus.START_FAILED  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_already_active_continues_only_after_explicit_approval() -> None:
    repository = InMemoryStreamSessionRepository()
    session = ready_session(repository)
    obs = FakeObsStreamingControlAdapter(["active", "active", "active"])
    result = await usecase(repository, obs=obs).execute(command(session))
    assert result.successful is True
    assert obs.start_calls == 0


@pytest.mark.asyncio
async def test_new_command_retries_from_start_failed_after_rechecking_external_state() -> None:
    repository = InMemoryStreamSessionRepository()
    session = ready_session(repository)
    obs = FakeObsStreamingControlAdapter(["unknown"])
    youtube = FakeYouTubeStreamingControlAdapter()
    value = usecase(repository, obs, youtube)
    failed = await value.execute(command(session, "first"))
    assert failed.status == "start_failed"

    obs.statuses = ["idle", "active", "active"]
    current = repository.get(session.session_id)
    assert current is not None
    retried = await value.execute(command(current, "retry"))
    assert retried.successful is True
    assert repository.get(session.session_id).status == StreamSessionStatus.LIVE  # type: ignore[union-attr]


def test_forbidden_state_transitions_are_rejected() -> None:
    session = StreamSession(trace_id="trace", selected_broadcast_id="broadcast", title="title")
    with pytest.raises(ValueError):
        session.transition(StreamSessionStatus.LIVE)
