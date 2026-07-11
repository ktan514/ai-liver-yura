

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.topic import TopicCategory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry


def test_topic_memory_entry_can_be_created() -> None:
    created_at = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)

    entry = TopicMemoryEntry(
        category=TopicCategory.NATURE,
        summary="海の色は時間や天気で変わる。",
        source_text="海の色は時間や天気で変わるのが面白いよね。",
        activity_type="speak",
        embedding=[0.1, 0.2, 0.3],
        source_activity_id="activity-1",
        created_at=created_at,
    )

    assert entry.category == TopicCategory.NATURE
    assert entry.summary == "海の色は時間や天気で変わる。"
    assert entry.source_text == "海の色は時間や天気で変わるのが面白いよね。"
    assert entry.activity_type == "speak"
    assert entry.embedding == [0.1, 0.2, 0.3]
    assert entry.source_activity_id == "activity-1"
    assert entry.created_at == created_at


def test_topic_memory_entry_uses_current_time_by_default() -> None:
    entry = TopicMemoryEntry(
        category=TopicCategory.GAME,
        summary="ゲームの水表現の話。",
        source_text="ゲームの中の水表現ってすごいよね。",
        activity_type="speak",
        embedding=[0.1, 0.2],
    )

    assert entry.created_at.tzinfo is not None


@pytest.mark.parametrize(
    ("summary", "source_text", "activity_type", "embedding", "expected_message"),
    [
        ("", "source", "speak", [0.1], "summary must not be empty"),
        ("   ", "source", "speak", [0.1], "summary must not be empty"),
        ("summary", "", "speak", [0.1], "source_text must not be empty"),
        ("summary", "   ", "speak", [0.1], "source_text must not be empty"),
        ("summary", "source", "", [0.1], "activity_type must not be empty"),
        ("summary", "source", "   ", [0.1], "activity_type must not be empty"),
        ("summary", "source", "speak", [], "embedding must not be empty"),
    ],
)
def test_topic_memory_entry_validates_required_fields(
    summary: str,
    source_text: str,
    activity_type: str,
    embedding: list[float],
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        TopicMemoryEntry(
            category=TopicCategory.OTHER,
            summary=summary,
            source_text=source_text,
            activity_type=activity_type,
            embedding=embedding,
        )


def test_similar_topic_memory_can_be_created() -> None:
    entry = TopicMemoryEntry(
        category=TopicCategory.TECHNOLOGY,
        summary="AIモデルの話。",
        source_text="AIモデルの仕組みって面白いよね。",
        activity_type="speak",
        embedding=[0.1, 0.2, 0.3],
    )

    similar_memory = SimilarTopicMemory(entry=entry, similarity=0.82)

    assert similar_memory.entry == entry
    assert similar_memory.similarity == 0.82