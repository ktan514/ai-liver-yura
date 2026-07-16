from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar, cast

from app.adapters.youtube.models import (
    map_broadcast,
    map_stream_health,
    map_stream_status,
)
from app.adapters.youtube.youtube_api_error_mapper import (
    YouTubeApiError,
    YouTubeApiErrorKind,
    YouTubeApiErrorMapper,
)
from app.domain.streaming import (
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
    YouTubeBroadcastStatus,
    YouTubeBroadcastSummary,
    YouTubeLiveChatSnapshot,
    YouTubeLiveChatStatus,
    YouTubeStreamSnapshot,
    YouTubeStreamStatus,
)
from app.utils.trace import TraceLogger

T = TypeVar("T")


class YouTubeAuthService(Protocol):
    def get_state(self) -> YouTubeAuthenticationState: ...

    def authenticate(self) -> YouTubeAuthenticationState: ...


class YouTubeClientFactory(Protocol):
    def create(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class GoogleYouTubePreparationConfig:
    max_retries: int = 2
    retry_initial_delay_seconds: float = 1.0
    allow_live_broadcast: bool = False
    allowed_privacy_statuses: tuple[str, ...] = ("private", "unlisted", "public")


class GoogleYouTubePreparationAdapter:
    """YouTube Data API v3の読取操作だけを公開するPreparation Adapter。"""

    def __init__(
        self,
        *,
        auth_service: YouTubeAuthService,
        client_factory: YouTubeClientFactory,
        config: GoogleYouTubePreparationConfig,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._auth_service = auth_service
        self._client_factory = client_factory
        self._config = config
        self._trace = trace_logger or TraceLogger()
        self._api_lock = asyncio.Lock()

    @property
    def adapter_type(self) -> str:
        return "google"

    async def get_authentication_state(self) -> YouTubeAuthenticationState:
        return await asyncio.to_thread(self._auth_service.get_state)

    async def authenticate(self) -> YouTubeAuthenticationState:
        return await asyncio.to_thread(self._auth_service.authenticate)

    async def check_authentication(self) -> bool:
        state = await self.get_authentication_state()
        return state.status == YouTubeAuthenticationStatus.AUTHENTICATED

    async def list_broadcasts(self) -> tuple[YouTubeBroadcastSummary, ...]:
        broadcasts: list[YouTubeBroadcastSummary] = []
        page_token: str | None = None
        while True:

            def list_page(client: Any, token: str | None = page_token) -> Any:
                return (
                    client.liveBroadcasts()
                    .list(
                        part="id,snippet,status,contentDetails",
                        broadcastStatus="all",
                        mine=True,
                        maxResults=50,
                        pageToken=token,
                    )
                    .execute(num_retries=0)
                )

            response = await self._request(list_page)
            items = response.get("items", [])
            if not isinstance(items, list):
                raise YouTubeApiError(
                    YouTubeApiErrorKind.INVALID_RESPONSE,
                    "YouTube Broadcast一覧responseが不正です。",
                )
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                try:
                    broadcasts.append(
                        map_broadcast(
                            raw,
                            allow_live_broadcast=self._config.allow_live_broadcast,
                        )
                    )
                except ValueError as error:
                    raise YouTubeApiError(
                        YouTubeApiErrorKind.INVALID_RESPONSE,
                        "YouTube Broadcast responseが不正です。",
                    ) from error
            next_token = response.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token
        maximum = datetime.max.replace(tzinfo=timezone.utc)
        broadcasts.sort(key=lambda item: (item.scheduled_start_at or maximum, item.broadcast_id))
        return tuple(broadcasts)

    async def resolve_broadcast(self, broadcast_id: str) -> YouTubeBroadcastSummary:
        broadcast = await self._find_owned_broadcast(broadcast_id)
        if not broadcast.selectable:
            raise YouTubeApiError(
                YouTubeApiErrorKind.INVALID_STATE,
                f"Broadcastは配信準備対象ではありません: {broadcast.lifecycle_status}",
            )
        if broadcast.privacy_status not in self._config.allowed_privacy_statuses:
            raise YouTubeApiError(
                YouTubeApiErrorKind.INVALID_STATE,
                "Broadcastの公開範囲を確認できません。",
            )
        if not broadcast.bound_stream_id:
            raise YouTubeApiError(
                YouTubeApiErrorKind.INVALID_STATE,
                "YouTube StreamがBroadcastへbindされていません。",
            )
        return broadcast

    async def resolve_bound_stream(self, broadcast_id: str) -> YouTubeStreamSnapshot:
        broadcast = await self.resolve_broadcast(broadcast_id)
        stream_id = broadcast.bound_stream_id
        if stream_id is None:
            raise YouTubeApiError(
                YouTubeApiErrorKind.INVALID_STATE,
                "YouTube StreamがBroadcastへbindされていません。",
            )
        response = await self._request(
            lambda client: (
                client.liveStreams()
                .list(part="id,snippet,status,cdn", id=stream_id, maxResults=1)
                .execute(num_retries=0)
            )
        )
        item = self._first_item(response, "YouTube Streamが見つかりません。")
        status_data = item.get("status")
        cdn = item.get("cdn")
        if not isinstance(status_data, dict):
            status_data = {}
        if not isinstance(cdn, dict):
            cdn = {}
        stream_status = map_stream_status(status_data.get("streamStatus"))
        if stream_status == YouTubeStreamStatus.UNKNOWN:
            raise YouTubeApiError(
                YouTubeApiErrorKind.INVALID_STATE,
                "YouTube Stream状態を確認できません。",
            )
        health = status_data.get("healthStatus")
        health_value = health.get("status") if isinstance(health, dict) else None
        ingestion_type = cdn.get("ingestionType")
        return YouTubeStreamSnapshot(
            stream_id=stream_id,
            status=stream_status.value,
            bound=True,
            live_chat_id=broadcast.live_chat_id,
            ingestion_type=ingestion_type if isinstance(ingestion_type, str) else None,
            health_status=map_stream_health(health_value),
        )

    async def get_stream_status(self, stream_id: str) -> str:
        response = await self._request(
            lambda client: (
                client.liveStreams()
                .list(part="id,status", id=stream_id, maxResults=1)
                .execute(num_retries=0)
            )
        )
        item = self._first_item(response, "YouTube Streamが見つかりません。")
        status_data = item.get("status")
        value = status_data.get("streamStatus") if isinstance(status_data, dict) else None
        return map_stream_status(value).value

    async def get_broadcast_status(self, broadcast_id: str) -> str:
        return (await self._find_owned_broadcast(broadcast_id)).lifecycle_status

    async def get_live_chat_id(self, broadcast_id: str) -> str | None:
        return (await self.get_live_chat_availability(broadcast_id)).live_chat_id

    async def get_live_chat_availability(self, broadcast_id: str) -> YouTubeLiveChatSnapshot:
        broadcast = await self._find_owned_broadcast(broadcast_id)
        if broadcast.live_chat_id:
            return YouTubeLiveChatSnapshot(
                YouTubeLiveChatStatus.AVAILABLE,
                live_chat_id=broadcast.live_chat_id,
            )
        status = YouTubeBroadcastStatus(broadcast.lifecycle_status)
        if status in {YouTubeBroadcastStatus.COMPLETE, YouTubeBroadcastStatus.REVOKED}:
            return YouTubeLiveChatSnapshot(
                YouTubeLiveChatStatus.UNAVAILABLE,
                reason="Broadcast状態によりLive Chatを利用できません。",
            )
        return YouTubeLiveChatSnapshot(
            YouTubeLiveChatStatus.MISSING,
            reason="Live Chat IDがまだ生成されていないか、Live Chatが無効です。",
        )

    async def health_check(self) -> bool:
        await self._request(
            lambda client: (
                client.channels().list(part="id", mine=True, maxResults=1).execute(num_retries=0)
            )
        )
        return True

    async def _find_owned_broadcast(self, broadcast_id: str) -> YouTubeBroadcastSummary:
        for broadcast in await self.list_broadcasts():
            if broadcast.broadcast_id == broadcast_id:
                return broadcast
        raise YouTubeApiError(
            YouTubeApiErrorKind.NOT_FOUND,
            "自チャンネルのYouTube Broadcastが見つかりません。",
        )

    async def _request(self, operation: Callable[[Any], Any]) -> dict[str, Any]:
        async with self._api_lock:
            delay = self._config.retry_initial_delay_seconds
            for attempt in range(self._config.max_retries + 1):
                try:
                    response = await asyncio.to_thread(self._request_sync, operation)
                    if not isinstance(response, dict):
                        raise YouTubeApiError(
                            YouTubeApiErrorKind.INVALID_RESPONSE,
                            "YouTube API responseがobjectではありません。",
                        )
                    return cast(dict[str, Any], response)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    mapped = YouTubeApiErrorMapper.map(error)
                    self._trace.warning(
                        "youtube_api:request_failed",
                        error_kind=mapped.kind.value,
                        http_status=mapped.http_status,
                        api_reason=mapped.api_reason,
                        retryable=mapped.retryable,
                        attempt=attempt + 1,
                    )
                    if not mapped.retryable or attempt >= self._config.max_retries:
                        raise mapped from error
                    await asyncio.sleep(delay)
                    delay *= 2
        raise AssertionError("unreachable")

    def _request_sync(self, operation: Callable[[Any], Any]) -> Any:
        return operation(self._client_factory.create())

    @staticmethod
    def _first_item(response: dict[str, Any], message: str) -> dict[str, Any]:
        items = response.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise YouTubeApiError(YouTubeApiErrorKind.NOT_FOUND, message)
        return cast(dict[str, Any], items[0])
