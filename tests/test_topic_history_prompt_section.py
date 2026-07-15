

from __future__ import annotations

from app.adapters.prompt.topic_history_prompt_section import TopicHistoryPromptSection
from app.domain.topic import TopicCategory, TopicHistory


def test_topic_history_prompt_section_returns_empty_when_topic_history_is_none() -> None:
    section = TopicHistoryPromptSection()

    assert section.build() == []


def test_topic_history_prompt_section_returns_empty_when_topic_history_is_empty() -> None:
    topic_history = TopicHistory()
    section = TopicHistoryPromptSection(topic_history=topic_history)

    assert section.build() == []


def test_topic_history_prompt_section_includes_recent_topic_history() -> None:
    topic_history = TopicHistory()
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海の生き物")
    topic_history.add(category=TopicCategory.GAME, summary="探索ゲーム")

    section = TopicHistoryPromptSection(topic_history=topic_history)

    lines = section.build()

    assert "# 直近の話題履歴" in lines
    assert "- sea_life: 海の生き物" in lines
    assert "- game: 探索ゲーム" in lines


def test_topic_history_prompt_section_limits_recent_topic_history_to_five_entries() -> None:
    topic_history = TopicHistory()
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="1")
    topic_history.add(category=TopicCategory.GAME, summary="2")
    topic_history.add(category=TopicCategory.TECHNOLOGY, summary="3")
    topic_history.add(category=TopicCategory.STREAMING, summary="4")
    topic_history.add(category=TopicCategory.MOOD, summary="5")
    topic_history.add(category=TopicCategory.VIEWER_QUESTION, summary="6")

    section = TopicHistoryPromptSection(topic_history=topic_history)

    lines = section.build()

    assert "- sea_life: 1" not in lines
    assert "- game: 2" in lines
    assert "- technology: 3" in lines
    assert "- streaming: 4" in lines
    assert "- mood: 5" in lines
    assert "- viewer_question: 6" in lines


def test_topic_history_prompt_section_includes_rotation_hint_when_topic_is_stagnating() -> None:
    topic_history = TopicHistory()
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海1")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海2")
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海3")

    section = TopicHistoryPromptSection(topic_history=topic_history)

    lines = section.build()

    assert "# 話題選択の注意" in lines
    assert "- 直近で sea_life 系の話題が続いているため、次は別カテゴリへ自然に広げる" in lines
    assert "- 話題を変える場合は、直前の話題との共通点を使って自然に橋渡しする" in lines
    assert "- 同じ大テーマの細部だけを掘り続けない" in lines


def test_topic_history_prompt_section_does_not_include_rotation_hint_when_topic_is_not_stagnating(
) -> None:
    topic_history = TopicHistory()
    topic_history.add(category=TopicCategory.SEA_LIFE, summary="海")
    topic_history.add(category=TopicCategory.GAME, summary="ゲーム")
    topic_history.add(category=TopicCategory.TECHNOLOGY, summary="技術")

    section = TopicHistoryPromptSection(topic_history=topic_history)

    lines = section.build()

    assert "# 直近の話題履歴" in lines
    assert "# 話題選択の注意" not in lines
