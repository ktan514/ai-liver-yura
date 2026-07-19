"""Deprecated compatibility import. Use Shared Contracts."""

from app.shared.contracts.plugins.registration.models import (
    CapabilityPolicy,
    CapabilityRegistration,
    EventSubscription,
    PluginActivityRequest,
    PluginActivitySpec,
    PluginHealth,
    PluginHealthStatus,
    PluginRegistration,
)

__all__ = [
    "CapabilityPolicy",
    "CapabilityRegistration",
    "EventSubscription",
    "PluginActivityRequest",
    "PluginActivitySpec",
    "PluginHealth",
    "PluginHealthStatus",
    "PluginRegistration",
]
