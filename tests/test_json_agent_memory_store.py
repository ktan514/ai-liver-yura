from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.adapters.storage.json_agent_memory_store import JsonAgentMemoryStore
from app.shared.contracts.memory import (
    AgentMemorySnapshot,
    EmotionHistoryRecord,
    EpisodicMemoryRecord,
    SemanticMemoryRecord,
)


def test_json_agent_memory_store_round_trip(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    snapshot = AgentMemorySnapshot(
        episodic=(EpisodicMemoryRecord("event-1", "user_text", now),),
        semantic=(SemanticMemoryRecord("favorite", "ramen", learned_at=now),),
        emotion_history=(
            EmotionHistoryRecord(
                "event-1",
                {"mood": "neutral"},
                {"mood": "happy"},
                "friendly_input",
                now,
            ),
        ),
    )
    store = JsonAgentMemoryStore(tmp_path / "agent-memory.json")

    store.save(snapshot)

    assert store.load() == snapshot


def test_json_agent_memory_store_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "agent-memory.json"
    path.write_text('{"schema_version":"unknown"}', encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        JsonAgentMemoryStore(path).load()
