from __future__ import annotations

import pytest

from app.core.plugins import PluginContext, PluginManager, SystemClock
from app.domain.activities import Activity, ActivityType
from app.plugins.llm_provider import LlmProviderPlugin


class StubActivityGateway:
    def register(self, activity: Activity) -> Activity:
        return activity


class StubGenerator:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    async def generate_response(self, activity: Activity) -> str:
        if self.error is not None:
            raise self.error
        return f"response:{activity.goal}"


def _initialize(plugin: LlmProviderPlugin) -> PluginManager:
    manager = PluginManager()
    manager.register(plugin)
    manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=plugin,
            activity_gateway=StubActivityGateway(),
            clock=SystemClock(),
            configuration={},
            capability_reporter=manager,
        ),
        {plugin.plugin_id: True},
    )
    return manager


@pytest.mark.asyncio
async def test_llm_provider_plugin_delegates_by_role() -> None:
    plugin = LlmProviderPlugin("character", StubGenerator())
    manager = _initialize(plugin)

    response = await plugin.generate_response(
        Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="挨拶する")
    )

    assert response == "response:挨拶する"
    assert manager.is_capability_available("llm.provider", plugin.plugin_id)
    assert manager.is_capability_available("llm.provider.character", plugin.plugin_id)


@pytest.mark.asyncio
async def test_llm_provider_failure_removes_capabilities_without_crashing_manager() -> (
    None
):
    plugin = LlmProviderPlugin("character", StubGenerator(error=OSError("offline")))
    manager = _initialize(plugin)

    with pytest.raises(OSError, match="offline"):
        await plugin.generate_response(
            Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="挨拶する")
        )

    assert not manager.is_capability_available("llm.provider", plugin.plugin_id)
    assert not manager.is_capability_available(
        "llm.provider.character", plugin.plugin_id
    )
    assert manager.status(plugin.plugin_id) is not None


def test_unconfigured_llm_provider_has_no_available_capability() -> None:
    plugin = LlmProviderPlugin(
        "character",
        StubGenerator(),
        configured_available=False,
    )
    manager = _initialize(plugin)

    assert plugin.available_capabilities() == frozenset()
    assert not manager.is_capability_available(
        "llm.provider.character", plugin.plugin_id
    )
