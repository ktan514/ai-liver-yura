

from __future__ import annotations

import asyncio

import pytest

from app.adapters.input import TimerInputReceiver
from app.domain.events import AgentEvent, AgentEventType


@pytest.mark.asyncio
async def test_timer_input_receiver_publishes_silence_timeout_event() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = TimerInputReceiver(interval_seconds=0.01, max_events=1)

    await receiver.start(publish_event)
    await asyncio.sleep(0.03)
    await receiver.stop()

    assert len(published_events) == 1
    assert published_events[0].event_type == AgentEventType.SILENCE_TIMEOUT
    assert published_events[0].payload == {"source": "timer"}
    assert published_events[0].discardable is True
    assert published_events[0].replace_key == "silence_timeout"


@pytest.mark.asyncio
async def test_timer_input_receiver_respects_max_events() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = TimerInputReceiver(interval_seconds=0.01, max_events=2)

    await receiver.start(publish_event)
    await asyncio.sleep(0.05)
    await receiver.stop()

    assert len(published_events) == 2


@pytest.mark.asyncio
async def test_timer_input_receiver_stop_prevents_additional_events() -> None:
    published_events: list[AgentEvent] = []

    async def publish_event(event: AgentEvent) -> None:
        published_events.append(event)

    receiver = TimerInputReceiver(interval_seconds=0.05, max_events=None)

    await receiver.start(publish_event)
    await asyncio.sleep(0.01)
    await receiver.stop()

    assert published_events == []