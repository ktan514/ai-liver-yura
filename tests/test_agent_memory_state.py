from __future__ import annotations

from datetime import datetime, timezone

from app.domain.activities import Activity, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.domain.memory import (
    AgentMemoryState,
    EmotionHistoryEntry,
    EpisodicMemory,
    SemanticMemory,
)
from app.runtime import ActivityManager, AgentLifeService
from app.shared.contracts.memory import AgentMemorySnapshot


class CapturingMemoryStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[AgentMemorySnapshot] = []
        self.fail = fail

    def load(self) -> AgentMemorySnapshot:
        return self.saved[-1] if self.saved else AgentMemorySnapshot()

    def save(self, snapshot: AgentMemorySnapshot) -> None:
        if self.fail:
            raise OSError("offline")
        self.saved.append(snapshot)


def test_memory_state_keeps_categories_separate_and_bounded() -> None:
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    state = AgentMemoryState(max_history_entries=2)
    for index in range(3):
        state = state.remember_episode(
            EpisodicMemory(f"event-{index}", "timer", now)
        ).record_emotion(
            EmotionHistoryEntry(
                source_event_id=f"event-{index}",
                before={"mood": "neutral"},
                after={"mood": "happy"},
                deltas={"joy": 0.5},
                reason="test",
                recorded_at=now,
            )
        )
    state = state.learn(SemanticMemory("favorite_color", "blue"))

    assert [item.event_id for item in state.episodic] == ["event-1", "event-2"]
    assert len(state.emotion_history) == 2
    assert state.semantic[0].fact == "blue"


def test_agent_life_records_episode_and_activity_but_filters_minor_emotion() -> None:
    manager = ActivityManager()
    service = AgentLifeService(manager)
    event = AgentEvent(AgentEventType.USER_TEXT, {"text": "こんにちは"})
    activity = manager.register_plugin_activity(
        Activity(ActivityType.CONVERSATION_WITH_USER, "会話を続ける")
    )

    state = service.handle_event(event)

    assert state.memory.episodic[-1].event_id == event.event_id
    assert state.memory.emotion_history == ()
    assert state.memory.unfinished_activities[0].activity_id == activity.activity_id


def test_semantic_memory_is_not_added_to_short_term_or_episode_history() -> None:
    service = AgentLifeService(ActivityManager())

    state = service.learn_semantic_fact(
        subject="viewer-1.favorite_food",
        fact="ramen",
        importance=0.8,
    )

    assert state.memory.semantic[0].fact == "ramen"
    assert state.memory.episodic == ()
    assert state.memory.emotion_history == ()


def test_agent_life_persists_shared_snapshot_and_continues_on_store_failure() -> None:
    store = CapturingMemoryStore()
    service = AgentLifeService(ActivityManager(), agent_memory_store=store)

    service.handle_event(AgentEvent(AgentEventType.SYSTEM_STARTED, {}))

    assert len(store.saved) == 1
    assert len(store.saved[0].episodic) == 1

    failing = AgentLifeService(
        ActivityManager(), agent_memory_store=CapturingMemoryStore(fail=True)
    )
    state = failing.handle_event(AgentEvent(AgentEventType.SYSTEM_STARTED, {}))
    assert len(state.memory.episodic) == 1
