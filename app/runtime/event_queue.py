from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field

from app.domain.events import AgentEvent


@dataclass(order=True)
class _QueuedEvent:
    sort_priority: int
    sequence: int
    event: AgentEvent = field(compare=False)


class EventQueue:
    """AgentEvent を優先度付きで扱うキュー。

    priority が高いイベントほど先に取り出す。
    同じ priority の場合は投入順を維持する。
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_QueuedEvent] = asyncio.PriorityQueue()
        self._sequence = itertools.count()

    async def put(self, event: AgentEvent) -> None:
        # PriorityQueue は小さい値を先に返すため、優先度を反転する。
        queued = _QueuedEvent(
            sort_priority=-event.priority,
            sequence=next(self._sequence),
            event=event,
        )
        await self._queue.put(queued)

    async def get(self) -> AgentEvent:
        queued = await self._queue.get()
        return queued.event

    def empty(self) -> bool:
        return self._queue.empty()
