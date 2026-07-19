from __future__ import annotations

from dataclasses import dataclass, replace

from app.shared.contracts.memory import AgentMemorySnapshot
from app.shared.contracts.memory import EmotionHistoryRecord as EmotionHistoryEntry
from app.shared.contracts.memory import EpisodicMemoryRecord as EpisodicMemory
from app.shared.contracts.memory import SemanticMemoryRecord as SemanticMemory
from app.shared.contracts.memory import (
    UnfinishedActivityRecord as UnfinishedActivityMemory,
)
from app.shared.contracts.memory import UnrecoveredTopicRecord as UnrecoveredTopicMemory

__all__ = [
    "AgentMemoryState",
    "EmotionHistoryEntry",
    "EpisodicMemory",
    "SemanticMemory",
    "UnfinishedActivityMemory",
    "UnrecoveredTopicMemory",
]


@dataclass(frozen=True, slots=True)
class AgentMemoryState:
    """種類ごとの意味を失わずに保持する、上限付きの継続記憶状態。"""

    episodic: tuple[EpisodicMemory, ...] = ()
    semantic: tuple[SemanticMemory, ...] = ()
    unfinished_activities: tuple[UnfinishedActivityMemory, ...] = ()
    unrecovered_topics: tuple[UnrecoveredTopicMemory, ...] = ()
    emotion_history: tuple[EmotionHistoryEntry, ...] = ()
    max_history_entries: int = 64

    def __post_init__(self) -> None:
        if self.max_history_entries <= 0:
            raise ValueError("max_history_entriesは1以上にしてください。")

    def remember_episode(self, episode: EpisodicMemory) -> AgentMemoryState:
        if any(item.event_id == episode.event_id for item in self.episodic):
            return self
        return replace(
            self,
            episodic=(*self.episodic, episode)[-self.max_history_entries :],
        )

    def learn(self, memory: SemanticMemory) -> AgentMemoryState:
        retained = tuple(
            item for item in self.semantic if item.subject != memory.subject
        )
        return replace(
            self,
            semantic=(*retained, memory)[-self.max_history_entries :],
        )

    def record_emotion(self, entry: EmotionHistoryEntry) -> AgentMemoryState:
        if any(
            item.source_event_id == entry.source_event_id
            for item in self.emotion_history
        ):
            return self
        return replace(
            self,
            emotion_history=(*self.emotion_history, entry)[-self.max_history_entries :],
        )

    def with_unfinished_activities(
        self, activities: tuple[UnfinishedActivityMemory, ...]
    ) -> AgentMemoryState:
        return replace(self, unfinished_activities=activities)

    def with_unrecovered_topic(
        self, topic: UnrecoveredTopicMemory | None
    ) -> AgentMemoryState:
        if topic is None:
            return replace(self, unrecovered_topics=())
        retained = tuple(
            item for item in self.unrecovered_topics if item.topic_id != topic.topic_id
        )
        return replace(
            self,
            unrecovered_topics=(*retained, topic)[-self.max_history_entries :],
        )

    def as_context(self, *, limit: int = 5) -> dict[str, object]:
        return {
            "recent_episodes": [
                {
                    "event_type": item.event_type,
                    "occurred_at": item.occurred_at.isoformat(),
                    "activity_id": item.activity_id,
                    "counterpart_id": item.counterpart_id,
                }
                for item in self.episodic[-limit:]
            ],
            "semantic_facts": [
                {
                    "subject": item.subject,
                    "fact": item.fact,
                    "importance": item.importance,
                }
                for item in self.semantic[-limit:]
            ],
            "unfinished_activities": [
                {
                    "activity_id": item.activity_id,
                    "activity_type": item.activity_type,
                    "goal": item.goal,
                    "status": item.status,
                }
                for item in self.unfinished_activities
            ],
            "unrecovered_topics": [
                {
                    "topic_id": item.topic_id,
                    "summary": item.summary,
                    "status": item.status,
                    "importance": item.importance,
                }
                for item in self.unrecovered_topics[-limit:]
            ],
            "emotion_history": [
                {
                    "before": item.before.get("mood"),
                    "after": item.after.get("mood"),
                    "reason": item.reason,
                    "recorded_at": item.recorded_at.isoformat(),
                }
                for item in self.emotion_history[-limit:]
            ],
        }

    def to_snapshot(self) -> AgentMemorySnapshot:
        return AgentMemorySnapshot(
            episodic=self.episodic,
            semantic=self.semantic,
            unfinished_activities=self.unfinished_activities,
            unrecovered_topics=self.unrecovered_topics,
            emotion_history=self.emotion_history,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AgentMemorySnapshot,
        *,
        max_history_entries: int = 64,
    ) -> AgentMemoryState:
        if snapshot.schema_version != "1":
            raise ValueError(f"未対応のMemory schemaです: {snapshot.schema_version}")
        return cls(
            episodic=snapshot.episodic[-max_history_entries:],
            semantic=snapshot.semantic[-max_history_entries:],
            unfinished_activities=snapshot.unfinished_activities,
            unrecovered_topics=snapshot.unrecovered_topics[-max_history_entries:],
            emotion_history=snapshot.emotion_history[-max_history_entries:],
            max_history_entries=max_history_entries,
        )
