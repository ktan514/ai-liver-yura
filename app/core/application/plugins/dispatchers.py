"""Deprecated compatibility import. Use app.shared.plugin_host."""

from app.shared.plugin_host.dispatchers import (
    ActivityDispatcher,
    CommandDispatcher,
    QueryDispatcher,
)

__all__ = ["ActivityDispatcher", "CommandDispatcher", "QueryDispatcher"]
