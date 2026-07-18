from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    event_id: str
    event_type: str
    occurred_at: str
    trace_id: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "trace_id": self.trace_id,
            "data": self.data,
        }


@dataclass(frozen=True, slots=True, eq=False)
class EventSubscription:
    """A bounded live feed paired with an immutable replay snapshot."""

    replay_events: tuple[ApplicationEvent, ...]
    live_queue: asyncio.Queue[ApplicationEvent]


class ApplicationEventBroker:
    """Plugin-neutral fan-out broker with bounded replay for framework adapters."""

    RESYNC_EVENT_TYPE = "system.resync_required"

    def __init__(
        self,
        replay_size: int = 256,
        *,
        replay_limit: int = 128,
        live_queue_size: int = 128,
    ) -> None:
        if replay_size < 1 or replay_limit < 1 or live_queue_size < 1:
            raise ValueError("event broker limits must be positive")
        self._history: deque[ApplicationEvent] = deque(maxlen=replay_size)
        self._replay_limit = replay_limit
        self._live_queue_size = live_queue_size
        self._clients: set[EventSubscription] = set()
        self._observers: list[Callable[[str, dict[str, Any], str], None]] = []
        self._lock = threading.RLock()

    def add_observer(self, observer: Callable[[str, dict[str, Any], str], None]) -> None:
        self._observers.append(observer)

    def publish(
        self, event_type: str, data: dict[str, Any], trace_id: str = ""
    ) -> ApplicationEvent:
        event = ApplicationEvent(
            event_id=str(uuid4()),
            event_type=event_type,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id or str(uuid4()),
            data=data,
        )
        with self._lock:
            self._history.append(event)
            clients = tuple(self._clients)
        for observer in tuple(self._observers):
            observer(event_type, data, event.trace_id)
        for subscription in clients:
            try:
                subscription.live_queue.put_nowait(event)
            except asyncio.QueueFull:
                self._disconnect_overflowed(subscription, event)
        return event

    def subscribe(self, last_event_id: str | None = None) -> EventSubscription:
        """Atomically register a live subscriber and capture its bounded replay."""
        queue: asyncio.Queue[ApplicationEvent] = asyncio.Queue(maxsize=self._live_queue_size)
        with self._lock:
            history = tuple(self._history)
            replay, resync_reason = self._select_replay(history, last_event_id)
            if resync_reason is not None:
                replay = (self._resync_event(resync_reason, history, replay), *replay)
            subscription = EventSubscription(replay_events=replay, live_queue=queue)
            self._clients.add(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        with self._lock:
            self._clients.discard(subscription)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def _select_replay(
        self,
        history: tuple[ApplicationEvent, ...],
        last_event_id: str | None,
    ) -> tuple[tuple[ApplicationEvent, ...], str | None]:
        if last_event_id is None:
            candidates = history
            reason = None
        else:
            position = next(
                (index for index, item in enumerate(history) if item.event_id == last_event_id),
                None,
            )
            if position is None:
                candidates = history
                reason = "last_event_id_unavailable"
            else:
                candidates = history[position + 1 :]
                reason = None
        if len(candidates) > self._replay_limit:
            return candidates[-self._replay_limit :], reason or "replay_limit_exceeded"
        return candidates, reason

    def _disconnect_overflowed(
        self, subscription: EventSubscription, latest_event: ApplicationEvent
    ) -> None:
        with self._lock:
            if subscription not in self._clients:
                return
            self._clients.discard(subscription)
            history = tuple(self._history)
        queue = subscription.live_queue
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(
            self._resync_event("live_queue_overflow", history, (latest_event,))
        )

    @staticmethod
    def _resync_event(
        reason: str,
        history: tuple[ApplicationEvent, ...],
        replay: tuple[ApplicationEvent, ...],
    ) -> ApplicationEvent:
        return ApplicationEvent(
            event_id=str(uuid4()),
            event_type=ApplicationEventBroker.RESYNC_EVENT_TYPE,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            trace_id=str(uuid4()),
            data={
                "reason": reason,
                "oldest_available_event_id": history[0].event_id if history else None,
                "replay_from_event_id": replay[0].event_id if replay else None,
            },
        )
