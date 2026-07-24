from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.adapters.storage.json_relationship_memory_store import (
    JsonRelationshipMemoryStore,
)
from app.domain.relationships import RelationshipIdentity, RelationshipMemory


def test_json_relationship_memory_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "relationships.json"
    store = JsonRelationshipMemoryStore(path, max_entries=10)
    memory = RelationshipMemory(max_entries=10).record(
        RelationshipIdentity("youtube:viewer-1", "Alice", "member"),
        event_id="event-1",
        occurred_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
    )

    store.save(memory)
    loaded = store.load()

    assert loaded == memory
    assert "Alice" in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


def test_json_relationship_memory_store_returns_empty_when_file_is_absent(
    tmp_path: Path,
) -> None:
    loaded = JsonRelationshipMemoryStore(
        tmp_path / "missing.json",
        max_entries=7,
    ).load()

    assert loaded == RelationshipMemory(max_entries=7)


def test_json_relationship_memory_store_rejects_unknown_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "relationships.json"
    path.write_text('{"schema_version": 999, "relationships": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        JsonRelationshipMemoryStore(path).load()
