from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.domain.activities import Activity
from app.ports.response_generator import ResponseGenerator


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ActivityGateway(Protocol):
    def register(self, activity: Activity) -> Activity: ...


@dataclass(frozen=True, slots=True)
class PluginContext:
    llm_gateway: ResponseGenerator
    activity_gateway: ActivityGateway
    clock: Clock
    configuration: Mapping[str, object]
