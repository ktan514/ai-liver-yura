from __future__ import annotations

import json
import threading
from collections.abc import Callable

import httpx

from streaming_admin.client.dto import ApiEvent
from streaming_admin.config import AdminClientConfig


class EventStreamClient:
    def __init__(self, config: AdminClientConfig) -> None:
        self.config = config
        self._seen: set[str] = set()
        self._last_event_id: str | None = None
        self._stop = threading.Event()

    def run(
        self, on_event: Callable[[ApiEvent], None], on_connection: Callable[[bool], None]
    ) -> None:
        headers = {"Accept": "text/event-stream"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        while not self._stop.is_set():
            if self._last_event_id:
                headers["Last-Event-ID"] = self._last_event_id
            try:
                with httpx.stream(
                    "GET",
                    f"{self.config.base_url}/api/v1/events/stream",
                    headers=headers,
                    timeout=httpx.Timeout(10, read=None),
                ) as response:
                    response.raise_for_status()
                    on_connection(True)
                    for line in response.iter_lines():
                        if self._stop.is_set():
                            return
                        if not line.startswith("data: "):
                            continue
                        event = ApiEvent.from_dict(json.loads(line[6:]))
                        if event.event_id in self._seen:
                            continue
                        self._seen.add(event.event_id)
                        self._last_event_id = event.event_id
                        on_event(event)
            except (httpx.HTTPError, ValueError, KeyError):
                on_connection(False)
                self._stop.wait(2)

    def stop(self) -> None:
        self._stop.set()
