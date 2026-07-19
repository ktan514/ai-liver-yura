from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.youtube.youtube_api_error_mapper import YouTubeApiErrorMapper
from app.ports.youtube_live_chat import (
    LiveChatMessageDto,
    LiveChatPageDto,
    YouTubeLiveChatReadPort,
)


class GoogleYouTubeLiveChatAdapter(YouTubeLiveChatReadPort):
    adapter_type = "google"

    def __init__(self, client_factory: Any) -> None:
        self._client_factory = client_factory

    async def get_live_chat_status(self, live_chat_id: str) -> str:
        try:
            page = await self.list_messages(live_chat_id, None, 1)
            return "active" if page.polling_interval_ms > 0 else "unknown"
        except Exception as error:
            mapped = YouTubeApiErrorMapper.map(error)
            if mapped.api_reason in {"liveChatEnded", "liveChatDisabled"}:
                return "ended"
            if mapped.api_reason == "liveChatNotFound":
                return "not_found"
            raise mapped from error

    async def list_messages(
        self, live_chat_id: str, page_token: str | None, max_results: int
    ) -> LiveChatPageDto:
        try:
            raw = await asyncio.to_thread(
                self._list_sync, live_chat_id, page_token, max_results
            )
            return self._parse(raw)
        except Exception as error:
            raise YouTubeApiErrorMapper.map(error) from error

    def _list_sync(
        self, live_chat_id: str, page_token: str | None, max_results: int
    ) -> dict[str, Any]:
        request = (
            self._client_factory.create()
            .liveChatMessages()
            .list(
                liveChatId=live_chat_id,
                part="id,snippet,authorDetails",
                maxResults=max(1, min(max_results, 2000)),
                pageToken=page_token,
            )
        )
        value = request.execute(num_retries=0)
        if not isinstance(value, dict):
            raise ValueError("live chat response must be an object")
        return value

    @staticmethod
    def _parse(raw: dict[str, Any]) -> LiveChatPageDto:
        items = raw.get("items")
        interval = raw.get("pollingIntervalMillis")
        if (
            not isinstance(items, list)
            or not isinstance(interval, int)
            or interval <= 0
        ):
            raise ValueError("invalid live chat response")
        messages: list[LiveChatMessageDto] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid live chat item")
            message_id = item.get("id")
            snippet = item.get("snippet")
            author = item.get("authorDetails", {})
            if not isinstance(message_id, str) or not isinstance(snippet, dict):
                raise ValueError("invalid live chat item")
            if not isinstance(author, dict):
                author = {}
            messages.append(
                LiveChatMessageDto(
                    message_id=message_id,
                    kind=str(snippet.get("type") or "unknown"),
                    snippet=dict(snippet),
                    author=dict(author),
                )
            )
        token = raw.get("nextPageToken")
        return LiveChatPageDto(
            tuple(messages),
            token if isinstance(token, str) and token else None,
            interval,
        )
