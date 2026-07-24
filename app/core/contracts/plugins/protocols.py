"""Deprecated compatibility import. Use Shared Contracts."""

from app.shared.contracts.plugins.registration.protocols import (
    ActivityProvider,
    CommandHandler,
    PluginDescriptor,
    PluginEventSubscriber,
    PluginLifecycle,
    QueryHandler,
)

__all__ = [
    "ActivityProvider",
    "CommandHandler",
    "PluginDescriptor",
    "PluginEventSubscriber",
    "PluginLifecycle",
    "QueryHandler",
]
