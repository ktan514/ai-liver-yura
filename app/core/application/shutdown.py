from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.shared.plugin_host import PluginRegistry

AsyncStep = Callable[[], Awaitable[None]]


class ApplicationShutdownCoordinator:
    """Owns process-level shutdown order; plugins only stop their own resources."""

    def __init__(self, plugins: PluginRegistry) -> None:
        self._plugins = plugins
        self._completed = False

    async def shutdown(
        self,
        *,
        stop_runtime: AsyncStep,
        stop_framework: AsyncStep,
        close_logging: AsyncStep,
    ) -> None:
        if self._completed:
            return
        await self._plugins.stop_all()
        await stop_runtime()
        await stop_framework()
        await close_logging()
        self._completed = True
