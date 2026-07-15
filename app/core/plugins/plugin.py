from __future__ import annotations

from typing import Protocol

from app.core.plugins.plugin_context import PluginContext
from app.core.plugins.plugin_result import PluginExecutionResult, PluginIntentResult
from app.domain.behavior import ActivityPlan


class Plugin(Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    def available_capabilities(self) -> frozenset[str]: ...

    def initialize(self, context: PluginContext) -> None: ...

    def shutdown(self) -> None: ...


class UserIntentInterpreter(Protocol):
    async def interpret_user_text(self, text: str) -> PluginIntentResult: ...


class PlannedActivityInterpreter(Protocol):
    async def interpret_activity_plan(
        self, plan: ActivityPlan, text: str
    ) -> PluginIntentResult: ...


class CommandHandler(Protocol):
    async def execute_command(self, result: PluginIntentResult) -> PluginExecutionResult: ...
