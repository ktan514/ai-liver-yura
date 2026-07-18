from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar, cast

from app.core.contracts.plugins import (
    ActivityProvider,
    CapabilityPolicy,
    CapabilityRegistration,
    CapabilityUnavailable,
    CommandHandler,
    DuplicateCapability,
    PluginDependencyMissing,
    PluginHealth,
    PluginRegistration,
    PluginStartFailed,
    PluginStopFailed,
    PluginUnavailable,
    QueryHandler,
)

HandlerT = TypeVar("HandlerT")


class PluginRegistry:
    """Generic registration and lifecycle boundary with explicit provider policy."""

    def __init__(self) -> None:
        self._registrations: dict[str, PluginRegistration] = {}
        self._capabilities: dict[str, list[tuple[str, CapabilityRegistration]]] = {}
        self._started: list[str] = []

    def register(self, registration: PluginRegistration) -> None:
        plugin_id = registration.descriptor.plugin_id
        if plugin_id in self._registrations:
            raise ValueError(f"Plugin already registered: {plugin_id}")
        declared = registration.descriptor.capabilities
        provided = {item.capability for item in registration.capability_registrations}
        exposed = set(registration.commands) | set(registration.queries) | set(
            registration.activity_providers
        )
        if provided != declared or not exposed <= provided:
            raise ValueError(f"Plugin capability declaration mismatch: {plugin_id}")
        for item in registration.capability_registrations:
            current = self._capabilities.get(item.capability, [])
            if current and (
                item.policy == CapabilityPolicy.SINGLE
                or any(existing.policy == CapabilityPolicy.SINGLE for _, existing in current)
            ):
                raise DuplicateCapability(item.capability)
            if current and any(existing.policy != item.policy for _, existing in current):
                raise DuplicateCapability(item.capability)
        self._registrations[plugin_id] = registration
        if not registration.enabled:
            return
        for item in registration.capability_registrations:
            self._capabilities.setdefault(item.capability, []).append((plugin_id, item))

    def unregister(self, plugin_id: str) -> None:
        if plugin_id in self._started:
            raise RuntimeError("Started plugins must be stopped before unregister")
        self._registrations.pop(plugin_id, None)
        for capability, providers in tuple(self._capabilities.items()):
            remaining = [item for item in providers if item[0] != plugin_id]
            if remaining:
                self._capabilities[capability] = remaining
            else:
                del self._capabilities[capability]

    def registration(self, plugin_id: str) -> PluginRegistration | None:
        return self._registrations.get(plugin_id)

    def list_enabled(self) -> tuple[PluginRegistration, ...]:
        return tuple(item for item in self._registrations.values() if item.enabled)

    def resolve_plugin(self, plugin_id: str) -> PluginRegistration:
        registration = self._registrations.get(plugin_id)
        if registration is None or not registration.enabled:
            raise PluginUnavailable(f"Plugin is unavailable: {plugin_id}", plugin_id=plugin_id)
        return registration

    def resolve_command(
        self, capability: str, *, provider: str | None = None
    ) -> CommandHandler[Any, Any]:
        return cast(
            CommandHandler[Any, Any], self._resolve_handler(capability, "commands", provider)
        )

    def resolve_query(
        self, capability: str, *, provider: str | None = None
    ) -> QueryHandler[Any, Any]:
        return cast(
            QueryHandler[Any, Any], self._resolve_handler(capability, "queries", provider)
        )

    def resolve_activity_provider(
        self, capability: str, *, provider: str | None = None
    ) -> ActivityProvider:
        return cast(
            ActivityProvider,
            self._resolve_handler(capability, "activity_providers", provider),
        )

    def _resolve_handler(
        self, capability: str, member: str, provider: str | None
    ) -> Any:
        providers = self._capabilities.get(capability, [])
        eligible = [
            (plugin_id, item)
            for plugin_id, item in providers
            if capability in getattr(self._registrations[plugin_id], member)
        ]
        plugin_id = self._select_provider(capability, eligible, provider)
        return getattr(self._registrations[plugin_id], member)[capability]

    @staticmethod
    def _select_provider(
        capability: str,
        providers: Iterable[tuple[str, CapabilityRegistration]],
        requested: str | None,
    ) -> str:
        available = list(providers)
        if requested is not None:
            if any(plugin_id == requested for plugin_id, _ in available):
                return requested
            raise CapabilityUnavailable(capability, provider=requested)
        if not available:
            raise CapabilityUnavailable(capability)
        policy = available[0][1].policy
        if policy in {
            CapabilityPolicy.NAMED_PROVIDER,
            CapabilityPolicy.EXPLICIT_SELECTION,
        }:
            raise CapabilityUnavailable(capability)
        if len(available) == 1:
            return available[0][0]
        if policy == CapabilityPolicy.PRIORITY:
            ranked = sorted(available, key=lambda item: (-item[1].priority, item[0]))
            if ranked[0][1].priority == ranked[1][1].priority:
                raise CapabilityUnavailable(capability)
            return ranked[0][0]
        raise CapabilityUnavailable(capability)

    async def start_all(self) -> None:
        enabled_ids = {item.descriptor.plugin_id for item in self.list_enabled()}
        registrations = {
            item.descriptor.plugin_id: item for item in self.list_enabled()
        }
        ordered: list[PluginRegistration] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(plugin_id: str) -> None:
            if plugin_id in visited:
                return
            if plugin_id in visiting:
                raise PluginDependencyMissing(plugin_id, "dependency_cycle")
            if plugin_id not in registrations:
                parent = next(iter(visiting), plugin_id)
                raise PluginDependencyMissing(parent, plugin_id)
            visiting.add(plugin_id)
            registration = registrations[plugin_id]
            for dependency in registration.descriptor.dependencies:
                visit(dependency)
            visiting.remove(plugin_id)
            visited.add(plugin_id)
            ordered.append(registration)

        for plugin_id in registrations:
            visit(plugin_id)
        for registration in ordered:
            plugin_id = registration.descriptor.plugin_id
            for dependency in registration.descriptor.dependencies:
                if dependency not in enabled_ids:
                    raise PluginDependencyMissing(plugin_id, dependency)
        for registration in ordered:
            plugin_id = registration.descriptor.plugin_id
            if plugin_id in self._started:
                continue
            try:
                await registration.lifecycle.start()
            except Exception as error:
                await self.stop_all()
                raise PluginStartFailed(str(error), plugin_id=plugin_id) from error
            self._started.append(plugin_id)

    async def stop_all(self) -> None:
        failures: list[PluginStopFailed] = []
        for plugin_id in reversed(tuple(self._started)):
            registration = self._registrations[plugin_id]
            try:
                await registration.lifecycle.stop()
            except Exception as error:
                failures.append(PluginStopFailed(str(error), plugin_id=plugin_id))
            finally:
                self._started.remove(plugin_id)
        if failures:
            raise failures[0]

    async def health(self) -> dict[str, PluginHealth]:
        return {
            registration.descriptor.plugin_id: await registration.lifecycle.health()
            for registration in self.list_enabled()
        }
