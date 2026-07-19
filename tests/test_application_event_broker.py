from __future__ import annotations

from typing import Any, cast

import pytest

from app.admin_api import create_admin_api
from app.core.application.events import ApplicationEventBroker


def _publish_many(broker: ApplicationEventBroker, count: int) -> list[str]:
    return [
        broker.publish("test.event", {"index": index}).event_id
        for index in range(count)
    ]


def test_replay_is_separate_from_bounded_live_queue() -> None:
    broker = ApplicationEventBroker(replay_size=20, replay_limit=10, live_queue_size=2)
    event_ids = _publish_many(broker, 5)

    subscription = broker.subscribe(event_ids[1])

    assert [event.event_id for event in subscription.replay_events] == event_ids[2:]
    assert subscription.live_queue.empty()
    live = broker.publish("test.live", {})
    assert subscription.live_queue.get_nowait() == live


def test_replay_over_live_capacity_is_truncated_without_queue_full() -> None:
    broker = ApplicationEventBroker(replay_size=20, replay_limit=3, live_queue_size=1)
    event_ids = _publish_many(broker, 8)

    subscription = broker.subscribe(event_ids[0])

    assert subscription.replay_events[0].event_type == broker.RESYNC_EVENT_TYPE
    assert subscription.replay_events[0].data["reason"] == "replay_limit_exceeded"
    assert [event.event_id for event in subscription.replay_events[1:]] == event_ids[
        -3:
    ]
    assert subscription.live_queue.empty()


def test_event_published_after_replay_snapshot_is_delivered_once_as_live() -> None:
    broker = ApplicationEventBroker(replay_size=20, replay_limit=20, live_queue_size=5)
    event_ids = _publish_many(broker, 3)
    subscription = broker.subscribe(event_ids[0])

    live = broker.publish("test.live", {})
    delivered = [*subscription.replay_events, subscription.live_queue.get_nowait()]

    assert [event.event_id for event in delivered] == [
        event_ids[1],
        event_ids[2],
        live.event_id,
    ]
    assert len({event.event_id for event in delivered}) == 3


def test_unavailable_last_event_id_requests_bounded_resync() -> None:
    broker = ApplicationEventBroker(replay_size=4, replay_limit=2, live_queue_size=2)
    event_ids = _publish_many(broker, 4)

    subscription = broker.subscribe("expired-event-id")

    control = subscription.replay_events[0]
    assert control.event_type == broker.RESYNC_EVENT_TYPE
    assert control.data["reason"] == "last_event_id_unavailable"
    assert [event.event_id for event in subscription.replay_events[1:]] == event_ids[
        -2:
    ]


def test_slow_live_subscriber_is_disconnected_with_resync_notice() -> None:
    broker = ApplicationEventBroker(replay_size=10, replay_limit=10, live_queue_size=1)
    subscription = broker.subscribe()

    broker.publish("test.first", {})
    broker.publish("test.overflow", {})

    notice = subscription.live_queue.get_nowait()
    assert notice.event_type == broker.RESYNC_EVENT_TYPE
    assert notice.data["reason"] == "live_queue_overflow"
    assert broker.subscriber_count == 0


def test_repeated_subscribe_unsubscribe_does_not_leak() -> None:
    broker = ApplicationEventBroker()

    for _ in range(3):
        subscription = broker.subscribe()
        assert broker.subscriber_count == 1
        broker.unsubscribe(subscription)
        assert broker.subscriber_count == 0


class _SseService:
    def __init__(self, broker: ApplicationEventBroker) -> None:
        self.broker = broker

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def runtime_status(self) -> dict[str, Any]:
        return {"runtime_mode": "test", "manual_check_log": {"enabled": False}}


@pytest.mark.asyncio
async def test_sse_generator_unsubscribes_when_disconnected_during_replay() -> None:
    broker = ApplicationEventBroker()
    broker.publish("test.replay", {})
    app = create_admin_api(_SseService(broker))  # type: ignore[arg-type]
    endpoint = next(
        cast(Any, route).endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/v1/events/stream"
    )
    response = await endpoint(None)
    iterator = response.body_iterator

    await anext(iterator)
    assert broker.subscriber_count == 1
    await iterator.aclose()

    assert broker.subscriber_count == 0
