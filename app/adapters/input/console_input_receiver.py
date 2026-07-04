

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.domain.events import AgentEvent, AgentEventType
from app.runtime import EventPublisher, InputReceiver


InputProvider = Callable[[], Awaitable[str | None]]


class ConsoleInputReceiver(InputReceiver):
    """コンソール入力を USER_TEXT Event として投入する入力アダプタ。"""

    def __init__(self, input_provider: InputProvider | None = None) -> None:
        self._input_provider = input_provider or self._default_input_provider
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

    async def wait_until_stopped(self) -> None:
        if self._task is None:
            return

        await self._task
        self._task = None

    async def _run(self, publish_event: EventPublisher) -> None:
        while self._running:
            text = await self._input_provider()

            if text is None:
                self._running = False
                break

            stripped_text = text.strip()

            if stripped_text in ("exit", "quit"):
                self._running = False
                break

            if not stripped_text:
                continue

            print()
            await publish_event(
                AgentEvent(
                    event_type=AgentEventType.USER_TEXT,
                    payload={"text": stripped_text, "source": "console"},
                )
            )
            await asyncio.sleep(0.01)

    async def _default_input_provider(self) -> str | None:
        return await asyncio.to_thread(input, "> ")