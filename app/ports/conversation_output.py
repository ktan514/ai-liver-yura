from __future__ import annotations

from typing import Protocol


class ConversationOutputPublisher(Protocol):
    async def publish_text(self, *, kind: str, text: str, action_id: str) -> None:
        """会話画面へ表示する出力テキストを送る。"""
