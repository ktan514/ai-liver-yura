from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.shared.contracts.plugins.runtime import PluginActivityResult, PluginEvent


class CoreActivityGateway(Protocol):
    async def execute(
        self, capability: str, payload: dict[str, object], trace_id: str
    ) -> PluginActivityResult: ...

    async def publish_event(self, event: PluginEvent) -> None: ...

    def configure_lifecycle_gate(self, gate: Any) -> None: ...

    def configure_comment_moderation(
        self, handler: Callable[[PluginEvent], Awaitable[object]]
    ) -> None: ...

    def cancel_outputs(self) -> bool: ...
