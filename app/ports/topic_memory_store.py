from __future__ import annotations

from typing import Protocol

from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry


class TopicMemoryStore(Protocol):
    async def save(self, entry: TopicMemoryEntry) -> None:
        raise NotImplementedError

    async def fetch_recent(self, limit: int = 10) -> list[TopicMemoryEntry]:
        raise NotImplementedError

    async def search_similar(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[SimilarTopicMemory]:
        raise NotImplementedError
