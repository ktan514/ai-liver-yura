from __future__ import annotations

import logging
from typing import Generic, TypeVar

from app.shared.contracts.memory import SnapshotStore
from app.shared.contracts.plugins.runtime import CapabilityReporter, PluginContext

MemoryT = TypeVar("MemoryT")


class RelationshipMemoryPlugin(Generic[MemoryT]):
    """関係性永続化Storeを任意Capabilityとして隔離するPlugin。"""

    plugin_id = "relationship_memory"
    display_name = "Relationship Memory"
    MEMORY_CAPABILITY = "memory.relationship"

    def __init__(self, store: SnapshotStore[MemoryT] | None) -> None:
        self._store = store
        self._initialized = False
        self._healthy = False
        self._capability_reporter: CapabilityReporter | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({self.MEMORY_CAPABILITY})

    def available_capabilities(self) -> frozenset[str]:
        if self._initialized and self._healthy:
            return self.capabilities
        return frozenset()

    def initialize(self, context: PluginContext) -> None:
        self._capability_reporter = context.capability_reporter
        self._initialized = True
        self._healthy = self._store is not None
        self._logger.info(
            "relationship memory initialized: available=%s",
            self._healthy,
        )

    def shutdown(self) -> None:
        self._initialized = False
        self._healthy = False
        self._capability_reporter = None

    def load(self) -> MemoryT:
        store = self._require_store()
        try:
            return store.load()
        except Exception as error:
            self._mark_unavailable("load_failed", error)
            raise

    def save(self, memory: MemoryT) -> None:
        store = self._require_store()
        try:
            store.save(memory)
        except Exception as error:
            self._mark_unavailable("save_failed", error)
            raise

    def _require_store(self) -> SnapshotStore[MemoryT]:
        if not self._initialized or not self._healthy or self._store is None:
            raise RuntimeError("relationship_memory.unavailable")
        return self._store

    def _mark_unavailable(self, reason: str, error: Exception) -> None:
        self._healthy = False
        if self._capability_reporter is not None:
            self._capability_reporter.set_capability_availability(
                self.plugin_id,
                self.MEMORY_CAPABILITY,
                available=False,
            )
        self._logger.warning(
            "relationship memory capability lost: reason=%s error=%s",
            reason,
            type(error).__name__,
        )
