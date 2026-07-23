from __future__ import annotations

from typing import Protocol


class AvatarOutputPort(Protocol):
    """Live2D等の実装に依存しないアバター出力契約。"""

    async def set_expression(self, expression: str) -> None:
        """高レベルな表情名をアバターへ反映する。"""

    async def play_gesture(self, gesture: str) -> None:
        """高レベルなジェスチャー名をアバターへ反映する。"""
