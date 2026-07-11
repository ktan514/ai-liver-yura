

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.adapters.storage.postgres_topic_memory_store import (
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.domain.topic import TopicCategory
from app.domain.topic_memory import TopicMemoryEntry


class FakeRecord(dict[str, Any]):
    pass


def _create_store(embedding_dimension: int = 3) -> PostgresTopicMemoryStore:
    return PostgresTopicMemoryStore(
        PostgresTopicMemoryStoreConfig(
            dsn="postgresql://user:password@localhost:5432/ai_liver_test",
            embedding_dimension=embedding_dimension,
        )
    )


def test_format_vector_converts_embedding_to_pgvector_text() -> None:
    store = _create_store()

    result = store._format_vector([0.1, -0.2, 3.0])

    assert result == "[0.1,-0.2,3.0]"


def test_parse_vector_converts_pgvector_text_to_embedding() -> None:
    store = _create_store()

    result = store._parse_vector("[0.1,-0.2,3]")

    assert result == [0.1, -0.2, 3.0]


def test_parse_vector_accepts_spaces() -> None:
    store = _create_store()

    result = store._parse_vector("[0.1, -0.2, 3]")

    assert result == [0.1, -0.2, 3.0]


def test_parse_vector_raises_error_when_format_is_invalid() -> None:
    store = _create_store()

    with pytest.raises(ValueError, match="invalid vector format"):
        store._parse_vector("0.1,-0.2,3")


def test_validate_embedding_dimension_accepts_expected_dimension() -> None:
    store = _create_store(embedding_dimension=3)

    store._validate_embedding_dimension([0.1, 0.2, 0.3])


def test_validate_embedding_dimension_raises_error_when_dimension_is_different() -> None:
    store = _create_store(embedding_dimension=3)

    with pytest.raises(
        ValueError,
        match="embedding dimension mismatch: expected 3, got 2",
    ):
        store._validate_embedding_dimension([0.1, 0.2])


def test_ensure_timezone_adds_utc_when_datetime_is_naive() -> None:
    store = _create_store()
    naive_datetime = datetime(2026, 7, 8, 12, 0, 0)

    result = store._ensure_timezone(naive_datetime)

    assert result == datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_ensure_timezone_keeps_timezone_when_datetime_is_aware() -> None:
    store = _create_store()
    aware_datetime = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)

    result = store._ensure_timezone(aware_datetime)

    assert result == aware_datetime


def test_record_to_entry_converts_record_to_topic_memory_entry() -> None:
    store = _create_store()
    created_at = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
    record = FakeRecord(
        category="nature",
        summary="海の色は天気で変わる。",
        source_text="海の色は時間や天気で変わるのが面白いよね。",
        activity_type="speak",
        source_activity_id="activity-1",
        embedding="[0.1,0.2,0.3]",
        created_at=created_at,
    )

    entry = store._record_to_entry(record)

    assert isinstance(entry, TopicMemoryEntry)
    assert entry.category == TopicCategory.NATURE
    assert entry.summary == "海の色は天気で変わる。"
    assert entry.source_text == "海の色は時間や天気で変わるのが面白いよね。"
    assert entry.activity_type == "speak"
    assert entry.source_activity_id == "activity-1"
    assert entry.embedding == [0.1, 0.2, 0.3]
    assert entry.created_at == created_at