"""Deprecated compatibility import. Use Shared Contracts."""

from app.shared.contracts.plugins.runtime import (
    MemoryPolicy,
    PluginActivityRequest,
    PluginActivityState,
    PluginActivityStatus,
    PluginCommand,
    PluginExecutionResult,
    PluginIntentResult,
    PromptFragment,
)

__all__ = [
    "MemoryPolicy",
    "PluginActivityRequest",
    "PluginActivityState",
    "PluginActivityStatus",
    "PluginCommand",
    "PluginExecutionResult",
    "PluginIntentResult",
    "PromptFragment",
]
