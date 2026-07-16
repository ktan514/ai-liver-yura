from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.domain.streaming import (
    YouTubeAuthenticationState,
    YouTubeAuthenticationStatus,
    YouTubeBroadcastSummary,
    YouTubeLiveChatSnapshot,
    YouTubeLiveChatStatus,
    YouTubeStreamSnapshot,
)


@dataclass(frozen=True, slots=True)
class FakeYouTubePreparationConfig:
    authenticated: bool = True
    api_available: bool = True
    broadcasts: tuple[YouTubeBroadcastSummary, ...] = ()
    stream_bound: bool = True
    stream_status: str = "ready"
    broadcast_status: str = "ready"
    live_chat_enabled: bool = True
    latency_seconds: float = 0.0
    timeout: bool = False
    quota_error: bool = False


class FakeYouTubePreparationAdapter:
    def __init__(self, config: FakeYouTubePreparationConfig) -> None:
        self._config = config

    @property
    def adapter_type(self) -> str:
        return "fake"

    async def get_authentication_state(self) -> YouTubeAuthenticationState:
        return YouTubeAuthenticationState(
            YouTubeAuthenticationStatus.AUTHENTICATED
            if self._config.authenticated
            else YouTubeAuthenticationStatus.AUTHENTICATION_REQUIRED
        )

    async def authenticate(self) -> YouTubeAuthenticationState:
        return await self.get_authentication_state()

    async def _wait(self) -> None:
        if self._config.timeout:
            await asyncio.sleep(3600)
        if self._config.latency_seconds:
            await asyncio.sleep(self._config.latency_seconds)
        if self._config.quota_error:
            raise RuntimeError("YouTube API quota exceeded")

    async def list_broadcasts(self) -> tuple[YouTubeBroadcastSummary, ...]:
        await self._wait()
        return self._config.broadcasts

    async def check_authentication(self) -> bool:
        await self._wait()
        return self._config.authenticated

    async def resolve_broadcast(self, broadcast_id: str) -> YouTubeBroadcastSummary:
        await self._wait()
        for item in self._config.broadcasts:
            if item.broadcast_id == broadcast_id:
                return item
        raise LookupError(f"YouTube Broadcastが見つかりません: {broadcast_id}")

    async def resolve_bound_stream(self, broadcast_id: str) -> YouTubeStreamSnapshot:
        await self.resolve_broadcast(broadcast_id)
        if not self._config.stream_bound:
            raise LookupError("YouTube StreamがBroadcastへbindされていません。")
        return YouTubeStreamSnapshot(
            stream_id=f"stream-{broadcast_id}",
            status=self._config.stream_status,
            bound=True,
            live_chat_id=f"chat-{broadcast_id}" if self._config.live_chat_enabled else None,
            ingestion_type="rtmp",
            health_status="healthy",
        )

    async def get_stream_status(self, stream_id: str) -> str:
        await self._wait()
        return self._config.stream_status

    async def get_broadcast_status(self, broadcast_id: str) -> str:
        await self.resolve_broadcast(broadcast_id)
        return self._config.broadcast_status

    async def get_live_chat_id(self, broadcast_id: str) -> str | None:
        await self.resolve_broadcast(broadcast_id)
        return f"chat-{broadcast_id}" if self._config.live_chat_enabled else None

    async def get_live_chat_availability(self, broadcast_id: str) -> YouTubeLiveChatSnapshot:
        live_chat_id = await self.get_live_chat_id(broadcast_id)
        return YouTubeLiveChatSnapshot(
            status=(
                YouTubeLiveChatStatus.AVAILABLE if live_chat_id else YouTubeLiveChatStatus.DISABLED
            ),
            live_chat_id=live_chat_id,
            reason=None if live_chat_id else "Live Chatは無効です。",
        )

    async def health_check(self) -> bool:
        await self._wait()
        return self._config.api_available


class UnavailableYouTubePreparationAdapter:
    """設定不備をRuntime停止ではなく構造化認証失敗として公開する。"""

    def __init__(self, reason: str, *, adapter_type: str = "google") -> None:
        self._reason = reason
        self._adapter_type = adapter_type

    @property
    def adapter_type(self) -> str:
        return self._adapter_type

    async def get_authentication_state(self) -> YouTubeAuthenticationState:
        return YouTubeAuthenticationState(
            YouTubeAuthenticationStatus.AUTHENTICATION_FAILED,
            self._reason,
        )

    async def authenticate(self) -> YouTubeAuthenticationState:
        return await self.get_authentication_state()

    async def _fail(self) -> None:
        raise RuntimeError(self._reason)

    async def list_broadcasts(self) -> tuple[YouTubeBroadcastSummary, ...]:
        await self._fail()
        return ()

    async def check_authentication(self) -> bool:
        return False

    async def resolve_broadcast(self, broadcast_id: str) -> YouTubeBroadcastSummary:
        await self._fail()
        raise AssertionError

    async def resolve_bound_stream(self, broadcast_id: str) -> YouTubeStreamSnapshot:
        await self._fail()
        raise AssertionError

    async def get_stream_status(self, stream_id: str) -> str:
        await self._fail()
        return "unknown"

    async def get_broadcast_status(self, broadcast_id: str) -> str:
        await self._fail()
        return "unknown"

    async def get_live_chat_id(self, broadcast_id: str) -> str | None:
        await self._fail()
        return None

    async def get_live_chat_availability(self, broadcast_id: str) -> YouTubeLiveChatSnapshot:
        await self._fail()
        return YouTubeLiveChatSnapshot(YouTubeLiveChatStatus.UNAVAILABLE)

    async def health_check(self) -> bool:
        return False
