from __future__ import annotations

import asyncio

import pytest

from app.adapters.input import ConsoleInputReceiver
from app.domain.events import AgentEvent, AgentEventType


class FakeInputProvider:
    def __init__(self, values: list[str | None]) -> None:
        self._values = values

    async def __call__(self) -> str | None:
        if not self._values:
            return None
        return self._values.pop(0)


class DecodeErrorThenQuitInputProvider:
    def __init__(self) -> None:
        self._failed = False

    async def __call__(self) -> str | None:
        if not self._failed:
            self._failed = True
            raise UnicodeDecodeError("utf-8", b"\xe3", 0, 1, "invalid continuation byte")
        return "quit"


@pytest.mark.asyncio
async def test_console_input_receiver_publishes_user_text_event() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = ConsoleInputReceiver(input_provider=FakeInputProvider(["こんにちは", None]))

    await receiver.start(publish_event)
    await asyncio.sleep(0)
    await receiver.stop()

    assert len(published_events) == 1
    assert published_events[0].event_type == AgentEventType.USER_TEXT
    assert published_events[0].payload == {
        "text": "こんにちは",
        "source": "console",
    }


@pytest.mark.asyncio
async def test_console_input_receiver_strips_text() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = ConsoleInputReceiver(input_provider=FakeInputProvider(["  こんにちは  ", None]))

    await receiver.start(publish_event)
    await asyncio.sleep(0)
    await receiver.stop()

    assert len(published_events) == 1
    assert published_events[0].payload["text"] == "こんにちは"


@pytest.mark.asyncio
async def test_console_input_receiver_ignores_empty_text() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = ConsoleInputReceiver(input_provider=FakeInputProvider(["", "   ", None]))

    await receiver.start(publish_event)
    await asyncio.sleep(0)
    await receiver.stop()

    assert published_events == []


@pytest.mark.asyncio
async def test_console_input_receiver_stops_on_exit() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = ConsoleInputReceiver(input_provider=FakeInputProvider(["exit", "ignored"]))

    await receiver.start(publish_event)
    await asyncio.sleep(0)
    await receiver.stop()

    assert published_events == []


@pytest.mark.asyncio
async def test_console_input_receiver_stops_on_quit() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = ConsoleInputReceiver(input_provider=FakeInputProvider(["quit", "ignored"]))

    await receiver.start(publish_event)
    await asyncio.sleep(0)
    await receiver.stop()

    assert published_events == []


@pytest.mark.asyncio
async def test_console_input_receiver_recovers_from_unicode_decode_error() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = ConsoleInputReceiver(input_provider=DecodeErrorThenQuitInputProvider())

    await receiver.start(publish_event)
    await receiver.wait_until_stopped()

    assert published_events == []
