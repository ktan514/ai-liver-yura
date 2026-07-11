

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.topic import TopicCategory


@dataclass(frozen=True)
class TopicMemoryEntry:
    category: TopicCategory
    summary: str
    source_text: str
    activity_type: str
    embedding: list[float]
    source_activity_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("summary must not be empty")
        if not self.source_text.strip():
            raise ValueError("source_text must not be empty")
        if not self.activity_type.strip():
            raise ValueError("activity_type must not be empty")
        if not self.embedding:
            raise ValueError("embedding must not be empty")


@dataclass(frozen=True)
class SimilarTopicMemory:
    entry: TopicMemoryEntry
    similarity: float