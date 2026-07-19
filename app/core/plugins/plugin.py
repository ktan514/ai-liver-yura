"""Deprecated compatibility import. Use Shared Contracts."""

from app.shared.contracts.plugins.runtime import (
    CommandHandler,
    PlannedActivityInterpreter,
    Plugin,
    UserIntentInterpreter,
)

__all__ = [
    "CommandHandler",
    "PlannedActivityInterpreter",
    "Plugin",
    "UserIntentInterpreter",
]
