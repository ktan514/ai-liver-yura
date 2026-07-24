from __future__ import annotations

import pytest

from app.core.plugins import PluginContext, PluginManager, SystemClock
from app.domain.activities import Activity
from app.domain.relationships import RelationshipIdentity, RelationshipMemory
from app.plugins.relationship_memory import RelationshipMemoryPlugin


class StubActivityGateway:
    def register(self, activity: Activity) -> Activity:
        return activity


class InMemoryStore:
    def __init__(self, *, fail_save: bool = False) -> None:
        self.memory = RelationshipMemory()
        self.fail_save = fail_save

    def load(self) -> RelationshipMemory:
        return self.memory

    def save(self, memory: RelationshipMemory) -> None:
        if self.fail_save:
            raise OSError("disk offline")
        self.memory = memory


def _initialize(plugin: RelationshipMemoryPlugin[RelationshipMemory]) -> PluginManager:
    manager = PluginManager()
    manager.register(plugin)
    manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=_UnusedGenerator(),
            activity_gateway=StubActivityGateway(),
            clock=SystemClock(),
            configuration={},
            capability_reporter=manager,
        ),
        {plugin.plugin_id: True},
    )
    return manager


class _UnusedGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return ""


def test_relationship_memory_plugin_round_trip() -> None:
    store = InMemoryStore()
    plugin = RelationshipMemoryPlugin(store)
    manager = _initialize(plugin)
    memory = RelationshipMemory().record(
        RelationshipIdentity("viewer-1", "Alice"),
        event_id="event-1",
    )

    plugin.save(memory)

    assert plugin.load() == memory
    assert manager.is_capability_available("memory.relationship", plugin.plugin_id)


def test_relationship_memory_plugin_removes_capability_on_store_failure() -> None:
    plugin = RelationshipMemoryPlugin(InMemoryStore(fail_save=True))
    manager = _initialize(plugin)

    with pytest.raises(OSError, match="disk offline"):
        plugin.save(RelationshipMemory())

    assert not manager.is_capability_available("memory.relationship", plugin.plugin_id)
