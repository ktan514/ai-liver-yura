from __future__ import annotations

from typing import Any

from app.shared.contracts.plugins.registration import (
    CommandRejected,
    PluginActivityRequest,
    QueryFailed,
)
from app.shared.plugin_host.registry import PluginRegistry


class CommandDispatcher:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    async def dispatch(
        self, capability: str, command: Any, *, provider: str | None = None
    ) -> Any:
        handler = self._registry.resolve_command(capability, provider=provider)
        try:
            return await handler.handle(command)
        except CommandRejected:
            raise
        except Exception as error:
            raise CommandRejected(
                f"Command handler rejected {capability}", plugin_id=provider
            ) from error


class QueryDispatcher:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    async def dispatch(
        self, capability: str, query: Any = None, *, provider: str | None = None
    ) -> Any:
        handler = self._registry.resolve_query(capability, provider=provider)
        try:
            return await handler.handle(query)
        except QueryFailed:
            raise
        except Exception as error:
            raise QueryFailed(
                f"Query handler failed {capability}", plugin_id=provider
            ) from error


class ActivityDispatcher:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    async def dispatch(
        self, request: PluginActivityRequest, *, provider: str | None = None
    ) -> Any:
        activity_provider = self._registry.resolve_activity_provider(
            request.capability, provider=provider
        )
        return await activity_provider.create_activity(request)
