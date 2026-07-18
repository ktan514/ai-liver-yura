from __future__ import annotations

from typing import Any, Protocol, TypeVar

if False:  # pragma: no cover - imported only by static type checkers
    from app.core.contracts.plugins.models import (
        EventSubscription,
        PluginActivityRequest,
        PluginHealth,
    )

CommandT = TypeVar("CommandT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)
QueryT = TypeVar("QueryT", contravariant=True)
ViewT = TypeVar("ViewT", covariant=True)


class PluginDescriptor(Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    @property
    def dependencies(self) -> tuple[str, ...]: ...


class PluginLifecycle(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def health(self) -> PluginHealth: ...


class CommandHandler(Protocol[CommandT, ResultT]):
    async def handle(self, command: CommandT) -> ResultT: ...


class QueryHandler(Protocol[QueryT, ViewT]):
    async def handle(self, query: QueryT) -> ViewT: ...


class ActivityProvider(Protocol):
    async def create_activity(self, request: PluginActivityRequest) -> Any: ...


class PluginEventSubscriber(Protocol):
    def subscriptions(self) -> tuple[EventSubscription, ...]: ...

