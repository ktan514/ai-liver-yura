

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_bus import EventBus
from app.runtime.event_queue import EventQueue


@pytest.mark.asyncio
async def test_publish_puts_event_into_event_queue() -> None:
    event_queue = EventQueue()
    event_bus = EventBus(event_queue)
    event = AgentEvent(event_type=AgentEventType.SPEECH_STARTED)

    await event_bus.publish(event)

    assert await event_queue.get() == event