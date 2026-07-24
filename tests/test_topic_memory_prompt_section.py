from app.adapters.prompt.topic_memory_prompt_section import TopicMemoryPromptSection
from app.domain.topic import TopicCategory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry


def _topic_memory_entry(
    category: TopicCategory,
    summary: str,
) -> TopicMemoryEntry:
    return TopicMemoryEntry(
        category=category,
        summary=summary,
        source_text=summary,
        activity_type="speak",
        embedding=[0.1, 0.2, 0.3],
    )


def test_build_returns_empty_string_when_topic_memories_are_empty() -> None:
    section = TopicMemoryPromptSection()

    prompt_section = section.build([])

    assert prompt_section == ""


def test_build_returns_topic_memory_prompt_section() -> None:
    section = TopicMemoryPromptSection()
    similar_topic_memories = [
        SimilarTopicMemory(
            entry=_topic_memory_entry(
                category=TopicCategory.NATURE,
                summary="海辺の静かな雰囲気について話した記憶",
            ),
            similarity=0.82,
        ),
        SimilarTopicMemory(
            entry=_topic_memory_entry(
                category=TopicCategory.SEA_LIFE,
                summary="クラゲ展示がきれいだった記憶",
            ),
            similarity=0.91,
        ),
    ]

    prompt_section = section.build(similar_topic_memories)

    assert prompt_section == "\n".join(
        [
            "# 関連する過去の記憶",
            "- sea_life: クラゲ展示がきれいだった記憶",
            "- nature: 海辺の静かな雰囲気について話した記憶",
        ]
    )
