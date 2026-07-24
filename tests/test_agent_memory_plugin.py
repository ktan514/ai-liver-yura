from __future__ import annotations

from app.core.plugins import PluginContext, PluginManager, SystemClock
from app.plugins.agent_memory import AgentMemoryPlugin
from app.shared.contracts.memory import AgentMemorySnapshot


class InMemoryStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.snapshot = AgentMemorySnapshot()
        self.fail = fail

    def load(self) -> AgentMemorySnapshot:
        return self.snapshot

    def save(self, snapshot: AgentMemorySnapshot) -> None:
        if self.fail:
            raise OSError("offline")
        self.snapshot = snapshot


class UnusedGateway:
    async def generate_response(self, activity: object) -> str:
        return ""

    def register(self, activity: object) -> object:
        return activity


def _initialize(plugin: AgentMemoryPlugin) -> PluginManager:
    manager = PluginManager()
    manager.register(plugin)
    gateway = UnusedGateway()
    manager.initialize_enabled_plugins(
        PluginContext(gateway, gateway, SystemClock(), {}, manager),
        {plugin.plugin_id: True},
    )
    return manager


def test_agent_memory_plugin_round_trip_through_shared_snapshot() -> None:
    plugin = AgentMemoryPlugin(InMemoryStore())
    manager = _initialize(plugin)
    snapshot = AgentMemorySnapshot()

    plugin.save(snapshot)

    assert plugin.load() == snapshot
    assert manager.is_capability_available("memory.agent_state", plugin.plugin_id)


def test_agent_memory_plugin_revokes_capability_on_store_failure() -> None:
    store = InMemoryStore(fail=True)
    plugin = AgentMemoryPlugin(store)
    manager = _initialize(plugin)

    try:
        plugin.save(AgentMemorySnapshot())
    except OSError:
        pass

    assert not manager.is_capability_available("memory.agent_state", plugin.plugin_id)
