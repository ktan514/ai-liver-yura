"""Deprecated compatibility import. Use app.shared.plugin_host."""

from app.shared.plugin_host import (
    ActivityDispatcher,
    CommandDispatcher,
    PluginRegistry,
    QueryDispatcher,
)

__all__ = [
    "ActivityDispatcher",
    "CommandDispatcher",
    "PluginRegistry",
    "QueryDispatcher",
]
