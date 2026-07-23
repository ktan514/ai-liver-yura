from __future__ import annotations

import logging

from app.ports.avatar_output import AvatarOutputPort
from app.shared.contracts.plugins.runtime import CapabilityReporter, PluginContext


class AvatarOutputPlugin:
    """Live2D/3D Adapterを任意Capabilityとして隔離するPlugin。"""

    plugin_id = "avatar_output"
    display_name = "Avatar Output"
    EXPRESSION_CAPABILITY = "output.avatar.expression"
    GESTURE_CAPABILITY = "output.avatar.gesture"

    def __init__(self, adapter: AvatarOutputPort | None) -> None:
        self._adapter = adapter
        self._initialized = False
        self._healthy = False
        self._capability_reporter: CapabilityReporter | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(
            {self.EXPRESSION_CAPABILITY, self.GESTURE_CAPABILITY}
        )

    def available_capabilities(self) -> frozenset[str]:
        if self._initialized and self._healthy:
            return self.capabilities
        return frozenset()

    def initialize(self, context: PluginContext) -> None:
        self._capability_reporter = context.capability_reporter
        self._initialized = True
        self._healthy = self._adapter is not None
        self._report_availability(self._healthy)
        self._logger.info("avatar output initialized: available=%s", self._healthy)

    def shutdown(self) -> None:
        self._report_availability(False)
        self._initialized = False
        self._healthy = False
        self._capability_reporter = None

    async def set_expression(self, expression: str) -> None:
        adapter = self._require_adapter(self.EXPRESSION_CAPABILITY)
        try:
            await adapter.set_expression(expression)
        except Exception as error:
            self._mark_unavailable("expression_failed", error)
            raise

    async def play_gesture(self, gesture: str) -> None:
        adapter = self._require_adapter(self.GESTURE_CAPABILITY)
        try:
            await adapter.play_gesture(gesture)
        except Exception as error:
            self._mark_unavailable("gesture_failed", error)
            raise

    def _require_adapter(self, capability: str) -> AvatarOutputPort:
        if not self._initialized or not self._healthy or self._adapter is None:
            raise RuntimeError(f"avatar_output.unavailable:{capability}")
        return self._adapter

    def _mark_unavailable(self, reason: str, error: Exception) -> None:
        self._healthy = False
        self._report_availability(False)
        self._logger.warning(
            "avatar output capability lost: reason=%s error=%s",
            reason,
            type(error).__name__,
        )

    def _report_availability(self, available: bool) -> None:
        if self._capability_reporter is None:
            return
        for capability in self.capabilities:
            self._capability_reporter.set_capability_availability(
                self.plugin_id,
                capability,
                available=available,
            )
