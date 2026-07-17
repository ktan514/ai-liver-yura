from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class LiveChatMessageDto:
    message_id: str
    kind: str
    snippet: dict[str, Any]
    author: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LiveChatPageDto:
    messages: tuple[LiveChatMessageDto, ...]
    next_page_token: str | None
    polling_interval_ms: int


class YouTubeLiveChatReadPort(Protocol):
    @property
    def adapter_type(self) -> str: ...

    async def get_live_chat_status(self, live_chat_id: str) -> str: ...

    async def list_messages(
        self, live_chat_id: str, page_token: str | None, max_results: int
    ) -> LiveChatPageDto: ...


class LiveChatDeduplicationRepository(Protocol):
    def check_and_mark(self, session_id: str, key: str) -> bool:
        """初回なら記録してTrue、既処理ならFalseを返す。"""
