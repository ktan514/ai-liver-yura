from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import datetime, timezone

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult, ActionExecutionStatus
from app.domain.character_response import VoiceIntent
from app.domain.events import AgentEvent, AgentEventType
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicCategory, TopicHistory
from app.domain.topic_classifier import TopicClassifier
from app.domain.topic_memory import TopicMemoryEntry
from app.ports.audio_player import AudioPlayer
from app.ports.embedding_generator import EmbeddingGenerator
from app.ports.event_publisher import EventPublisher
from app.ports.memory_summary_generator import MemorySummaryGenerator
from app.ports.speech_synthesizer import SpeechSynthesizer
from app.ports.topic_memory_store import TopicMemoryStore
from app.utils.conversation_log import ConversationLogger
from app.utils.trace import TraceLogger


class ExecuteActionUsecase:
    """ActionPlanをPort経由で実行し、利用不能な出力は安全に縮退するUseCase。"""

    def __init__(
        self,
        event_publisher: EventPublisher | None = None,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
        topic_classifier: TopicClassifier | None = None,
        embedding_generator: EmbeddingGenerator | None = None,
        topic_memory_store: TopicMemoryStore | None = None,
        memory_summary_generator: MemorySummaryGenerator | None = None,
        speech_synthesizer: SpeechSynthesizer | None = None,
        audio_player: AudioPlayer | None = None,
        background_topic_memory: bool = False,
        conversation_logger: ConversationLogger | None = None,
    ) -> None:
        self._event_publisher = event_publisher
        self._short_term_memory = short_term_memory or ShortTermMemory()
        self._topic_history = topic_history
        self._topic_classifier = topic_classifier
        self._embedding_generator = embedding_generator
        self._topic_memory_store = topic_memory_store
        self._memory_summary_generator = memory_summary_generator
        self._speech_synthesizer = speech_synthesizer
        self._audio_player = audio_player
        self._background_topic_memory = background_topic_memory
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._background_tasks_lock = threading.RLock()
        self._trace_logger = TraceLogger()
        self._conversation_logger = conversation_logger or ConversationLogger()

    async def prepare(self, action_plan: ActionPlan) -> ActionPlan:
        """音声を先に合成する。イベント発行・再生・記憶保存は行わない。"""

        if (
            action_plan.action_type != ActionType.SPEAK
            or self._speech_synthesizer is None
            or self._audio_player is None
            or isinstance(action_plan.metadata.get("prepared_audio"), bytes)
        ):
            return action_plan
        voice_intent = action_plan.metadata.get("voice_intent")
        self._conversation_logger.record(
            speaker="llm",
            source="tts",
            text=action_plan.text,
            action_id=action_plan.action_id,
        )
        action_plan = replace(
            action_plan,
            metadata={**action_plan.metadata, "conversation_tts_logged": True},
        )
        self._trace_logger.write(
            "execute_action_usecase:speak:synthesis_started",
            action_id=action_plan.action_id,
            phase="prepare",
        )
        try:
            audio_data = await self._speech_synthesizer.synthesize(
                action_plan.text,
                voice_intent=(
                    voice_intent if isinstance(voice_intent, VoiceIntent) else None
                ),
            )
        except Exception as error:
            self._trace_logger.warning(
                "execute_action_usecase:speak:synthesis_prepare_failed",
                action_id=action_plan.action_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return action_plan
        self._trace_logger.write(
            "execute_action_usecase:speak:synthesis_finished",
            action_id=action_plan.action_id,
            audio_bytes=len(audio_data),
            phase="prepare",
        )
        return replace(
            action_plan,
            metadata={**action_plan.metadata, "prepared_audio": audio_data},
        )

    async def execute(self, action_plan: ActionPlan) -> ActionExecutionResult | None:
        self._trace_logger.write(
            "execute_action_usecase:execute:start",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            source_activity_id=action_plan.source_activity_id,
            output_unit_id=action_plan.output_unit_id,
            text_length=len(action_plan.text),
            required_resources=[
                resource.value for resource in action_plan.required_resources
            ],
        )
        if action_plan.action_type == ActionType.SPEAK:
            if (
                action_plan.metadata.get("conversation_tts_logged") is not True
                and self._speech_synthesizer is not None
                and self._audio_player is not None
            ):
                self._conversation_logger.record(
                    speaker="llm",
                    source="tts",
                    text=action_plan.text,
                    action_id=action_plan.action_id,
                )
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
            print(f"[{action_plan.action_type.value}] {action_plan.text}")
            playback_error = await self._play_speech(action_plan)
            await self._publish_speech_event(
                AgentEventType.SPEECH_FINISHED, action_plan
            )
            self._trace_logger.write(
                "execute_action_usecase:speak:speech_finished_published",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            if playback_error is None:
                self._short_term_memory.add_speech(
                    text=action_plan.text,
                    activity_type=action_plan.action_type.value,
                )
                self._trace_logger.info(
                    "execute_action_usecase:speak:memory_saved",
                    action_id=action_plan.action_id,
                    source_activity_id=action_plan.source_activity_id,
                    text_length=len(action_plan.text),
                    reason="speak_completed",
                )
                if self._background_topic_memory:
                    self._schedule_topic_history(action_plan)
                else:
                    await self._record_topic_history(action_plan)
            else:
                self._trace_logger.info(
                    "execute_action_usecase:speak:memory_not_saved",
                    action_id=action_plan.action_id,
                    source_activity_id=action_plan.source_activity_id,
                    reason="speak_failed",
                )
            self._trace_logger.write(
                "execute_action_usecase:speak:finished",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            pause_after = action_plan.metadata.get("pause_after_seconds", 0.0)
            if (
                playback_error is None
                and isinstance(pause_after, (int, float))
                and not isinstance(pause_after, bool)
                and pause_after > 0
            ):
                await asyncio.sleep(min(float(pause_after), 3.0))
            if playback_error is not None:
                now = datetime.now(timezone.utc)
                return ActionExecutionResult(
                    action_id=action_plan.action_id,
                    action_type=action_plan.action_type.value,
                    status=ActionExecutionStatus.FAILED,
                    output_unit_id=action_plan.output_unit_id or "",
                    activity_turn_id="",
                    error=playback_error,
                    started_at=now,
                    finished_at=now,
                )
            return None

        if action_plan.action_type in (ActionType.ASK, ActionType.REACT):
            print(f"[{action_plan.action_type.value}] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return None

        if action_plan.action_type == ActionType.OBSERVE:
            print("[observe]")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return None

        if action_plan.action_type == ActionType.UPDATE_SUBTITLE:
            print(f"[subtitle] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                text_length=len(action_plan.text),
            )
            return None

        if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
            print(f"[expression] {action_plan.text}")
            self._trace_logger.write(
                "execute_action_usecase:execute:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                text=action_plan.text,
            )
            return None

        print(f"[{action_plan.action_type.value}] not implemented")
        self._trace_logger.write(
            "execute_action_usecase:execute:not_implemented",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
        )
        return None

    def _estimate_speech_duration_seconds(self, text: str) -> float:
        """テキスト長から疑似的な読み上げ予定時間を見積もる。"""

        chars_per_second = 8.0
        minimum_seconds = 1.0
        maximum_seconds = 20.0
        estimated_seconds = len(text) / chars_per_second
        return max(minimum_seconds, min(maximum_seconds, estimated_seconds))

    async def _play_speech(self, action_plan: ActionPlan) -> str | None:
        if self._speech_synthesizer is not None and self._audio_player is not None:
            try:
                prepared_audio = action_plan.metadata.get("prepared_audio")
                if isinstance(prepared_audio, bytes):
                    audio_data = prepared_audio
                else:
                    voice_intent = action_plan.metadata.get("voice_intent")
                    self._trace_logger.write(
                        "execute_action_usecase:speak:synthesis_started",
                        action_id=action_plan.action_id,
                        phase="playback_fallback",
                    )
                    audio_data = await self._speech_synthesizer.synthesize(
                        action_plan.text,
                        voice_intent=(
                            voice_intent
                            if isinstance(voice_intent, VoiceIntent)
                            else None
                        ),
                    )
                    self._trace_logger.write(
                        "execute_action_usecase:speak:synthesis_finished",
                        action_id=action_plan.action_id,
                        audio_bytes=len(audio_data),
                        phase="playback_fallback",
                    )
                self._trace_logger.write(
                    "execute_action_usecase:speak:playback_started",
                    action_id=action_plan.action_id,
                )
                await self._audio_player.play(audio_data)
                self._trace_logger.write(
                    "execute_action_usecase:speak:playback_finished",
                    action_id=action_plan.action_id,
                )
                self._trace_logger.info(
                    "execute_action_usecase:speak:audio_played",
                    action_id=action_plan.action_id,
                    audio_bytes=len(audio_data),
                )
                return None
            except Exception as error:
                self._trace_logger.warning(
                    "execute_action_usecase:speak:audio_fallback",
                    action_id=action_plan.action_id,
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                playback_error = f"{type(error).__name__}: {error}"
        else:
            playback_error = None

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
        await asyncio.sleep(estimated_duration_seconds)
        return playback_error

    def _schedule_topic_history(self, action_plan: ActionPlan) -> None:
        task = asyncio.create_task(
            self._record_topic_history_in_background(action_plan),
            name=f"topic-memory:{action_plan.action_id}",
        )
        with self._background_tasks_lock:
            self._background_tasks.add(task)
        task.add_done_callback(self._background_task_finished)
        self._trace_logger.write(
            "execute_action_usecase:speak:topic_memory_scheduled",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
        )

    async def _record_topic_history_in_background(
        self, action_plan: ActionPlan
    ) -> None:
        try:
            await self._record_topic_history(action_plan)
        except Exception as error:
            self._trace_logger.warning(
                "execute_action_usecase:speak:topic_memory_background_failed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )

    def _background_task_finished(self, task: asyncio.Task[None]) -> None:
        with self._background_tasks_lock:
            self._background_tasks.discard(task)

    @property
    def pending_background_task_count(self) -> int:
        with self._background_tasks_lock:
            return len(self._background_tasks)

    async def _record_topic_history(self, action_plan: ActionPlan) -> None:
        if action_plan.metadata.get("skip_topic_memory") is True:
            self._trace_logger.debug(
                "execute_action_usecase:speak:topic_history_skipped",
                reason="activity_memory_policy",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
            )
            return
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
            output_unit_id=action_plan.output_unit_id,
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
                    "output_unit_id": action_plan.output_unit_id,
                    "text": action_plan.text,
                },
            )
        )
        self._trace_logger.write(
            "execute_action_usecase:publish_speech_event:published",
            event_type=event_type.value,
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            output_unit_id=action_plan.output_unit_id,
        )
