from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from app.core.application.plugins import (
    CommandDispatcher,
    PluginRegistry,
    QueryDispatcher,
)
from app.core.contracts.plugins import (
    CapabilityPolicy,
    CapabilityRegistration,
    CapabilityUnavailable,
    DuplicateCapability,
    PluginDependencyMissing,
    PluginHealth,
    PluginHealthStatus,
    PluginRegistration,
)
from app.shared.contracts.plugins.registration import (
    PluginActivityRequest as SharedPluginActivityRequest,
)
from tests.fixtures.plugins.sample_echo_plugin import (
    EchoDescriptor,
    EchoLifecycle,
    registration,
)


@pytest.mark.asyncio
async def test_sample_plugin_registers_dispatches_and_stops_without_core_changes() -> (
    None
):
    registry = PluginRegistry()
    item = registration()
    registry.register(item)

    await registry.start_all()
    assert await CommandDispatcher(registry).dispatch("sample.echo", "hello") == {
        "echo": "hello"
    }
    assert await QueryDispatcher(registry).dispatch("sample.status") == {
        "started": True
    }
    assert (await registry.health())["sample_echo"].status == PluginHealthStatus.HEALTHY
    await registry.stop_all()
    await registry.stop_all()
    assert isinstance(item.lifecycle, EchoLifecycle)
    assert item.lifecycle.stop_count == 1


def test_disabled_plugin_is_not_resolvable() -> None:
    registry = PluginRegistry()
    registry.register(registration(enabled=False))
    assert registry.list_enabled() == ()
    with pytest.raises(CapabilityUnavailable):
        registry.resolve_command("sample.echo")


def test_single_capability_rejects_duplicate_provider() -> None:
    registry = PluginRegistry()
    registry.register(registration())
    duplicate = registration()
    duplicate = replace(
        duplicate,
        descriptor=replace(duplicate.descriptor, plugin_id="other_echo"),
    )
    with pytest.raises(DuplicateCapability):
        registry.register(duplicate)


@dataclass(frozen=True, slots=True)
class PriorityDescriptor:
    plugin_id: str
    capabilities: frozenset[str] = frozenset({"shared.query"})
    dependencies: tuple[str, ...] = ()
    version: str = "1"


class ValueQuery:
    def __init__(self, value: str) -> None:
        self.value = value

    async def handle(self, query: object) -> str:
        del query
        return self.value


def priority_registration(plugin_id: str, priority: int) -> PluginRegistration:
    return PluginRegistration(
        descriptor=PriorityDescriptor(plugin_id),
        lifecycle=EchoLifecycle(),
        capability_registrations=(
            CapabilityRegistration(
                "shared.query", CapabilityPolicy.PRIORITY, priority=priority
            ),
        ),
        queries={"shared.query": ValueQuery(plugin_id)},
    )


@pytest.mark.asyncio
async def test_priority_and_explicit_provider_resolution_are_deterministic() -> None:
    registry = PluginRegistry()
    registry.register(priority_registration("low", 1))
    registry.register(priority_registration("high", 10))
    dispatcher = QueryDispatcher(registry)
    assert await dispatcher.dispatch("shared.query") == "high"
    assert await dispatcher.dispatch("shared.query", provider="low") == "low"


@pytest.mark.asyncio
async def test_named_provider_policy_never_selects_implicitly() -> None:
    item = priority_registration("named", 0)
    item = replace(
        item,
        capability_registrations=(
            CapabilityRegistration("shared.query", CapabilityPolicy.NAMED_PROVIDER),
        ),
    )
    registry = PluginRegistry()
    registry.register(item)
    dispatcher = QueryDispatcher(registry)
    with pytest.raises(CapabilityUnavailable):
        await dispatcher.dispatch("shared.query")
    assert await dispatcher.dispatch("shared.query", provider="named") == "named"


@pytest.mark.asyncio
async def test_missing_dependency_prevents_lifecycle_start() -> None:
    registry = PluginRegistry()
    item = registration()
    descriptor = EchoDescriptor(dependencies=("missing",))
    registry.register(replace(item, descriptor=descriptor))
    with pytest.raises(PluginDependencyMissing):
        await registry.start_all()


class ActivityProvider:
    async def create_activity(self, request: object) -> object:
        return request


@pytest.mark.asyncio
async def test_activity_provider_dispatch() -> None:
    from app.core.application.plugins import ActivityDispatcher
    from app.core.contracts.plugins import PluginActivityRequest

    registry = PluginRegistry()
    lifecycle = EchoLifecycle()
    registry.register(
        PluginRegistration(
            descriptor=PriorityDescriptor(
                "activity", capabilities=frozenset({"sample.activity"})
            ),
            lifecycle=lifecycle,
            capability_registrations=(CapabilityRegistration("sample.activity"),),
            activity_providers={"sample.activity": ActivityProvider()},
        )
    )
    request = PluginActivityRequest("sample.activity", {"text": "hi"}, "trace")
    assert await ActivityDispatcher(registry).dispatch(request) is request


class HealthyLifecycle(EchoLifecycle):
    async def health(self) -> PluginHealth:
        return PluginHealth(PluginHealthStatus.HEALTHY)


def test_legacy_plugin_contract_import_reexports_shared_contract() -> None:
    from app.core.contracts.plugins import (
        PluginActivityRequest as LegacyPluginActivityRequest,
    )

    assert LegacyPluginActivityRequest is SharedPluginActivityRequest
