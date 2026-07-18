from __future__ import annotations

from app.core.plugins import (
    CapabilityAvailability,
    CapabilityRegistry,
    StaticCapabilityProvider,
)


def test_capability_health_preserves_provider_reason_and_binary_compatibility() -> None:
    registry = CapabilityRegistry()
    plugin = StaticCapabilityProvider(
        "test_provider", frozenset({"stream.session.prepare"})
    )
    registry.register(plugin, "stream.session.prepare")
    registry.update_health(
        plugin.plugin_id,
        "stream.session.prepare",
        status=CapabilityAvailability.DEGRADED,
        failure_reason="partial",
    )
    health = registry.get_health("stream.session.prepare", plugin.plugin_id)[0]
    assert registry.is_available("stream.session.prepare") is True
    assert health.status == CapabilityAvailability.DEGRADED
    assert health.failure_reason == "partial"
    assert health.provider_plugin_id == plugin.plugin_id
