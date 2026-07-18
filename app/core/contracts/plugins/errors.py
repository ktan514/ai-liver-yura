from __future__ import annotations


class PluginContractError(RuntimeError):
    """Base error safe to translate at framework boundaries."""

    code = "plugin.error"

    def __init__(self, message: str, *, plugin_id: str | None = None) -> None:
        super().__init__(message)
        self.plugin_id = plugin_id


class PluginUnavailable(PluginContractError):
    code = "plugin.unavailable"


class CapabilityUnavailable(PluginContractError):
    code = "capability.unavailable"

    def __init__(self, capability: str, *, provider: str | None = None) -> None:
        super().__init__(f"Capability is unavailable: {capability}", plugin_id=provider)
        self.capability = capability


class PluginDependencyMissing(PluginContractError):
    code = "plugin.dependency_missing"

    def __init__(self, plugin_id: str, dependency: str) -> None:
        super().__init__(
            f"Plugin dependency is missing: {plugin_id} -> {dependency}",
            plugin_id=plugin_id,
        )
        self.dependency = dependency


class DuplicateCapability(PluginContractError):
    code = "capability.duplicate"

    def __init__(self, capability: str) -> None:
        super().__init__(f"Duplicate single-provider capability: {capability}")
        self.capability = capability


class PluginStartFailed(PluginContractError):
    code = "plugin.start_failed"


class PluginStopFailed(PluginContractError):
    code = "plugin.stop_failed"


class CommandRejected(PluginContractError):
    code = "command.rejected"

    def __init__(
        self,
        message: str,
        *,
        plugin_id: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        super().__init__(message, plugin_id=plugin_id)
        self.reason_code = reason_code or self.code


class QueryFailed(PluginContractError):
    code = "query.failed"
