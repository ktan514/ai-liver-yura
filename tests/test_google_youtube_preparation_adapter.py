from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from app.adapters.streaming import (
    FakeAvatarHealthAdapter,
    FakeObsPreparationAdapter,
    FakeObsPreparationConfig,
    InMemoryStreamPreparationPublisher,
    InMemoryStreamSessionRepository,
    YamlRunOfShowRepository,
)
from app.adapters.youtube import (
    GoogleYouTubePreparationAdapter,
    GoogleYouTubePreparationConfig,
    YouTubeApiError,
    YouTubeApiErrorKind,
)
from app.plugins.youtube_streaming.application import (
    PrepareStreamSessionUsecase,
    StreamPreparationRequirements,
)
from app.plugins.youtube_streaming.domain import (
    HealthStatus,
    StreamPreparationCommand,
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
    YouTubeLiveChatStatus,
)


class FakeAuth:
    def __init__(
        self,
        status: YouTubeAuthenticationStatus = YouTubeAuthenticationStatus.AUTHENTICATED,
    ) -> None:
        self._status = status

    def get_state(self) -> YouTubeAuthenticationState:
        return YouTubeAuthenticationState(self._status)

    def authenticate(self) -> YouTubeAuthenticationState:
        return self.get_state()


class FakeRequest:
    def __init__(self, result: object) -> None:
        self._result = result

    def execute(self, *, num_retries: int) -> object:
        assert num_retries == 0
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class FakeResource:
    def __init__(
        self, name: str, handler: Callable[[str, dict[str, object]], object]
    ) -> None:
        self._name = name
        self._handler = handler

    def list(self, **kwargs: object) -> FakeRequest:
        return FakeRequest(self._handler(self._name, kwargs))


class FakeClient:
    def __init__(self, handler: Callable[[str, dict[str, object]], object]) -> None:
        self._handler = handler

    def liveBroadcasts(self) -> FakeResource:  # noqa: N802 - Google API contract
        return FakeResource("broadcasts", self._handler)

    def liveStreams(self) -> FakeResource:  # noqa: N802 - Google API contract
        return FakeResource("streams", self._handler)

    def channels(self) -> FakeResource:
        return FakeResource("channels", self._handler)


class FakeFactory:
    def __init__(self, handler: Callable[[str, dict[str, object]], object]) -> None:
        self._handler = handler

    def create(self) -> FakeClient:
        return FakeClient(self._handler)


def broadcast(
    broadcast_id: str = "broadcast-1",
    *,
    title: str = "same title",
    lifecycle: str = "ready",
    bound_stream_id: str | None = "stream-1",
    live_chat_id: str | None = "chat-1",
    privacy: str = "private",
) -> dict[str, object]:
    snippet: dict[str, object] = {
        "title": title,
        "scheduledStartTime": "2026-07-20T10:00:00Z",
    }
    if live_chat_id is not None:
        snippet["liveChatId"] = live_chat_id
    content: dict[str, object] = {}
    if bound_stream_id is not None:
        content["boundStreamId"] = bound_stream_id
    return {
        "id": broadcast_id,
        "snippet": snippet,
        "status": {"lifeCycleStatus": lifecycle, "privacyStatus": privacy},
        "contentDetails": content,
    }


def stream(*, status: str = "ready", health: str = "good") -> dict[str, object]:
    return {
        "id": "stream-1",
        "status": {"streamStatus": status, "healthStatus": {"status": health}},
        "cdn": {
            "ingestionType": "rtmp",
            "ingestionInfo": {
                "streamName": "secret-stream-key",
                "ingestionAddress": "rtmp://secret",
            },
        },
    }


def adapter(
    handler: Callable[[str, dict[str, object]], object],
    *,
    max_retries: int = 0,
    auth: FakeAuth | None = None,
) -> GoogleYouTubePreparationAdapter:
    return GoogleYouTubePreparationAdapter(
        auth_service=auth or FakeAuth(),
        client_factory=FakeFactory(handler),
        config=GoogleYouTubePreparationConfig(
            max_retries=max_retries,
            retry_initial_delay_seconds=0,
        ),
    )


@pytest.mark.asyncio
async def test_list_broadcasts_handles_empty_pagination_sort_and_same_title() -> None:
    def empty_handler(name: str, params: dict[str, object]) -> object:
        del name, params
        return {"items": []}

    assert await adapter(empty_handler).list_broadcasts() == ()

    def handler(name: str, params: dict[str, object]) -> object:
        assert name == "broadcasts"
        if params["pageToken"] is None:
            return {
                "items": [broadcast("broadcast-2", lifecycle="complete")],
                "nextPageToken": "next",
            }
        return {"items": [broadcast("broadcast-1")]}

    results = await adapter(handler).list_broadcasts()
    assert {item.broadcast_id for item in results} == {"broadcast-1", "broadcast-2"}
    assert results[0].title == results[1].title
    assert (
        next(item for item in results if item.broadcast_id == "broadcast-2").selectable
        is False
    )


@pytest.mark.asyncio
async def test_resolve_validates_not_found_status_privacy_and_bound_stream() -> None:
    cases: tuple[tuple[list[dict[str, object]], YouTubeApiErrorKind], ...] = (
        ([], YouTubeApiErrorKind.NOT_FOUND),
        ([broadcast(lifecycle="revoked")], YouTubeApiErrorKind.INVALID_STATE),
        ([broadcast(privacy="unknown")], YouTubeApiErrorKind.INVALID_STATE),
        ([broadcast(bound_stream_id=None)], YouTubeApiErrorKind.INVALID_STATE),
    )
    for items, expected in cases:

        def handler(
            name: str,
            params: dict[str, object],
            values: list[dict[str, object]] = items,
        ) -> object:
            del name, params
            return {"items": values}

        instance = adapter(handler)
        with pytest.raises(YouTubeApiError) as captured:
            await instance.resolve_broadcast("broadcast-1")
        assert captured.value.kind == expected


@pytest.mark.asyncio
async def test_stream_resolution_maps_status_health_without_leaking_secret() -> None:
    def handler(name: str, params: dict[str, object]) -> object:
        return (
            {"items": [broadcast()]} if name == "broadcasts" else {"items": [stream()]}
        )

    result = await adapter(handler).resolve_bound_stream("broadcast-1")
    assert result.status == "ready"
    assert result.health_status == "healthy"
    assert result.ingestion_type == "rtmp"
    assert "secret-stream-key" not in repr(result)
    assert "ingestionAddress" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "mapped"),
    [
        ("ready", "ready"),
        ("active", "active"),
        ("inactive", "inactive"),
        ("error", "error"),
        ("unexpected", "unknown"),
    ],
)
async def test_stream_status_mapping(raw: str, mapped: str) -> None:
    instance = adapter(lambda name, params: {"items": [stream(status=raw)]})
    assert await instance.get_stream_status("stream-1") == mapped


@pytest.mark.asyncio
async def test_live_chat_available_and_missing_are_distinct() -> None:
    available = adapter(lambda name, params: {"items": [broadcast()]})
    assert (
        await available.get_live_chat_availability("broadcast-1")
    ).status == YouTubeLiveChatStatus.AVAILABLE
    missing = adapter(lambda name, params: {"items": [broadcast(live_chat_id=None)]})
    snapshot = await missing.get_live_chat_availability("broadcast-1")
    assert snapshot.status == YouTubeLiveChatStatus.MISSING
    assert snapshot.live_chat_id is None


@pytest.mark.asyncio
async def test_retry_is_limited_to_retryable_errors() -> None:
    attempts = 0

    def retry_handler(name: str, params: dict[str, object]) -> object:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return YouTubeApiError(
                YouTubeApiErrorKind.SERVER, "temporary", retryable=True
            )
        return {"items": []}

    assert await adapter(retry_handler, max_retries=2).list_broadcasts() == ()
    assert attempts == 3

    quota_attempts = 0

    def quota_handler(name: str, params: dict[str, object]) -> object:
        nonlocal quota_attempts
        quota_attempts += 1
        return YouTubeApiError(
            YouTubeApiErrorKind.QUOTA_EXHAUSTED, "quota", retryable=False
        )

    with pytest.raises(YouTubeApiError):
        await adapter(quota_handler, max_retries=5).list_broadcasts()
    assert quota_attempts == 1


@pytest.mark.asyncio
async def test_cancel_does_not_publish_late_sync_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = adapter(lambda name, params: {"items": []})

    def slow(operation: object) -> object:
        import time

        time.sleep(0.05)
        return {"items": []}

    monkeypatch.setattr(instance, "_request_sync", slow)
    task = asyncio.create_task(instance.list_broadcasts())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auth_status", "bound_stream_id", "ready"),
    [
        (YouTubeAuthenticationStatus.AUTHENTICATED, "stream-1", True),
        (YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED, "stream-1", False),
        (YouTubeAuthenticationStatus.AUTHENTICATED, None, False),
    ],
)
async def test_google_adapter_integrates_with_prepare_usecase(
    tmp_path: Path,
    auth_status: YouTubeAuthenticationStatus,
    bound_stream_id: str | None,
    ready: bool,
) -> None:
    def handler(name: str, params: dict[str, object]) -> object:
        del params
        if name == "broadcasts":
            return {"items": [broadcast(bound_stream_id=bound_stream_id)]}
        if name == "streams":
            return {"items": [stream()]}
        return {"items": [{"id": "channel"}]}

    ros = tmp_path / "default.yaml"
    ros.write_text(
        "run_of_show_id: default\ntitle: default\nversion: '1'\n"
        "planned_duration_seconds: 10\nsegments:\n  - title: main\n",
        encoding="utf-8",
    )
    youtube = adapter(handler, auth=FakeAuth(auth_status))
    sessions = InMemoryStreamSessionRepository()
    usecase = PrepareStreamSessionUsecase(
        youtube=youtube,
        obs=FakeObsPreparationAdapter(FakeObsPreparationConfig()),
        tts=FakeAvatarHealthAdapter(HealthStatus.HEALTHY),
        avatar=FakeAvatarHealthAdapter(HealthStatus.HEALTHY),
        run_of_show=YamlRunOfShowRepository(tmp_path),
        sessions=sessions,
        publisher=InMemoryStreamPreparationPublisher(),
        requirements=StreamPreparationRequirements(),
    )
    selected = await youtube.list_broadcasts()
    session = usecase.create_session(selected[0], trace_id="trace")
    result = await usecase.execute(
        StreamPreparationCommand(
            "command",
            "trace",
            session.session_id,
            selected[0].broadcast_id,
            expected_state_version=0,
        )
    )
    assert result.ready is ready
    assert any(item.check_id == "youtube.stream.status" for item in result.checks)
    assert not any("secret-stream-key" in repr(item.metadata) for item in result.checks)
