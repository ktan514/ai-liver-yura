from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.domain.events import AgentEvent

EventPublisher = Callable[[AgentEvent], Awaitable[None]]


class InputReceiver(Protocol):
    """外部入力を AgentEvent として Runtime に投入する入口。"""

    async def start(self, publish_event: EventPublisher) -> None: ...

    async def stop(self) -> None: ...
