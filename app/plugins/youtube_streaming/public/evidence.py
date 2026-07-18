from __future__ import annotations

from typing import Any, Protocol


class ManualCheckRecorder(Protocol):
    @property
    def path(self) -> object: ...

    @property
    def count(self) -> int: ...

    @property
    def last_write_at(self) -> str | None: ...

    def record_broker_event(
        self, event_type: str, data: dict[str, Any], trace_id: str
    ) -> None: ...

    def record_ui(self, event: str, details: dict[str, Any] | None = None) -> None: ...

    def record_demo_submission(self, **values: Any) -> None: ...

    def record(self, source: str, category: str, event: str, **values: Any) -> None: ...
