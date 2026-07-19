from __future__ import annotations

import logging
from typing import Any

from app.shared.contracts.plugins.runtime import (
    CapabilityReporter,
    PluginContext,
    ResponseGenerationGateway,
)


class LlmProviderPlugin:
    """ResponseGenerator Adapterを役割別の任意LLM Capabilityとして隔離する。"""

    GENERIC_CAPABILITY = "llm.provider"

    def __init__(
        self,
        role: str,
        generator: ResponseGenerationGateway,
        *,
        configured_available: bool = True,
    ) -> None:
        if not role or not role.replace("_", "").isalnum():
            raise ValueError("roleは英数字とunderscoreで指定してください。")
        self.role = role
        self.plugin_id = f"llm_provider.{role}"
        self.display_name = f"LLM Provider ({role})"
        self._generator = generator
        self._configured_available = configured_available
        self._initialized = False
        self._healthy = False
        self._capability_reporter: CapabilityReporter | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def role_capability(self) -> str:
        return f"{self.GENERIC_CAPABILITY}.{self.role}"

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({self.GENERIC_CAPABILITY, self.role_capability})

    def available_capabilities(self) -> frozenset[str]:
        if self._initialized and self._healthy:
            return self.capabilities
        return frozenset()

    def initialize(self, context: PluginContext) -> None:
        self._capability_reporter = context.capability_reporter
        self._initialized = True
        self._healthy = self._configured_available
        self._logger.info(
            "LLM provider initialized: plugin=%s role=%s available=%s",
            self.plugin_id,
            self.role,
            self._healthy,
        )

    def shutdown(self) -> None:
        self._initialized = False
        self._healthy = False
        self._capability_reporter = None

    async def generate_response(self, activity: Any) -> str:
        if not self._initialized or not self._healthy:
            raise RuntimeError(f"{self.plugin_id}.unavailable")
        try:
            return await self._generator.generate_response(activity)
        except Exception as error:
            self._healthy = False
            if self._capability_reporter is not None:
                for capability in self.capabilities:
                    self._capability_reporter.set_capability_availability(
                        self.plugin_id,
                        capability,
                        available=False,
                    )
            self._logger.warning(
                "LLM provider capability lost: plugin=%s role=%s error=%s",
                self.plugin_id,
                self.role,
                type(error).__name__,
            )
            raise
