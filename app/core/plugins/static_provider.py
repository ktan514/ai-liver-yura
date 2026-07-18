from __future__ import annotations

from dataclasses import dataclass

from app.core.plugins.plugin_context import PluginContext


@dataclass(frozen=True, slots=True)
class StaticCapabilityProvider:
    """Compatibility provider for capability health sources without Plugin imports."""

    plugin_id: str
    capabilities: frozenset[str]
    display_name: str = "Capability Provider"

    def available_capabilities(self) -> frozenset[str]:
        return self.capabilities

    def initialize(self, context: PluginContext) -> None:
        del context

    def shutdown(self) -> None:
        return None

