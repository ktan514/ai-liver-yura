from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ApiEvent:
    event_id: str
    event_type: str
    occurred_at: str
    trace_id: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ApiEvent:
        return cls(
            event_id=str(value["event_id"]),
            event_type=str(value["event_type"]),
            occurred_at=str(value["occurred_at"]),
            trace_id=str(value.get("trace_id", "")),
            data=dict(value.get("data", {})),
        )
