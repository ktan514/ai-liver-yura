from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.adapters.streaming import (
    FakeAvatarHealthAdapter,
    FakeObsPreparationAdapter,
    FakeObsPreparationConfig,
    FakeYouTubePreparationAdapter,
    FakeYouTubePreparationConfig,
    InMemoryStreamPreparationPublisher,
    InMemoryStreamSessionRepository,
    YamlRunOfShowRepository,
)
from app.domain.streaming import (
    HealthCheckItem,
    HealthStatus,
    StreamPreparationCommand,
    StreamPreparationResult,
    YouTubeBroadcastSummary,
)
from app.usecases import PrepareStreamSessionUsecase, StreamPreparationRequirements


@dataclass
class FakeTtsHealth:
    status: HealthStatus = HealthStatus.HEALTHY
    delay: float = 0.0
    raises: bool = False

    async def check(self, *, required: bool) -> HealthCheckItem:
        await asyncio.sleep(self.delay)
        if self.raises:
            raise RuntimeError("tts error")
        return HealthCheckItem(
            "tts.available",
            "tts",
            self.status,
            required,
            "tts",
            failure_reason=None if self.status == HealthStatus.HEALTHY else "tts unavailable",
        )


def build_usecase(
    tmp_path: Path,
    *,
    youtube_config: FakeYouTubePreparationConfig | None = None,
    obs_config: FakeObsPreparationConfig | None = None,
    tts: FakeTtsHealth | None = None,
    require_avatar: bool = False,
    timeout: float = 1.0,
) -> tuple[
    PrepareStreamSessionUsecase,
    InMemoryStreamSessionRepository,
    InMemoryStreamPreparationPublisher,
    StreamPreparationCommand,
]:
    ros = tmp_path / "default.yaml"
    ros.write_text(
        "run_of_show_id: default\ntitle: default\nversion: '1'\n"
        "planned_duration_seconds: 10\nsegments:\n  - title: main\n",
        encoding="utf-8",
    )
    broadcast = YouTubeBroadcastSummary("broadcast", "title")
    sessions = InMemoryStreamSessionRepository()
    publisher = InMemoryStreamPreparationPublisher()
    usecase = PrepareStreamSessionUsecase(
        youtube=FakeYouTubePreparationAdapter(
            youtube_config or FakeYouTubePreparationConfig(broadcasts=(broadcast,))
        ),
        obs=FakeObsPreparationAdapter(obs_config or FakeObsPreparationConfig()),
        tts=tts or FakeTtsHealth(),
        avatar=FakeAvatarHealthAdapter(HealthStatus.UNAVAILABLE, "avatar unavailable"),
        run_of_show=YamlRunOfShowRepository(tmp_path),
        sessions=sessions,
        publisher=publisher,
        requirements=StreamPreparationRequirements(
            require_avatar=require_avatar, timeout_seconds=timeout
        ),
    )
    session = usecase.create_session(broadcast, trace_id="trace")
    command = StreamPreparationCommand(
        "command",
        "trace",
        session.session_id,
        broadcast.broadcast_id,
        expected_state_version=session.state_version,
    )
    return usecase, sessions, publisher, command


@pytest.mark.asyncio
async def test_all_required_healthy_becomes_ready_and_publishes(tmp_path: Path) -> None:
    usecase, sessions, publisher, command = build_usecase(tmp_path)
    published: list[StreamPreparationResult] = []
    publisher.subscribe(published.append)
    result = await usecase.execute(command)
    assert result.ready is True
    assert result.status == "ready"
    session = sessions.get(command.session_id)
    assert session is not None and session.can_start is True
    assert published == [result]
    assert any(item.status == HealthStatus.DEGRADED for item in result.checks)


@pytest.mark.asyncio
async def test_required_failure_becomes_failed_and_preserves_reason(tmp_path: Path) -> None:
    config = FakeYouTubePreparationConfig(
        broadcasts=(YouTubeBroadcastSummary("broadcast", "title"),),
        authenticated=False,
    )
    usecase, _, _, command = build_usecase(tmp_path, youtube_config=config)
    result = await usecase.execute(command)
    assert result.ready is False
    assert result.status == "failed"
    assert any("認証" in reason for reason in result.failure_reasons)


@pytest.mark.asyncio
async def test_command_is_idempotent_and_version_mismatch_is_rejected(tmp_path: Path) -> None:
    usecase, sessions, _, command = build_usecase(tmp_path)
    first = await usecase.execute(command)
    duplicate = await usecase.execute(command)
    assert first.ready is True
    assert duplicate.duplicate is True
    retry = StreamPreparationCommand(
        "retry",
        "trace",
        command.session_id,
        command.selected_broadcast_id,
        expected_state_version=0,
    )
    mismatch = await usecase.execute(retry)
    assert mismatch.version_mismatch is True
    session = sessions.get(command.session_id)
    assert session is not None and session.status.value == "ready"


@pytest.mark.asyncio
async def test_unknown_session_is_rejected(tmp_path: Path) -> None:
    usecase, _, _, command = build_usecase(tmp_path)
    unknown = StreamPreparationCommand("unknown", "trace", "missing", command.selected_broadcast_id)
    result = await usecase.execute(unknown)
    assert result.status == "rejected"


@pytest.mark.asyncio
async def test_timeout_and_exception_are_converted_without_aborting_other_checks(
    tmp_path: Path,
) -> None:
    usecase, _, _, command = build_usecase(tmp_path, tts=FakeTtsHealth(delay=0.1), timeout=0.01)
    result = await usecase.execute(command)
    tts = next(item for item in result.checks if item.check_id == "tts.available")
    assert tts.status == HealthStatus.UNAVAILABLE
    assert len(result.checks) > 5


@pytest.mark.asyncio
async def test_checks_run_in_parallel(tmp_path: Path) -> None:
    config = FakeYouTubePreparationConfig(
        broadcasts=(YouTubeBroadcastSummary("broadcast", "title"),),
        latency_seconds=0.02,
    )
    usecase, _, _, command = build_usecase(
        tmp_path, youtube_config=config, tts=FakeTtsHealth(delay=0.05)
    )
    loop = asyncio.get_running_loop()
    started = loop.time()
    await usecase.execute(command)
    elapsed = loop.time() - started
    assert elapsed < 0.16


@pytest.mark.asyncio
async def test_cancel_returns_canceled_failed_result(tmp_path: Path) -> None:
    usecase, _, _, command = build_usecase(tmp_path, tts=FakeTtsHealth(delay=1), timeout=2)
    task = asyncio.create_task(usecase.execute(command))
    await asyncio.sleep(0.01)
    task.cancel()
    result = await task
    assert result.canceled is True
    assert result.status == "failed"
