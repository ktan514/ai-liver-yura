from __future__ import annotations

from dataclasses import dataclass, field

from app.ports.youtube_live_chat import LiveChatMessageDto, LiveChatPageDto


@dataclass(slots=True)
class FakeLiveChatAdapter:
    pages: list[LiveChatPageDto] = field(default_factory=list)
    adapter_type: str = "fake_live_chat_test"
    error: Exception | None = None
    calls: int = 0
    keep_alive: bool = False

    def enqueue(
        self, message: LiveChatMessageDto, *, polling_interval_ms: int = 100
    ) -> None:
        self.pages.append(LiveChatPageDto((message,), None, polling_interval_ms))

    async def get_live_chat_status(self, live_chat_id: str) -> str:
        del live_chat_id
        return "active" if self.keep_alive or self.pages else "ended"

    async def list_messages(
        self, live_chat_id: str, page_token: str | None, max_results: int
    ) -> LiveChatPageDto:
        del live_chat_id, page_token, max_results
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not self.pages and self.keep_alive:
            return LiveChatPageDto((), None, 100)
        if not self.pages:
            raise RuntimeError("live_chat.chat_ended")
        return self.pages.pop(0)
