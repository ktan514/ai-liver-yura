"""Deprecated compatibility import. Use Shared Contracts."""

from app.shared.contracts.plugins.runtime import (
    ActivityGateway,
    CapabilityReporter,
    Clock,
    PluginContext,
    ResponseGenerationGateway,
    SystemClock,
)

__all__ = [
    "ActivityGateway",
    "CapabilityReporter",
    "Clock",
    "PluginContext",
    "ResponseGenerationGateway",
    "SystemClock",
]
