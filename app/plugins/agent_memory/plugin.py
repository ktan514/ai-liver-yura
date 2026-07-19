from __future__ import annotations

import logging

from app.shared.contracts.memory import AgentMemorySnapshot, AgentMemoryStore
from app.shared.contracts.plugins.runtime import CapabilityReporter, PluginContext


class AgentMemoryPlugin:
    plugin_id = "agent_memory"
    display_name = "Agent Memory"
    MEMORY_CAPABILITY = "memory.agent_state"

    def __init__(self, store: AgentMemoryStore | None) -> None:
        self._store = store
        self._initialized = False
        self._healthy = False
        self._reporter: CapabilityReporter | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({self.MEMORY_CAPABILITY})

    def available_capabilities(self) -> frozenset[str]:
        return self.capabilities if self._initialized and self._healthy else frozenset()

    def initialize(self, context: PluginContext) -> None:
        self._reporter = context.capability_reporter
        self._initialized = True
        self._healthy = self._store is not None

    def shutdown(self) -> None:
        self._initialized = False
        self._healthy = False
        self._reporter = None

    def load(self) -> AgentMemorySnapshot:
        try:
            return self._require_store().load()
        except Exception as error:
            self._mark_unavailable(error)
            raise

    def save(self, snapshot: AgentMemorySnapshot) -> None:
        try:
            self._require_store().save(snapshot)
        except Exception as error:
            self._mark_unavailable(error)
            raise

    def _require_store(self) -> AgentMemoryStore:
        if not self._initialized or not self._healthy or self._store is None:
            raise RuntimeError("agent_memory.unavailable")
        return self._store

    def _mark_unavailable(self, error: Exception) -> None:
        self._healthy = False
        if self._reporter is not None:
            self._reporter.set_capability_availability(
                self.plugin_id, self.MEMORY_CAPABILITY, available=False
            )
        self._logger.warning("agent memory capability lost: %s", type(error).__name__)
