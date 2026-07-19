"""Deprecated compatibility import. Use Shared Contracts."""

from app.shared.contracts.plugins.registration.errors import (
    CapabilityUnavailable,
    CommandRejected,
    DuplicateCapability,
    PluginContractError,
    PluginDependencyMissing,
    PluginStartFailed,
    PluginStopFailed,
    PluginUnavailable,
    QueryFailed,
)

__all__ = [
    "CapabilityUnavailable",
    "CommandRejected",
    "DuplicateCapability",
    "PluginContractError",
    "PluginDependencyMissing",
    "PluginStartFailed",
    "PluginStopFailed",
    "PluginUnavailable",
    "QueryFailed",
]
