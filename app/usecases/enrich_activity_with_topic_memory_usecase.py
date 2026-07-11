

from __future__ import annotations

from dataclasses import replace

from app.domain.activities import Activity
from app.ports.embedding_generator import EmbeddingGenerator
from app.ports.topic_memory_store import TopicMemoryStore
from app.utils.trace import TraceLogger


class EnrichActivityWithTopicMemoryUsecase:
    """Activity に関連する長期記憶を検索し、context に追加する Usecase。"""

    def __init__(
        self,
        embedding_generator: EmbeddingGenerator | None = None,
        topic_memory_store: TopicMemoryStore | None = None,
        search_limit: int = 5,
    ) -> None:
        self._embedding_generator = embedding_generator
        self._topic_memory_store = topic_memory_store
        self._search_limit = search_limit
        self._trace_logger = TraceLogger()

    async def enrich(self, activity: Activity) -> Activity:
        if self._embedding_generator is None or self._topic_memory_store is None:
            self._trace_logger.write(
                "enrich_activity_with_topic_memory:skipped",
                reason="topic_memory_dependency_missing",
                activity_type=activity.activity_type.value,
            )
            return activity

        query_text = self._build_query_text(activity)
        if not query_text:
            self._trace_logger.write(
                "enrich_activity_with_topic_memory:skipped",
                reason="query_text_empty",
                activity_type=activity.activity_type.value,
            )
            return activity

        try:
            embedding = await self._embedding_generator.generate_embedding(query_text)
        except Exception as error:
            self._trace_logger.write(
                "enrich_activity_with_topic_memory:embedding_generation_failed",
                activity_type=activity.activity_type.value,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return activity

        if not embedding:
            self._trace_logger.write(
                "enrich_activity_with_topic_memory:skipped",
                reason="embedding_empty",
                activity_type=activity.activity_type.value,
            )
            return activity

        try:
            similar_topic_memories = await self._topic_memory_store.search_similar(
                embedding=embedding,
                limit=self._search_limit,
            )
        except Exception as error:
            self._trace_logger.write(
                "enrich_activity_with_topic_memory:search_failed",
                activity_type=activity.activity_type.value,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return activity

        if not similar_topic_memories:
            self._trace_logger.write(
                "enrich_activity_with_topic_memory:finished",
                activity_type=activity.activity_type.value,
                query_text_length=len(query_text),
                related_memory_count=0,
            )
            return activity

        enriched_context = dict(activity.context)
        enriched_context["similar_topic_memories"] = similar_topic_memories
        enriched_activity = replace(activity, context=enriched_context)
        self._trace_logger.write(
            "enrich_activity_with_topic_memory:finished",
            activity_type=activity.activity_type.value,
            query_text_length=len(query_text),
            related_memory_count=len(similar_topic_memories),
        )
        return enriched_activity

    def _build_query_text(self, activity: Activity) -> str:
        text_parts = [activity.goal]

        event_payload = activity.context.get("event_payload")
        if isinstance(event_payload, dict):
            event_text = event_payload.get("text")
            if isinstance(event_text, str):
                text_parts.append(event_text)

        return "\n".join(text_part.strip() for text_part in text_parts if text_part.strip())