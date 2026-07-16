from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.core.plugins.plugin import Plugin
from app.utils.trace import TraceLogger


class CapabilityAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CapabilityHealth:
    capability: str
    provider_plugin_id: str
    status: CapabilityAvailability
    failure_reason: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CapabilityRegistry:
    """現在実行可能と確認できたCapabilityだけを保持する許可リスト。"""

    def __init__(self) -> None:
        self._providers: dict[str, dict[str, Plugin]] = {}
        self._health: dict[tuple[str, str], CapabilityHealth] = {}
        self._trace_logger = TraceLogger()

    def register(self, plugin: Plugin, capability: str) -> None:
        providers = self._providers.setdefault(capability, {})
        if plugin.plugin_id in providers:
            return
        providers[plugin.plugin_id] = plugin
        self.update_health(
            plugin.plugin_id,
            capability,
            status=CapabilityAvailability.AVAILABLE,
        )
        self._trace_logger.info(
            "capability_registry:capability_available",
            plugin_id=plugin.plugin_id,
            capability=capability,
        )

    def unregister(self, plugin_id: str, capability: str | None = None) -> None:
        targets = (capability,) if capability is not None else tuple(self._providers)
        for target in targets:
            providers = self._providers.get(target)
            if providers is None or providers.pop(plugin_id, None) is None:
                continue
            self.update_health(
                plugin_id,
                target,
                status=CapabilityAvailability.UNAVAILABLE,
                failure_reason="Capability providerが解除されました。",
            )
            self._trace_logger.info(
                "capability_registry:capability_unavailable",
                plugin_id=plugin_id,
                capability=target,
            )
            if not providers:
                del self._providers[target]

    def is_available(self, capability: str, plugin_id: str | None = None) -> bool:
        providers = self._providers.get(capability, {})
        return bool(providers) if plugin_id is None else plugin_id in providers

    def list_available(self) -> frozenset[str]:
        return frozenset(self._providers)

    def resolve_providers(self, capability: str) -> list[Plugin]:
        return list(self._providers.get(capability, {}).values())

    def update_health(
        self,
        plugin_id: str,
        capability: str,
        *,
        status: CapabilityAvailability,
        failure_reason: str | None = None,
        observed_at: datetime | None = None,
    ) -> CapabilityHealth:
        health = CapabilityHealth(
            capability=capability,
            provider_plugin_id=plugin_id,
            status=status,
            failure_reason=failure_reason,
            observed_at=observed_at or datetime.now(timezone.utc),
        )
        self._health[(capability, plugin_id)] = health
        return health

    def get_health(
        self, capability: str, plugin_id: str | None = None
    ) -> tuple[CapabilityHealth, ...]:
        return tuple(
            health
            for (registered_capability, registered_plugin), health in self._health.items()
            if registered_capability == capability
            and (plugin_id is None or registered_plugin == plugin_id)
        )
