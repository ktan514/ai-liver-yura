from __future__ import annotations

from dataclasses import dataclass

from app.core.contracts.plugins import (
    CapabilityRegistration,
    PluginHealth,
    PluginHealthStatus,
    PluginRegistration,
)


@dataclass(frozen=True, slots=True)
class EchoDescriptor:
    plugin_id: str = "sample_echo"
    version: str = "1.0.0"
    capabilities: frozenset[str] = frozenset({"sample.echo", "sample.status"})
    dependencies: tuple[str, ...] = ()


class EchoLifecycle:
    def __init__(self) -> None:
        self.started = False
        self.stop_count = 0

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        if self.started:
            self.stop_count += 1
        self.started = False

    async def health(self) -> PluginHealth:
        status = (
            PluginHealthStatus.HEALTHY if self.started else PluginHealthStatus.STOPPED
        )
        return PluginHealth(status)


class EchoCommand:
    async def handle(self, command: object) -> object:
        return {"echo": command}


class EchoQuery:
    def __init__(self, lifecycle: EchoLifecycle) -> None:
        self._lifecycle = lifecycle

    async def handle(self, query: object) -> object:
        del query
        return {"started": self._lifecycle.started}


def registration(*, enabled: bool = True) -> PluginRegistration:
    lifecycle = EchoLifecycle()
    return PluginRegistration(
        descriptor=EchoDescriptor(),
        lifecycle=lifecycle,
        capability_registrations=(
            CapabilityRegistration("sample.echo"),
            CapabilityRegistration("sample.status"),
        ),
        commands={"sample.echo": EchoCommand()},
        queries={"sample.status": EchoQuery(lifecycle)},
        enabled=enabled,
    )
