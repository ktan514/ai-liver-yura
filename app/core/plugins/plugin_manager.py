from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import cast

from app.core.plugins.capability_registry import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRegistry,
)
from app.shared.contracts.activity import ActivityDefinition
from app.shared.contracts.plugins.runtime import Plugin, PluginContext
from app.utils.trace import TraceLogger


class PluginStatus(str, Enum):
    REGISTERED = "registered"
    DISABLED = "disabled"
    INITIALIZED = "initialized"
    FAILED = "failed"
    SHUTDOWN = "shutdown"


class PluginManager:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._statuses: dict[str, PluginStatus] = {}
        self._contexts: dict[str, PluginContext] = {}
        self._capabilities = CapabilityRegistry()
        self._trace_logger = TraceLogger()

    def register(self, plugin: Plugin) -> None:
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"Pluginは登録済みです: {plugin.plugin_id}")
        self._plugins[plugin.plugin_id] = plugin
        self._statuses[plugin.plugin_id] = PluginStatus.REGISTERED
        self._trace_logger.info(
            "plugin_manager:plugin_registered",
            plugin_id=plugin.plugin_id,
            capabilities=sorted(plugin.capabilities),
        )

    def initialize_enabled_plugins(
        self,
        context: PluginContext,
        enabled: dict[str, bool],
    ) -> None:
        for plugin_id, plugin in self._plugins.items():
            if not enabled.get(plugin_id, False):
                self._contexts.pop(plugin_id, None)
                self._capabilities.unregister(plugin_id)
                if self._statuses.get(plugin_id) == PluginStatus.INITIALIZED:
                    try:
                        plugin.shutdown()
                    except Exception as error:
                        self._trace_logger.error(
                            "plugin_manager:plugin_shutdown_failed",
                            plugin_id=plugin_id,
                            error_type=type(error).__name__,
                        )
                self._statuses[plugin_id] = PluginStatus.DISABLED
                self._trace_logger.info(
                    "plugin_manager:plugin_disabled", plugin_id=plugin_id
                )
                continue
            self._contexts[plugin_id] = context
            self._trace_logger.info(
                "plugin_manager:plugin_enabled", plugin_id=plugin_id
            )
            try:
                plugin.initialize(context)
            except Exception as error:
                self._capabilities.unregister(plugin_id)
                self._statuses[plugin_id] = PluginStatus.FAILED
                self._trace_logger.error(
                    "plugin_manager:plugin_initialization_failed",
                    plugin_id=plugin_id,
                    error_type=type(error).__name__,
                )
                continue
            self._statuses[plugin_id] = PluginStatus.INITIALIZED
            self._trace_logger.info(
                "plugin_manager:plugin_initialized", plugin_id=plugin_id
            )
            declared = plugin.capabilities
            try:
                available = plugin.available_capabilities()
            except Exception as error:
                self._statuses[plugin_id] = PluginStatus.FAILED
                self._capabilities.unregister(plugin_id)
                try:
                    plugin.shutdown()
                except Exception:
                    pass
                self._trace_logger.error(
                    "plugin_manager:capability_health_check_failed",
                    plugin_id=plugin_id,
                    error_type=type(error).__name__,
                )
                continue
            undeclared = available - declared
            if undeclared:
                self._statuses[plugin_id] = PluginStatus.FAILED
                self._capabilities.unregister(plugin_id)
                try:
                    plugin.shutdown()
                except Exception:
                    pass
                self._trace_logger.error(
                    "plugin_manager:undeclared_capability_rejected",
                    plugin_id=plugin_id,
                    capabilities=sorted(undeclared),
                )
                continue
            for capability in available:
                self._capabilities.register(plugin, capability)

    def recover_plugin(self, plugin_id: str) -> bool:
        """明示的な再接続要求でPluginを再初期化し、Capabilityを再検出する。"""

        plugin = self._plugins.get(plugin_id)
        context = self._contexts.get(plugin_id)
        status = self._statuses.get(plugin_id)
        if plugin is None:
            raise ValueError(f"未登録のPluginです: {plugin_id}")
        if context is None or status in {
            PluginStatus.REGISTERED,
            PluginStatus.DISABLED,
            PluginStatus.SHUTDOWN,
        }:
            return False

        self._capabilities.unregister(plugin_id)
        try:
            plugin.shutdown()
        except Exception as error:
            self._trace_logger.warning(
                "plugin_manager:plugin_recovery_shutdown_failed",
                plugin_id=plugin_id,
                error_type=type(error).__name__,
            )
        try:
            plugin.initialize(context)
            available = plugin.available_capabilities()
            undeclared = available - plugin.capabilities
            if undeclared:
                raise ValueError(
                    "Pluginが未宣言Capabilityを復旧時に公開しました: "
                    + ",".join(sorted(undeclared))
                )
        except Exception as error:
            self._statuses[plugin_id] = PluginStatus.FAILED
            self._trace_logger.error(
                "plugin_manager:plugin_recovery_failed",
                plugin_id=plugin_id,
                error_type=type(error).__name__,
            )
            return False

        self._statuses[plugin_id] = PluginStatus.INITIALIZED
        for capability in available:
            self._capabilities.register(plugin, capability)
        self._trace_logger.info(
            "plugin_manager:plugin_recovered",
            plugin_id=plugin_id,
            capabilities=sorted(available),
        )
        return bool(available)

    def shutdown_plugins(self) -> None:
        for plugin_id, plugin in reversed(tuple(self._plugins.items())):
            if self._statuses.get(plugin_id) != PluginStatus.INITIALIZED:
                continue
            self._capabilities.unregister(plugin_id)
            try:
                plugin.shutdown()
            except Exception as error:
                self._trace_logger.error(
                    "plugin_manager:plugin_shutdown_failed",
                    plugin_id=plugin_id,
                    error_type=type(error).__name__,
                )
            self._statuses[plugin_id] = PluginStatus.SHUTDOWN
            self._trace_logger.info(
                "plugin_manager:plugin_shutdown", plugin_id=plugin_id
            )

    def get_plugin(self, plugin_id: str) -> Plugin | None:
        if self._statuses.get(plugin_id) != PluginStatus.INITIALIZED:
            return None
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> list[Plugin]:
        return list(self._plugins.values())

    def list_activity_definitions(self) -> tuple[ActivityDefinition, ...]:
        definitions: list[ActivityDefinition] = []
        for plugin in self._plugins.values():
            provider = getattr(plugin, "activity_definitions", None)
            if callable(provider):
                definitions.extend(cast(tuple[ActivityDefinition, ...], provider()))
        return tuple(definitions)

    def active_activity_definition(self) -> ActivityDefinition | None:
        for plugin in self._plugins.values():
            if self._statuses.get(plugin.plugin_id) != PluginStatus.INITIALIZED:
                continue
            provider = getattr(plugin, "active_activity_definition", None)
            if callable(provider):
                definition = cast(ActivityDefinition | None, provider())
                if definition is not None:
                    return definition
        return None

    def list_capabilities(self) -> frozenset[str]:
        return self._capabilities.list_available()

    def get_plugins_by_capability(self, capability: str) -> list[Plugin]:
        return self._capabilities.resolve_providers(capability)

    def is_capability_available(
        self, capability: str, plugin_id: str | None = None
    ) -> bool:
        return self._capabilities.is_available(capability, plugin_id)

    def set_capability_availability(
        self, plugin_id: str, capability: str, *, available: bool
    ) -> None:
        plugin = self._plugins.get(plugin_id)
        if plugin is None or self._statuses.get(plugin_id) != PluginStatus.INITIALIZED:
            raise ValueError(f"初期化済みPluginではありません: {plugin_id}")
        if capability not in plugin.capabilities:
            raise ValueError(f"Pluginが宣言していないCapabilityです: {capability}")
        if available:
            if capability not in plugin.available_capabilities():
                raise ValueError(f"Pluginが現在利用可能としていません: {capability}")
            self._capabilities.register(plugin, capability)
        else:
            self._capabilities.unregister(plugin_id, capability)

    def set_capability_health(
        self,
        plugin_id: str,
        capability: str,
        *,
        status: CapabilityAvailability,
        failure_reason: str | None = None,
        observed_at: datetime | None = None,
    ) -> CapabilityHealth:
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            raise ValueError(f"未登録のPluginです: {plugin_id}")
        if capability not in plugin.capabilities:
            raise ValueError(f"Pluginが宣言していないCapabilityです: {capability}")
        if self._statuses.get(plugin_id) == PluginStatus.INITIALIZED:
            if status in {
                CapabilityAvailability.AVAILABLE,
                CapabilityAvailability.DEGRADED,
            }:
                self._capabilities.register(plugin, capability)
            else:
                self._capabilities.unregister(plugin_id, capability)
        return self._capabilities.update_health(
            plugin_id,
            capability,
            status=status,
            failure_reason=failure_reason,
            observed_at=observed_at,
        )

    def get_capability_health(
        self, capability: str, plugin_id: str | None = None
    ) -> tuple[CapabilityHealth, ...]:
        return self._capabilities.get_health(capability, plugin_id)

    def status(self, plugin_id: str) -> PluginStatus | None:
        return self._statuses.get(plugin_id)
