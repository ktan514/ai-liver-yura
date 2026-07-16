from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from app.domain.streaming import StreamPreparationResult
from app.ports.streaming_preparation import PreparationSubscriber
from app.utils.trace import TraceLogger


class InMemoryStreamPreparationPublisher:
    def __init__(self) -> None:
        self._subscribers: list[PreparationSubscriber] = []
        self._lock = RLock()
        self._trace = TraceLogger()

    def publish(self, result: StreamPreparationResult) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber(result)
            except Exception as error:
                self._trace.warning(
                    "stream_preparation:subscriber_failed",
                    session_id=result.session_id,
                    trace_id=result.trace_id,
                    error_type=type(error).__name__,
                )

    def subscribe(self, subscriber: PreparationSubscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

        return unsubscribe
