import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.topic import TopicCategory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry
from app.usecases.enrich_activity_with_topic_memory_usecase import (
    EnrichActivityWithTopicMemoryUsecase,
)


class FakeEmbeddingGenerator:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding
        self.received_texts: list[str] = []

    async def generate_embedding(self, text: str) -> list[float]:
        self.received_texts.append(text)
        return self.embedding


class FakeTopicMemoryStore:
    def __init__(
        self,
        similar_topic_memories: list[SimilarTopicMemory],
        recent_entries: list[TopicMemoryEntry] | None = None,
    ) -> None:
        self.similar_topic_memories = similar_topic_memories
        self.recent_entries = recent_entries or []
        self.received_embeddings: list[list[float]] = []
        self.received_limits: list[int] = []

    async def save(self, entry: TopicMemoryEntry) -> None:
        raise NotImplementedError

    async def fetch_recent(self, limit: int = 10) -> list[TopicMemoryEntry]:
        return self.recent_entries[:limit]

    async def search_similar(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[SimilarTopicMemory]:
        self.received_embeddings.append(embedding)
        self.received_limits.append(limit)
        return self.similar_topic_memories


class ErrorEmbeddingGenerator:
    async def generate_embedding(self, text: str) -> list[float]:
        raise RuntimeError("embedding failed")


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


def _activity(
    goal: str = "自律的に話題を出して話す",
    context: dict | None = None,
) -> Activity:
    return Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal=goal,
        context=context or {},
    )


@pytest.mark.asyncio
async def test_enrich_adds_similar_topic_memories_to_activity_context() -> None:
    similar_topic_memories = [
        SimilarTopicMemory(
            entry=_topic_memory_entry(
                category=TopicCategory.SEA_LIFE,
                summary="クラゲ展示がきれいだった記憶",
            ),
            similarity=0.91,
        )
    ]
    embedding_generator = FakeEmbeddingGenerator(embedding=[0.1, 0.2, 0.3])
    topic_memory_store = FakeTopicMemoryStore(
        similar_topic_memories=similar_topic_memories
    )
    usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
        search_limit=3,
    )
    activity = _activity(context={"event_payload": {"text": "クラゲの話をしたい"}})

    enriched_activity = await usecase.enrich(activity)

    assert enriched_activity is not activity
    assert activity.context == {"event_payload": {"text": "クラゲの話をしたい"}}
    assert enriched_activity.context["event_payload"] == {"text": "クラゲの話をしたい"}
    assert enriched_activity.context["similar_topic_memories"] == similar_topic_memories
    assert embedding_generator.received_texts == [
        "自律的に話題を出して話す\nクラゲの話をしたい"
    ]
    assert topic_memory_store.received_embeddings == [[0.1, 0.2, 0.3]]
    assert topic_memory_store.received_limits == [3]


@pytest.mark.asyncio
async def test_enrich_keeps_recent_context_out_of_positive_search_query() -> None:
    embedding_generator = FakeEmbeddingGenerator(embedding=[0.1, 0.2, 0.3])
    topic_memory_store = FakeTopicMemoryStore(similar_topic_memories=[])
    usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )
    activity = _activity(
        context={
            "event_payload": {
                "text": "今は何を話すか",
                "recent_topics": ["海の話", "ゲームの話"],
            },
            "autonomous_situation_context": {
                "recent_topic_summary": "前に海の話をしていた",
                "topic_state": {"recent_category": "sea_life"},
            },
        }
    )

    await usecase.enrich(activity)

    query_text = embedding_generator.received_texts[0]
    assert query_text == "自律的に話題を出して話す\n今は何を話すか"


@pytest.mark.asyncio
async def test_enrich_does_not_disable_search_from_planning_metadata() -> None:
    embedding_generator = FakeEmbeddingGenerator(embedding=[0.1, 0.2, 0.3])
    topic_memory_store = FakeTopicMemoryStore(similar_topic_memories=[])
    usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )
    activity = _activity(
        context={
            "event_payload": {
                "behavior_plan": {
                    "constraints": {
                        "topic_selection_mode": "derive_from_context"
                    }
                }
            }
        }
    )

    enriched = await usecase.enrich(activity)

    assert enriched is activity
    assert embedding_generator.received_texts == ["自律的に話題を出して話す"]
    assert topic_memory_store.received_embeddings == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_load_recent_context_omits_source_text_and_embedding() -> None:
    entry = _topic_memory_entry(
        category=TopicCategory.GAME,
        summary="探索ゲームの仕掛けについて話した記憶",
    )
    store = FakeTopicMemoryStore([], recent_entries=[entry])
    usecase = EnrichActivityWithTopicMemoryUsecase(topic_memory_store=store)

    memories = await usecase.load_recent_context()

    assert len(memories) == 1
    assert memories[0]["category"] == "game"
    assert memories[0]["summary"] == "探索ゲームの仕掛けについて話した記憶"
    assert "source_text" not in memories[0]
    assert "embedding" not in memories[0]


@pytest.mark.asyncio
async def test_enrich_returns_original_activity_when_dependencies_are_missing() -> None:
    activity = _activity()
    usecase = EnrichActivityWithTopicMemoryUsecase()

    enriched_activity = await usecase.enrich(activity)

    assert enriched_activity is activity


@pytest.mark.asyncio
async def test_enrich_returns_original_activity_when_embedding_is_empty() -> None:
    embedding_generator = FakeEmbeddingGenerator(embedding=[])
    topic_memory_store = FakeTopicMemoryStore(similar_topic_memories=[])
    usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )
    activity = _activity()

    enriched_activity = await usecase.enrich(activity)

    assert enriched_activity is activity
    assert embedding_generator.received_texts == ["自律的に話題を出して話す"]
    assert topic_memory_store.received_embeddings == []


@pytest.mark.asyncio
async def test_enrich_returns_original_activity_when_no_similar_topic_memories_are_found() -> (
    None
):
    embedding_generator = FakeEmbeddingGenerator(embedding=[0.1, 0.2, 0.3])
    topic_memory_store = FakeTopicMemoryStore(similar_topic_memories=[])
    usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )
    activity = _activity()

    enriched_activity = await usecase.enrich(activity)

    assert enriched_activity is activity
    assert topic_memory_store.received_embeddings == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_enrich_returns_original_activity_when_embedding_generation_fails() -> (
    None
):
    topic_memory_store = FakeTopicMemoryStore(similar_topic_memories=[])
    usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=ErrorEmbeddingGenerator(),
        topic_memory_store=topic_memory_store,
    )
    activity = _activity()

    enriched_activity = await usecase.enrich(activity)

    assert enriched_activity is activity
    assert topic_memory_store.received_embeddings == []
