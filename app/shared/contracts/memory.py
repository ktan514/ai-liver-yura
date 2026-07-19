from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, TypeVar
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class EpisodicMemoryRecord:
    event_id: str
    event_type: str
    occurred_at: datetime
    activity_id: str | None = None
    counterpart_id: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticMemoryRecord:
    subject: str
    fact: str
    importance: float = 0.5
    learned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    memory_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.subject.strip() or not self.fact.strip():
            raise ValueError("意味記憶のsubjectとfactは空にできません。")
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError("意味記憶のimportanceは0.0以上1.0以下にしてください。")


@dataclass(frozen=True, slots=True)
class EmotionHistoryRecord:
    source_event_id: str
    before: Mapping[str, object]
    after: Mapping[str, object]
    reason: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class UnfinishedActivityRecord:
    activity_id: str
    activity_type: str
    goal: str
    status: str
    priority: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UnrecoveredTopicRecord:
    topic_id: str
    source_activity_id: str
    summary: str
    status: str
    importance: float
    interrupted_at: datetime | None


@dataclass(frozen=True, slots=True)
class AgentMemorySnapshot:
    episodic: tuple[EpisodicMemoryRecord, ...] = ()
    semantic: tuple[SemanticMemoryRecord, ...] = ()
    unfinished_activities: tuple[UnfinishedActivityRecord, ...] = ()
    unrecovered_topics: tuple[UnrecoveredTopicRecord, ...] = ()
    emotion_history: tuple[EmotionHistoryRecord, ...] = ()
    schema_version: str = "1"


class AgentMemoryStore(Protocol):
    def load(self) -> AgentMemorySnapshot: ...

    def save(self, snapshot: AgentMemorySnapshot) -> None: ...


SnapshotT = TypeVar("SnapshotT")


class SnapshotStore(Protocol[SnapshotT]):
    """Pluginが保存対象の内部構造を知らずに扱う型付きStore契約。"""

    def load(self) -> SnapshotT: ...

    def save(self, snapshot: SnapshotT) -> None: ...
