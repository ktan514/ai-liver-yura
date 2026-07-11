from __future__ import annotations

import asyncio

from app.utils.trace import TraceLogger
from app.domain.actions import ActionPlan, ActionType
from app.domain.events import AgentEvent, AgentEventType
from app.domain.topic import TopicCategory, TopicHistory
from app.domain.topic_classifier import TopicClassifier
from app.domain.topic_memory import TopicMemoryEntry
from app.ports.embedding_generator import EmbeddingGenerator
from app.ports.memory_summary_generator import MemorySummaryGenerator
from app.ports.event_publisher import EventPublisher
from app.ports.topic_memory_store import TopicMemoryStore
from app.domain.short_term_memory import ShortTermMemory


class ExecuteActionUsecase:
    """ActionPlan を実行する最小 UseCase。

    初期段階では外部 TTS / OBS / Live2D へ接続せず、標準出力に出す。
    後で Channel Executor へ分割する。
    """

    def __init__(
        self,
        event_publisher: EventPublisher | None = None,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
        topic_classifier: TopicClassifier | None = None,
        embedding_generator: EmbeddingGenerator | None = None,
        topic_memory_store: TopicMemoryStore | None = None,
        memory_summary_generator: MemorySummaryGenerator | None = None,
    ) -> None:
        self._event_publisher = event_publisher
        self._short_term_memory = short_term_memory or ShortTermMemory()
        self._topic_history = topic_history
        self._topic_classifier = topic_classifier
        self._embedding_generator = embedding_generator
        self._topic_memory_store = topic_memory_store
        self._memory_summary_generator = memory_summary_generator
        self._trace_logger = TraceLogger()

    async def execute(self, action_plan: ActionPlan) -> None:
        self._trace_logger.write(
            "execute_action_usecase:execute:start",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            source_activity_id=action_plan.source_activity_id,
            text_length=len(action_plan.text),
            required_resources=[
                resource.value for resource in action_plan.required_resources
            ],
        )
        if action_plan.action_type == ActionType.SPEAK:
            self._trace_logger.write(
                "execute_action_usecase:speak:start",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                text_length=len(action_plan.text),
            )
            await self._publish_speech_event(AgentEventType.SPEECH_STARTED, action_plan)
            self._trace_logger.write(
                "execute_action_usecase:speak:speech_started_published",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            estimated_duration_seconds = self._estimate_speech_duration_seconds(
                action_plan.text
            )
            self._trace_logger.write(
                "execute_action_usecase:speak:estimated_duration",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                text_length=len(action_plan.text),
                estimated_duration_seconds=estimated_duration_seconds,
            )
            print(f"[{action_plan.action_type.value}] {action_plan.text}")
            await asyncio.sleep(estimated_duration_seconds)
            await self._publish_speech_event(AgentEventType.SPEECH_FINISHED, action_plan)
            self._trace_logger.write(
                "execute_action_usecase:speak:speech_finished_published",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            self._short_term_memory.add_speech(
                text=action_plan.text,
                activity_type=action_plan.action_type.value,
            )
            self._trace_logger.write(
                "execute_action_usecase:speak:short_term_memory_added",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                text_length=len(action_plan.text),
            )
            await self._record_topic_history(action_plan)
            self._trace_logger.write(
                "execute_action_usecase:speak:finished",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            return

        if action_plan.action_type in (ActionType.ASK, ActionType.REACT):
            print(f"[{action_plan.action_type.value}] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return

        if action_plan.action_type == ActionType.OBSERVE:
            print("[observe]")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return

        if action_plan.action_type == ActionType.UPDATE_SUBTITLE:
            print(f"[subtitle] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                text_length=len(action_plan.text),
            )
            return

        if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
            print(f"[expression] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                text=action_plan.text,
            )
            return

        print(f"[{action_plan.action_type.value}] not implemented")
        self._trace_logger.write(
            "execute_action_usecase:execute:not_implemented",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
        )

    def _estimate_speech_duration_seconds(self, text: str) -> float:
        """テキスト長から疑似的な読み上げ予定時間を見積もる。"""

        chars_per_second = 8.0
        minimum_seconds = 1.0
        maximum_seconds = 20.0
        estimated_seconds = len(text) / chars_per_second
        return max(minimum_seconds, min(maximum_seconds, estimated_seconds))

    async def _record_topic_history(self, action_plan: ActionPlan) -> None:
        if self._topic_history is None or self._topic_classifier is None:
            self._trace_logger.write(
                "execute_action_usecase:speak:topic_history_skipped",
                reason="topic_history_or_classifier_not_set",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            return

        try:
            category = await self._topic_classifier.classify(action_plan.text)
        except Exception as error:
            self._trace_logger.write(
                "execute_action_usecase:speak:topic_classification_failed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return

        self._topic_history.add(
            category=category,
            summary=action_plan.text,
            source_text=action_plan.text,
            activity_type=action_plan.action_type.value,
        )
        self._trace_logger.write(
            "execute_action_usecase:speak:topic_history_added",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            category=category.value,
            text_length=len(action_plan.text),
        )
        await self._record_topic_memory(action_plan, category)

    async def _record_topic_memory(
        self,
        action_plan: ActionPlan,
        category: TopicCategory,
    ) -> None:
        if self._embedding_generator is None or self._topic_memory_store is None:
            self._trace_logger.write(
                "execute_action_usecase:speak:topic_memory_skipped",
                reason="embedding_generator_or_topic_memory_store_not_set",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            return

        try:
            summary = await self._generate_memory_summary(action_plan.text)
            embedding = await self._embedding_generator.generate_embedding(summary)
        except Exception as error:
            self._trace_logger.write(
                "execute_action_usecase:speak:embedding_generation_failed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return

        if not embedding:
            self._trace_logger.write(
                "execute_action_usecase:speak:topic_memory_skipped",
                reason="embedding_is_empty",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            return

        try:
            entry = TopicMemoryEntry(
                category=category,
                summary=summary,
                source_text=action_plan.text,
                activity_type=action_plan.action_type.value,
                embedding=embedding,
                source_activity_id=action_plan.source_activity_id,
            )
            await self._topic_memory_store.save(entry)
        except Exception as error:
            self._trace_logger.write(
                "execute_action_usecase:speak:topic_memory_save_failed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return

        self._trace_logger.write(
            "execute_action_usecase:speak:topic_memory_saved",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            category=category.value,
            summary=summary,
            embedding_dimension=len(embedding),
            text_length=len(action_plan.text),
        )

    async def _generate_memory_summary(self, text: str) -> str:
        if self._memory_summary_generator is None:
            return text

        summary = await self._memory_summary_generator.generate_summary(text)
        stripped_summary = summary.strip()
        if not stripped_summary:
            return text
        return stripped_summary

    async def _publish_speech_event(
        self,
        event_type: AgentEventType,
        action_plan: ActionPlan,
    ) -> None:
        self._trace_logger.write(
            "execute_action_usecase:publish_speech_event:start",
            event_type=event_type.value,
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            publisher_exists=self._event_publisher is not None,
        )
        if self._event_publisher is None:
            self._trace_logger.write(
                "execute_action_usecase:publish_speech_event:skipped",
                reason="publisher_not_set",
                event_type=event_type.value,
                action_id=action_plan.action_id,
            )
            return

        await self._event_publisher.publish(
            AgentEvent(
                event_type=event_type,
                payload={
                    "action_id": action_plan.action_id,
                    "source_activity_id": action_plan.source_activity_id,
                    "text": action_plan.text,
                },
            )
        )
        self._trace_logger.write(
            "execute_action_usecase:publish_speech_event:published",
            event_type=event_type.value,
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
        )
