from __future__ import annotations

from app.core.plugins.plugin import Plugin
from app.utils.trace import TraceLogger


class CapabilityRegistry:
    """現在実行可能と確認できたCapabilityだけを保持する許可リスト。"""

    def __init__(self) -> None:
        self._providers: dict[str, dict[str, Plugin]] = {}
        self._trace_logger = TraceLogger()

    def register(self, plugin: Plugin, capability: str) -> None:
        providers = self._providers.setdefault(capability, {})
        if plugin.plugin_id in providers:
            return
        providers[plugin.plugin_id] = plugin
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
