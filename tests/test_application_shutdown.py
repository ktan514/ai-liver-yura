from __future__ import annotations

import pytest

from app.core.application.plugins import PluginRegistry
from app.core.application.shutdown import ApplicationShutdownCoordinator
from tests.fixtures.plugins.sample_echo_plugin import EchoLifecycle, registration


@pytest.mark.asyncio
async def test_shutdown_coordinator_stops_plugins_before_runtime_framework_and_logging() -> None:
    registry = PluginRegistry()
    item = registration()
    registry.register(item)
    await registry.start_all()
    order: list[str] = []

    async def step(name: str) -> None:
        lifecycle = item.lifecycle
        assert isinstance(lifecycle, EchoLifecycle)
        assert lifecycle.started is False
        order.append(name)

    coordinator = ApplicationShutdownCoordinator(registry)
    await coordinator.shutdown(
        stop_runtime=lambda: step("runtime"),
        stop_framework=lambda: step("framework"),
        close_logging=lambda: step("logging"),
    )
    await coordinator.shutdown(
        stop_runtime=lambda: step("runtime-again"),
        stop_framework=lambda: step("framework-again"),
        close_logging=lambda: step("logging-again"),
    )
    assert order == ["runtime", "framework", "logging"]
