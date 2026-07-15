from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.plugins import PluginContext, PluginManager, PluginStatus
from app.domain.activities import Activity


class StubClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class StubGateway:
    def register(self, activity: Activity) -> Activity:
        return activity


class StubLlm:
    async def generate_response(self, activity: Activity) -> str:
        return "{}"


class StubPlugin:
    display_name = "Stub"

    def __init__(
        self,
        plugin_id: str = "stub",
        *,
        fail: bool = False,
        declared: frozenset[str] = frozenset({"test_capability"}),
        available: frozenset[str] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.fail = fail
        self.capabilities = declared
        self._available = declared if available is None else available
        self.initialized = False
        self.shutdown_called = False

    def initialize(self, context: PluginContext) -> None:
        if self.fail:
            raise RuntimeError("failed")
        self.initialized = True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def available_capabilities(self) -> frozenset[str]:
        return self._available if self.initialized else frozenset()


def _context() -> PluginContext:
    return PluginContext(StubLlm(), StubGateway(), StubClock(), {})


def test_plugin_manager_initializes_only_enabled_plugins_and_capabilities() -> None:
    manager = PluginManager()
    enabled = StubPlugin("enabled")
    disabled = StubPlugin("disabled")
    manager.register(enabled)
    manager.register(disabled)

    manager.initialize_enabled_plugins(_context(), {"enabled": True, "disabled": False})

    assert enabled.initialized is True
    assert disabled.initialized is False
    assert manager.status("enabled") == PluginStatus.INITIALIZED
    assert manager.status("disabled") == PluginStatus.DISABLED
    assert manager.get_plugins_by_capability("test_capability") == [enabled]


def test_plugin_manager_rejects_duplicate_id() -> None:
    manager = PluginManager()
    manager.register(StubPlugin())

    with pytest.raises(ValueError):
        manager.register(StubPlugin())


def test_plugin_initialization_failure_is_isolated_and_shutdown_works() -> None:
    manager = PluginManager()
    failed = StubPlugin("failed", fail=True)
    healthy = StubPlugin("healthy")
    manager.register(failed)
    manager.register(healthy)

    manager.initialize_enabled_plugins(_context(), {"failed": True, "healthy": True})
    manager.shutdown_plugins()

    assert manager.status("failed") == PluginStatus.FAILED
    assert manager.status("healthy") == PluginStatus.SHUTDOWN
    assert healthy.shutdown_called is True
    assert manager.list_capabilities() == frozenset()


def test_plugin_manifest_is_not_treated_as_current_availability() -> None:
    manager = PluginManager()
    plugin = StubPlugin(
        declared=frozenset({"healthy", "unavailable"}),
        available=frozenset({"healthy"}),
    )
    manager.register(plugin)

    manager.initialize_enabled_plugins(_context(), {"stub": True})

    assert manager.list_capabilities() == frozenset({"healthy"})
    assert manager.get_plugins_by_capability("unavailable") == []


def test_capability_health_can_be_revoked_and_restored_independently() -> None:
    manager = PluginManager()
    plugin = StubPlugin(declared=frozenset({"first", "second"}))
    manager.register(plugin)
    manager.initialize_enabled_plugins(_context(), {"stub": True})

    manager.set_capability_availability("stub", "first", available=False)

    assert manager.list_capabilities() == frozenset({"second"})
    assert manager.is_capability_available("first", "stub") is False

    manager.set_capability_availability("stub", "first", available=True)

    assert manager.is_capability_available("first", "stub") is True
