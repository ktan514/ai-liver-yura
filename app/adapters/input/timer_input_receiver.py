from __future__ import annotations

import asyncio

from app.domain.events import AgentEvent, AgentEventType
from app.runtime import EventPublisher, InputReceiver


class TimerInputReceiver(InputReceiver):
    """一定間隔で SILENCE_TIMEOUT Event を投入する入力アダプタ。"""

    def __init__(self, interval_seconds: float, max_events: int | None = None) -> None:
        self._interval_seconds = interval_seconds
        self._max_events = max_events
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self, publish_event: EventPublisher) -> None:
        if self._task is not None and not self._task.done():
            return

        self._running = True
        self._task = asyncio.create_task(self._run(publish_event))

    async def stop(self) -> None:
        self._running = False

        if self._task is None:
            return

        await self._task
        self._task = None

    async def _run(self, publish_event: EventPublisher) -> None:
        published_count = 0

        while self._running:
            if self._max_events is not None and published_count >= self._max_events:
                self._running = False
                break

            await asyncio.sleep(self._interval_seconds)

            if not self._running:
                break

            await publish_event(
                AgentEvent(
                    event_type=AgentEventType.SILENCE_TIMEOUT,
                    payload={"source": "timer"},
                    discardable=True,
                    replace_key="silence_timeout",
                )
            )
            published_count += 1
