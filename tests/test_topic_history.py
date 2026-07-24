from __future__ import annotations

import pytest

from app.domain.topic import TopicCategory, TopicHistory


def test_topic_history_adds_topic_entries() -> None:
    topic_history = TopicHistory()

    topic_history.add(
        category=TopicCategory.SEA_LIFE,
        summary="海の生き物の話",
        source_text="クラゲって見てると落ち着くよね。",
        activity_type="autonomous_talk",
    )

    entries = topic_history.recent_entries()

    assert len(entries) == 1
    assert entries[0].category == TopicCategory.SEA_LIFE
    assert entries[0].summary == "海の生き物の話"
    assert entries[0].source_text == "クラゲって見てると落ち着くよね。"
    assert entries[0].activity_type == "autonomous_talk"


def test_topic_history_keeps_max_entries() -> None:
    topic_history = TopicHistory(max_entries=3)

    topic_history.add(category=TopicCategory.SEA_LIFE, summary="1")
    topic_history.add(category=TopicCategory.GAME, summary="2")
    topic_history.add(category=TopicCategory.TECHNOLOGY, summary="3")
    topic_history.add(category=TopicCategory.STREAMING, summary="4")

    entries = topic_history.recent_entries()

    assert [entry.summary for entry in entries] == ["2", "3", "4"]


def test_topic_history_returns_recent_categories() -> None:
    topic_history = TopicHistory()

    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海")
    topic_history.add(category=TopicCategory.GAME, summary="ゲーム")
    topic_history.add(category=TopicCategory.TECHNOLOGY, summary="技術")

    assert topic_history.recent_categories(limit=2) == [
        TopicCategory.GAME,
        TopicCategory.TECHNOLOGY,
    ]


def test_topic_history_detects_stagnation() -> None:
    topic_history = TopicHistory()

    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海1")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海2")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海3")

    assert topic_history.is_stagnating(category=TopicCategory.SEA_LIFE, threshold=3)


def test_topic_history_does_not_detect_stagnation_when_category_changes() -> None:
    topic_history = TopicHistory()

    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海1")
    topic_history.add(category=TopicCategory.GAME, summary="ゲーム")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海2")

    assert not topic_history.is_stagnating(category=TopicCategory.SEA_LIFE, threshold=3)


def test_topic_history_returns_latest_category() -> None:
    topic_history = TopicHistory()

    assert topic_history.latest_category() is None

    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海")
    topic_history.add(category=TopicCategory.GAME, summary="ゲーム")

    assert topic_history.latest_category() == TopicCategory.GAME


def test_topic_history_returns_rotation_hint_when_topic_is_stagnating() -> None:
    topic_history = TopicHistory()

    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海1")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海2")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海3")

    assert topic_history.rotation_hint() == (
        "直近で sea_life 系の話題が続いているため、" "次は別カテゴリへ自然に広げる"
    )


def test_topic_history_returns_none_rotation_hint_when_topic_is_not_stagnating() -> (
    None
):
    topic_history = TopicHistory()

    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海")
    topic_history.add(category=TopicCategory.GAME, summary="ゲーム")

    assert topic_history.rotation_hint() is None


def test_topic_history_rejects_invalid_max_entries() -> None:
    with pytest.raises(ValueError, match="max_entries must be greater than 0"):
        TopicHistory(max_entries=0)


def test_topic_history_rejects_invalid_stagnation_threshold() -> None:
    topic_history = TopicHistory()

    with pytest.raises(ValueError, match="threshold must be greater than 0"):
        topic_history.is_stagnating(category=TopicCategory.SEA_LIFE, threshold=0)
