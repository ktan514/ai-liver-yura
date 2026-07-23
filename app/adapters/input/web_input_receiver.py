from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.runtime import EventPublisher, InputReceiver
from app.utils.trace import TraceLogger


@dataclass(frozen=True)
class WebInputReceiverConfig:
    host: str = "127.0.0.1"
    port: int = 8771
    max_text_length: int = 4000

    def __post_init__(self) -> None:
        if not 0 <= self.port <= 65535:
            raise ValueError("Web入力UDPポートは0から65535の範囲で指定してください。")
        if self.max_text_length < 1:
            raise ValueError("Web入力の最大文字数は1以上で指定してください。")


class _WebInputProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        publish_event: EventPublisher,
        config: WebInputReceiverConfig,
        task_started: Callable[[asyncio.Task[None]], None],
        task_finished: Callable[[asyncio.Task[None]], None],
    ) -> None:
        self._publish_event = publish_event
        self._config = config
        self._task_started = task_started
        self._task_finished = task_finished
        self._trace_logger = TraceLogger()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        del addr
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return
        if payload.get("type") != "user_text":
            return
        raw_text = payload.get("text")
        if not isinstance(raw_text, str):
            return
        text = raw_text.strip()
        if not text or len(text) > self._config.max_text_length:
            return
        event = AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": text, "source": "web"},
            authority=InputAuthority.USER,
        )
        task: asyncio.Task[None] = asyncio.create_task(self._publish(event))
        self._task_started(task)
        task.add_done_callback(self._task_finished)
        self._trace_logger.debug(
            "web_input_receiver:user_text_received",
            input_length=len(text),
            source="web",
        )

    async def _publish(self, event: AgentEvent) -> None:
        await self._publish_event(event)


class WebInputReceiver(InputReceiver):
    """ローカルWeb会話画面からUSER_TEXTを受け取るUDP入力アダプタ。"""

    def __init__(self, config: WebInputReceiverConfig | None = None) -> None:
        self._config = config or WebInputReceiverConfig()
        self._transport: asyncio.DatagramTransport | None = None
        self._stopped = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self, publish_event: EventPublisher) -> None:
        if self._transport is not None:
            return
        self._stopped.clear()
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _WebInputProtocol(
                publish_event,
                self._config,
                self._tasks.add,
                self._task_finished,
            ),
            local_addr=(self._config.host, self._config.port),
        )
        self._transport = transport

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._stopped.set()

    async def wait_until_stopped(self) -> None:
        await self._stopped.wait()

    @property
    def bound_port(self) -> int | None:
        if self._transport is None:
            return None
        address = self._transport.get_extra_info("sockname")
        return int(address[1]) if isinstance(address, tuple) else None

    def _task_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except Exception as error:
            TraceLogger().warning(
                "web_input_receiver:event_publish_failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
