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

    async def load_recent_context(
        self, limit: int | None = None
    ) -> tuple[dict[str, object], ...]:
        """自律計画へ渡すため、発話原文とembeddingを除いた最近の記憶を返す。"""

        if self._topic_memory_store is None:
            return ()
        try:
            entries = await self._topic_memory_store.fetch_recent(
                limit=limit or self._search_limit
            )
        except Exception as error:
            self._trace_logger.write(
                "enrich_activity_with_topic_memory:recent_fetch_failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return ()
        memories: tuple[dict[str, object], ...] = tuple(
            {
                "category": entry.category.value,
                "summary": entry.summary,
                "activity_type": entry.activity_type,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in entries
        )
        self._trace_logger.write(
            "enrich_activity_with_topic_memory:recent_context_loaded",
            memory_count=len(memories),
        )
        return memories

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
        text_parts: list[str] = []

        event_payload = activity.context.get("event_payload")

        # base goal
        if isinstance(activity.goal, str) and activity.goal.strip():
            text_parts.append(activity.goal.strip())

        # event payload text and selected topic
        if isinstance(event_payload, dict):
            event_text = event_payload.get("text") or event_payload.get("comment")
            if isinstance(event_text, str) and event_text.strip():
                text_parts.append(event_text.strip())

            selected_topic = (
                event_payload.get("selected_topic")
                or (event_payload.get("behavior_plan") or {}).get("topic")
            )
            if isinstance(selected_topic, str) and selected_topic.strip():
                text_parts.append(selected_topic.strip())

        return "\n".join(text_part for text_part in text_parts if text_part)
