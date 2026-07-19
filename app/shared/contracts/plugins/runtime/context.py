from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ActivityGateway(Protocol):
    def register(self, activity: Any) -> Any: ...


class ResponseGenerationGateway(Protocol):
    async def generate_response(self, activity: Any) -> str: ...


@dataclass(frozen=True, slots=True)
class PluginLlmRequest:
    purpose: str
    prompt: str
    context: Mapping[str, object]
    request_id: str = field(default_factory=lambda: str(uuid4()))


class CapabilityReporter(Protocol):
    def set_capability_availability(
        self,
        plugin_id: str,
        capability: str,
        *,
        available: bool,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PluginContext:
    llm_gateway: ResponseGenerationGateway
    activity_gateway: ActivityGateway
    clock: Clock
    configuration: Mapping[str, object]
    capability_reporter: CapabilityReporter | None = None
