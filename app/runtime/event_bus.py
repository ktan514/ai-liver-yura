

from __future__ import annotations

from app.domain.events import AgentEvent
from app.ports.event_publisher import EventPublisher
from app.runtime.event_queue import EventQueue


class EventBus(EventPublisher):
    """AgentEvent を Runtime の EventQueue へ流す内部 EventBus。"""

    def __init__(self, event_queue: EventQueue) -> None:
        self._event_queue = event_queue

    async def publish(self, event: AgentEvent) -> None:
        await self._event_queue.put(event)