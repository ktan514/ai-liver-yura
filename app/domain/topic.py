from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TopicCategory(str, Enum):
    SEA_LIFE = "sea_life"
    NATURE = "nature"
    GAME = "game"
    TECHNOLOGY = "technology"
    STREAMING = "streaming"
    MOOD = "mood"
    VIEWER_QUESTION = "viewer_question"
    OTHER = "other"


@dataclass(frozen=True)
class TopicEntry:
    category: TopicCategory
    summary: str
    source_text: str = ""
    activity_type: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TopicHistory:
    def __init__(self, max_entries: int = 20) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than 0")

        self._max_entries = max_entries
        self._entries: list[TopicEntry] = []

    def add(
        self,
        *,
        category: TopicCategory,
        summary: str,
        source_text: str = "",
        activity_type: str = "",
    ) -> None:
        self._entries.append(
            TopicEntry(
                category=category,
                summary=summary,
                source_text=source_text,
                activity_type=activity_type,
            )
        )

        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

    def recent_entries(self, limit: int | None = None) -> list[TopicEntry]:
        if limit is None:
            return list(self._entries)

        if limit <= 0:
            return []

        return self._entries[-limit:]

    def recent_categories(self, limit: int | None = None) -> list[TopicCategory]:
        return [entry.category for entry in self.recent_entries(limit)]

    def is_stagnating(
        self,
        *,
        category: TopicCategory,
        threshold: int = 3,
    ) -> bool:
        if threshold <= 0:
            raise ValueError("threshold must be greater than 0")

        recent_categories = self.recent_categories(limit=threshold)

        if len(recent_categories) < threshold:
            return False

        return all(recent_category == category for recent_category in recent_categories)

    def latest_category(self) -> TopicCategory | None:
        if not self._entries:
            return None

        return self._entries[-1].category

    def rotation_hint(self, *, threshold: int = 3) -> str | None:
        latest_category = self.latest_category()

        if latest_category is None:
            return None

        if not self.is_stagnating(category=latest_category, threshold=threshold):
            return None

        return (
            f"直近で {latest_category.value} 系の話題が続いているため、"
            "次は別カテゴリへ自然に広げる"
        )