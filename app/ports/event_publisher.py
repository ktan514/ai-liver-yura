from __future__ import annotations

from typing import Protocol

from app.domain.events import AgentEvent


class EventPublisher(Protocol):
    """Runtime 内部へ AgentEvent を発行するための Port。"""

    async def publish(self, event: AgentEvent) -> None:
        """AgentEvent を発行する。"""
