from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.domain.activity_turn_result import ActivityTurnResult
from app.domain.events import AgentEvent


class CoreActivityGateway(Protocol):
    async def execute(
        self, capability: str, payload: dict[str, object], trace_id: str
    ) -> ActivityTurnResult: ...

    async def publish_event(self, event: AgentEvent) -> None: ...

    def configure_lifecycle_gate(self, gate: Any) -> None: ...

    def configure_comment_moderation(
        self, handler: Callable[[AgentEvent], Awaitable[object]]
    ) -> None: ...

    def cancel_outputs(self) -> bool: ...

