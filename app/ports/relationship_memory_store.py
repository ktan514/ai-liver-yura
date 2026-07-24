from __future__ import annotations

from typing import Protocol

from app.domain.relationships import RelationshipMemory


class RelationshipMemoryStore(Protocol):
    """継続関係状態の永続化境界。"""

    def load(self) -> RelationshipMemory:
        raise NotImplementedError

    def save(self, memory: RelationshipMemory) -> None:
        raise NotImplementedError
