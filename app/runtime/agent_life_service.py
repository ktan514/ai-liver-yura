from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from app.domain.activities import ActivityType
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.domain.memory import (
    EmotionHistoryEntry,
    EpisodicMemory,
    SemanticMemory,
    UnfinishedActivityMemory,
    UnrecoveredTopicMemory,
)
from app.domain.relationships import RelationshipMemory, RelationshipState
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import (
    InterruptedTopic,
    TopicContinuationDecision,
    TopicContinuationResult,
    TopicLifecycleStatus,
)
from app.ports.relationship_memory_store import RelationshipMemoryStore
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
from app.runtime.drive_state_updater import DriveStateUpdater
from app.runtime.emotion_appraiser import EmotionAppraiser
from app.runtime.emotion_state_updater import EmotionStateUpdater
from app.runtime.relationship_state_updater import RelationshipStateUpdater
from app.runtime.topic_continuation_evaluator import TopicContinuationEvaluator
from app.shared.contracts.memory import AgentMemoryStore
from app.utils.trace import TraceLogger


class AgentLifeService:
    """AIライバーの生活・活動状態を更新する同期処理本体。

    AgentState の更新と ActivityManager からの状態同期を担当し、
    状態に応じて次に発生させる自律 Event を判断する。
    Thread や Queue には依存しない。
    """

    def __init__(
        self,
        activity_manager: ActivityManager,
        initial_state: AgentState | None = None,
        drive_state_updater: DriveStateUpdater | None = None,
        emotion_appraiser: EmotionAppraiser | None = None,
        emotion_state_updater: EmotionStateUpdater | None = None,
        relationship_state_updater: RelationshipStateUpdater | None = None,
        relationship_memory_store: RelationshipMemoryStore | None = None,
        short_term_memory: ShortTermMemory | None = None,
        now: datetime | None = None,
        conversation_idle_timeout_seconds: float = 30.0,
        topic_continuation_evaluator: TopicContinuationEvaluator | None = None,
        pending_confirmation_provider: Callable[[], bool] | None = None,
        autonomous_activity_policy: AutonomousActivityPolicy | None = None,
        agent_memory_store: AgentMemoryStore | None = None,
        autonomous_plan_retry_backoff_seconds: float = 2.0,
    ) -> None:
        self._activity_manager = activity_manager
        self._agent_state = initial_state or AgentState()
        self._drive_state_updater = drive_state_updater or DriveStateUpdater()
        self._last_drive_updated_at = now or datetime.now(timezone.utc)
        self._emotion_appraiser = emotion_appraiser or EmotionAppraiser()
        self._emotion_state_updater = emotion_state_updater or EmotionStateUpdater()
        self._relationship_state_updater = (
            relationship_state_updater or RelationshipStateUpdater()
        )
        self._relationship_memory_store = relationship_memory_store
        self._short_term_memory = short_term_memory
        self._last_emotion_updated_at = self._last_drive_updated_at
        self._last_autonomous_talk_planned_at: datetime | None = None
        self._last_autonomous_plan_rejected_at: datetime | None = None
        self._autonomous_plan_retry_backoff_seconds = max(
            autonomous_plan_retry_backoff_seconds, 0.0
        )
        self._conversation_idle_timeout_seconds = conversation_idle_timeout_seconds
        self._observed_ongoing_activity_id: str | None = None
        self._explicit_resume_reason: str | None = None
        self._topic_continuation_evaluator = (
            topic_continuation_evaluator or TopicContinuationEvaluator()
        )
        self._autonomous_topic: InterruptedTopic | None = None
        self._recent_autonomous_texts: list[str] = []
        self._pending_confirmation_provider = pending_confirmation_provider or (
            lambda: False
        )
        self._autonomous_activity_policy = (
            autonomous_activity_policy or AutonomousActivityPolicy()
        )
        self._agent_memory_store = agent_memory_store
        self._processed_event_ids: deque[str] = deque(maxlen=1024)
        self._processed_event_id_set: set[str] = set()
        self._trace_logger = TraceLogger()

    @property
    def agent_state(self) -> AgentState:
        return self._agent_state

    @property
    def autonomous_topic(self) -> InterruptedTopic | None:
        return self._autonomous_topic

    def record_autonomous_output(
        self,
        *,
        activity_id: str,
        text: str,
        context: dict[str, object] | None = None,
    ) -> InterruptedTopic:
        """出力成功済みの自律発話を、再開判断可能な話題状態として保持する。"""

        metrics = (context or {}).get("topic_metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
        existing = self._autonomous_topic
        same_activity = (
            existing is not None and existing.source_activity_id == activity_id
        )
        topic = InterruptedTopic(
            topic_id=(
                existing.topic_id
                if same_activity and existing is not None
                else str(uuid4())
            ),
            source_activity_id=activity_id,
            original_text=text,
            status=(
                existing.status
                if same_activity and existing is not None
                else TopicLifecycleStatus.ACTIVE
            ),
            importance=self._metric(
                metrics, "importance", self._estimate_importance(text)
            ),
            interest=self._metric(
                metrics,
                "interest",
                (self._agent_state.current_drive.curiosity * 0.6)
                + (self._agent_state.current_drive.engagement * 0.4),
            ),
            incompleteness=self._metric(
                metrics, "incompleteness", self._estimate_incompleteness(text)
            ),
            exhaustion=self._metric(
                metrics, "exhaustion", self._estimate_exhaustion(text)
            ),
            interrupted_at=(
                existing.interrupted_at if same_activity and existing else None
            ),
            interruption_turns=(
                existing.interruption_turns if same_activity and existing else 0
            ),
            interruption_topics=(
                existing.interruption_topics if same_activity and existing else ()
            ),
        )
        self._autonomous_topic = topic
        self._trace_logger.info(
            "agent_life_service:autonomous_topic:recorded",
            topic_id=topic.topic_id,
            source_activity_id=topic.source_activity_id,
            topic_status=topic.status.value,
            importance=topic.importance,
            interest=topic.interest,
            incompleteness=topic.incompleteness,
            exhaustion=topic.exhaustion,
        )
        return topic

    def interrupt_autonomous_topic(
        self,
        *,
        activity_id: str,
        fallback_text: str,
        now: datetime | None = None,
    ) -> InterruptedTopic:
        topic = self._autonomous_topic
        if topic is None or topic.source_activity_id != activity_id:
            topic = InterruptedTopic(
                topic_id=str(uuid4()),
                source_activity_id=activity_id,
                original_text=fallback_text,
            )
        interrupted = topic.with_status(
            TopicLifecycleStatus.INTERRUPTED,
            interrupted_at=now or datetime.now(timezone.utc),
        )
        self._autonomous_topic = interrupted
        self._trace_logger.info(
            "agent_life_service:autonomous_topic:interrupted",
            topic_id=interrupted.topic_id,
            source_activity_id=activity_id,
            topic_status=interrupted.status.value,
        )
        return interrupted

    def complete_autonomous_topic(self, *, activity_id: str) -> None:
        topic = self._autonomous_topic
        if (
            topic is None
            or topic.source_activity_id != activity_id
            or topic.status
            in {TopicLifecycleStatus.INTERRUPTED, TopicLifecycleStatus.SUSPENDED}
        ):
            return
        self._autonomous_topic = topic.with_status(TopicLifecycleStatus.COMPLETED)
        self._recent_autonomous_texts = [
            *self._recent_autonomous_texts[-4:],
            topic.original_text,
        ]

    def plan_next_event(self, now: datetime | None = None) -> AgentEvent | None:
        """現在状態から、次に発生させる自律 Event を判断する。"""

        now = now or datetime.now(timezone.utc)
        self._update_drive_by_elapsed_time(now)
        self._update_emotion_by_elapsed_time(now)
        self.sync_from_activity_manager()
        self._trace_logger.write(
            "agent_life_service:plan_next_event:start",
            active_activity_exists=self._agent_state.active_activity is not None,
            pending_activity_count=len(self._agent_state.pending_activities),
            suspended_activity_count=len(self._agent_state.suspended_activities),
            drive_curiosity=self._agent_state.current_drive.curiosity,
            drive_engagement=self._agent_state.current_drive.engagement,
            drive_boredom=self._agent_state.current_drive.boredom,
            drive_energy=self._agent_state.current_drive.energy,
            emotion_mood=self._agent_state.current_emotion.mood.value,
            emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
        )

        if self._pending_confirmation_provider():
            self._trace_logger.debug(
                "agent_life_service:plan_next_event:skipped",
                reason="pending_confirmation_exists",
            )
            return None

        active_activity = self._agent_state.active_activity
        is_autonomous_lookahead = (
            active_activity is not None
            and active_activity.activity_type == ActivityType.AUTONOMOUS_TALK
            and active_activity.context.get("action_plan_prepared") is True
            and not self._agent_state.pending_activities
            and not self._agent_state.suspended_activities
        )

        if active_activity is not None and not is_autonomous_lookahead:
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="active_activity_exists",
                active_activity_type=active_activity.activity_type.value,
            )
            return None

        if self._agent_state.pending_activities:
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="pending_activity_exists",
                pending_activity_count=len(self._agent_state.pending_activities),
            )
            return None

        ongoing_activity = self._activity_manager.ongoing_activity
        if ongoing_activity is not None:
            self._observed_ongoing_activity_id = ongoing_activity.ongoing_activity_id
            self._trace_logger.debug(
                "agent_life_service:plan_next_event:skipped",
                reason="ongoing_activity_active",
                ongoing_activity_id=ongoing_activity.ongoing_activity_id,
                ongoing_activity_type=ongoing_activity.activity_type,
            )
            return None

        resume_reason = self._conversation_resume_reason(now)
        if resume_reason is None and self._is_within_pause(
            since=self._agent_state.last_user_input_at,
            now=now,
            pause_seconds=self._conversation_idle_timeout_seconds,
        ):
            self._trace_logger.debug(
                "agent_life_service:plan_next_event:skipped",
                reason="conversation_idle_timeout_not_reached",
                last_user_input_at=self._agent_state.last_user_input_at,
                conversation_idle_timeout_seconds=self._conversation_idle_timeout_seconds,
            )
            return None

        continuation_result = self._evaluate_topic_continuation(now)
        if continuation_result is not None and continuation_result.decision in {
            TopicContinuationDecision.WAIT,
            TopicContinuationDecision.SUSPEND_ORIGINAL,
            TopicContinuationDecision.ABANDON_ORIGINAL,
        }:
            self._trace_logger.debug(
                "agent_life_service:topic_continuation:no_event",
                topic_id=(
                    self._autonomous_topic.topic_id if self._autonomous_topic else None
                ),
                decision=continuation_result.decision.value,
                reasons=list(continuation_result.reasons),
            )
            return None

        if self._autonomous_activity_policy.should_defer_talking(
            self._agent_state.current_emotion
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="emotion_reduces_speech",
                emotion_mood=self._agent_state.current_emotion.mood.value,
                emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
            )
            return None

        if not self._agent_state.current_drive.should_start_autonomous_talk():
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="drive_too_weak",
                drive_curiosity=self._agent_state.current_drive.curiosity,
                drive_engagement=self._agent_state.current_drive.engagement,
                drive_boredom=self._agent_state.current_drive.boredom,
                drive_energy=self._agent_state.current_drive.energy,
            )
            return None

        minimum_pause_seconds = (
            self._autonomous_activity_policy.minimum_talk_interval_seconds(
                self._agent_state.current_emotion
            )
        )

        if not is_autonomous_lookahead and self._is_within_pause(
            since=self._agent_state.last_speech_finished_at,
            now=now,
            pause_seconds=minimum_pause_seconds,
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="after_speech_pause",
                pause_seconds=minimum_pause_seconds,
                last_speech_finished_at=self._agent_state.last_speech_finished_at,
            )
            return None

        if (
            not is_autonomous_lookahead
            and resume_reason is None
            and self._is_within_pause(
                since=self._agent_state.last_user_input_at,
                now=now,
                pause_seconds=minimum_pause_seconds,
            )
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="after_user_input_pause",
                pause_seconds=minimum_pause_seconds,
                last_user_input_at=self._agent_state.last_user_input_at,
            )
            return None

        autonomous_talk_interval_seconds = self._autonomous_talk_interval_seconds()
        if self._is_within_pause(
            since=self._last_autonomous_plan_rejected_at,
            now=now,
            pause_seconds=self._autonomous_plan_retry_backoff_seconds,
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="autonomous_plan_retry_backoff",
                backoff_seconds=self._autonomous_plan_retry_backoff_seconds,
                last_rejected_at=self._last_autonomous_plan_rejected_at,
            )
            return None
        if not is_autonomous_lookahead and self._is_within_pause(
            since=self._last_autonomous_talk_planned_at,
            now=now,
            pause_seconds=autonomous_talk_interval_seconds,
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="autonomous_talk_interval",
                interval_seconds=autonomous_talk_interval_seconds,
                last_autonomous_talk_planned_at=self._last_autonomous_talk_planned_at,
                emotion_arousal=self._agent_state.current_emotion.arousal,
                emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
                drive_energy=self._agent_state.current_drive.energy,
            )
            return None

        not_before = now
        if is_autonomous_lookahead and self._last_autonomous_talk_planned_at is not None:
            not_before = max(
                now,
                self._last_autonomous_talk_planned_at
                + timedelta(seconds=autonomous_talk_interval_seconds),
            )
        self._trace_logger.write(
            "agent_life_service:plan_next_event:planned",
            event_type=AgentEventType.CURIOSITY_PEAK.value,
            reason="internal_drive",
            drive=self._agent_state.current_drive.strongest_drive_name(),
            drive_curiosity=self._agent_state.current_drive.curiosity,
            drive_engagement=self._agent_state.current_drive.engagement,
            drive_boredom=self._agent_state.current_drive.boredom,
            drive_energy=self._agent_state.current_drive.energy,
            autonomous_talk_interval_seconds=autonomous_talk_interval_seconds,
            emotion_arousal=self._agent_state.current_emotion.arousal,
            emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
            resume_reason=resume_reason,
        )

        payload: dict[str, Any] = {
            "reason": "internal_drive",
            "drive": self._agent_state.current_drive.strongest_drive_name(),
            "autonomous_planned_for": not_before.isoformat(),
        }
        if is_autonomous_lookahead:
            payload.update(
                {
                    "lookahead": True,
                    "not_before": not_before.isoformat(),
                }
            )
        if resume_reason is not None and resume_reason != "no_conversation":
            payload["resume_reason"] = resume_reason
        if continuation_result is not None:
            payload.update(
                {
                    "continuation_decision": continuation_result.decision.value,
                    "continuation_reasons": list(continuation_result.reasons),
                    "reintroduction_required": continuation_result.reintroduction_required,
                    "selected_topic": continuation_result.selected_topic,
                    "interrupted_topic": (
                        self._autonomous_topic.original_text
                        if self._autonomous_topic is not None
                        else None
                    ),
                }
            )

        return AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload=payload,
            priority=10,
            discardable=True,
            replace_key="agent_life_service:curiosity_peak",
        )

    def end_conversation(self, *, reason: str) -> None:
        """明示的な会話終了後、次回の自律計画を許可する。"""

        self._explicit_resume_reason = reason
        self._trace_logger.info(
            "agent_life_service:conversation:ended",
            reason=reason,
        )

    def _conversation_resume_reason(self, now: datetime) -> str | None:
        if self._explicit_resume_reason is not None:
            return f"conversation_ended:{self._explicit_resume_reason}"
        if self._observed_ongoing_activity_id is not None:
            return f"ongoing_activity_completed:{self._observed_ongoing_activity_id}"
        if (
            self._agent_state.last_user_input_at is not None
            and not self._is_within_pause(
                since=self._agent_state.last_user_input_at,
                now=now,
                pause_seconds=self._conversation_idle_timeout_seconds,
            )
        ):
            return "conversation_idle_timeout"
        if self._agent_state.last_user_input_at is None:
            return "no_conversation"
        return None

    def handle_event(self, event: AgentEvent) -> AgentState:
        """Event を受け取り、AgentState に反映する。"""

        if event.event_id in self._processed_event_id_set:
            self._trace_logger.debug(
                "agent_life_service:handle_event:duplicate_skipped",
                event_id=event.event_id,
                event_type=event.event_type.value,
            )
            return self.sync_from_activity_manager()
        if len(self._processed_event_ids) == self._processed_event_ids.maxlen:
            oldest = self._processed_event_ids[0]
            self._processed_event_id_set.discard(oldest)
        self._processed_event_ids.append(event.event_id)
        self._processed_event_id_set.add(event.event_id)

        if event.event_type == AgentEventType.CURIOSITY_PEAK:
            planned_for = event.payload.get("autonomous_planned_for")
            try:
                accepted_at = (
                    datetime.fromisoformat(planned_for)
                    if isinstance(planned_for, str)
                    else event.occurred_at
                )
            except ValueError:
                accepted_at = event.occurred_at
            self._last_autonomous_talk_planned_at = accepted_at
            self._last_autonomous_plan_rejected_at = None
            self._explicit_resume_reason = None
            self._observed_ongoing_activity_id = None
            self._trace_logger.write(
                "agent_life_service:autonomous_plan:accepted",
                source_event_id=event.event_id,
                planned_for=accepted_at,
            )

        before_drive = self._agent_state.current_drive
        before_emotion = self._agent_state.current_emotion
        before_relationship = self._agent_state.relationship_memory.current

        self._agent_state = self._agent_state.with_drive(
            self._drive_state_updater.update_by_event(
                self._agent_state.current_drive,
                event,
            )
        )

        after_drive = self._agent_state.current_drive
        self._trace_logger.write(
            "agent_life_service:handle_event:drive_updated",
            event_type=event.event_type.value,
            before_curiosity=before_drive.curiosity,
            before_engagement=before_drive.engagement,
            before_boredom=before_drive.boredom,
            before_energy=before_drive.energy,
            after_curiosity=after_drive.curiosity,
            after_engagement=after_drive.engagement,
            after_boredom=after_drive.boredom,
            after_energy=after_drive.energy,
        )

        appraisal = self._emotion_appraiser.appraise(event)
        self._agent_state = self._agent_state.with_emotion(
            self._emotion_state_updater.apply(before_emotion, appraisal)
        )
        self._last_emotion_updated_at = max(
            self._last_emotion_updated_at,
            event.occurred_at,
        )
        after_emotion = self._agent_state.current_emotion
        self._trace_logger.info(
            "agent_life_service:handle_event:emotion_updated",
            event_type=event.event_type.value,
            source_event_id=event.event_id,
            appraisal_reason=appraisal.reason,
            before_arousal=before_emotion.arousal,
            before_valence=before_emotion.valence,
            before_talkativeness=before_emotion.talkativeness,
            after_arousal=after_emotion.arousal,
            after_valence=after_emotion.valence,
            after_talkativeness=after_emotion.talkativeness,
        )

        relationship_memory = self._relationship_state_updater.update(
            self._agent_state.relationship_memory,
            event,
        )
        self._agent_state = self._agent_state.with_relationship_memory(
            relationship_memory
        )
        after_relationship = relationship_memory.current
        relationship_changed = (
            after_relationship is not None and after_relationship != before_relationship
        )
        if relationship_changed and after_relationship is not None:
            self._trace_logger.info(
                "agent_life_service:relationship_updated",
                source_event_id=event.event_id,
                counterpart_id=after_relationship.counterpart_id,
                role=after_relationship.role,
                familiarity=after_relationship.familiarity,
                interaction_count=after_relationship.interaction_count,
            )
            self._persist_relationship_memory(relationship_memory, event.event_id)

        attention_target = (
            after_relationship.counterpart_id
            if relationship_changed and after_relationship is not None
            else self._agent_state.attention_target
        )
        source = event.payload.get("source")
        input_source = source if isinstance(source, str) and source.strip() else None
        self._agent_state = self._agent_state.with_attention_target(attention_target)
        self._agent_state = self._agent_state.with_memory(
            self._agent_state.memory.remember_episode(
                EpisodicMemory(
                    event_id=event.event_id,
                    event_type=event.event_type.value,
                    occurred_at=event.occurred_at,
                    activity_id=(
                        self._agent_state.active_activity.activity_id
                        if self._agent_state.active_activity is not None
                        else None
                    ),
                    counterpart_id=attention_target,
                )
            ).record_emotion(
                EmotionHistoryEntry(
                    source_event_id=event.event_id,
                    before=asdict(before_emotion),
                    after=asdict(after_emotion),
                    reason=appraisal.reason,
                    recorded_at=event.occurred_at,
                )
            )
        )
        self._persist_agent_memory()
        self._agent_state = self._agent_state.with_situation(
            self._agent_state.current_situation.observe_event(
                event_id=event.event_id,
                event_type=event.event_type.value,
                occurred_at=event.occurred_at,
                input_source=input_source,
                input_authority_role=event.authority.role,
                attention_target=attention_target,
            )
        )

        if event.event_type in (
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        ):
            self._agent_state = self._agent_state.mark_user_input_received(
                event.occurred_at
            )
            text = event.payload.get("text") or event.payload.get("comment")
            if self._short_term_memory is not None and isinstance(text, str):
                self._short_term_memory.add_user_input(
                    text,
                    counterpart_id=(
                        after_relationship.counterpart_id
                        if after_relationship is not None
                        else None
                    ),
                    display_name=(
                        after_relationship.display_name
                        if after_relationship is not None
                        else None
                    ),
                    created_at=event.occurred_at,
                )
            if self._autonomous_topic is not None and isinstance(text, str):
                self._autonomous_topic = self._autonomous_topic.add_interruption_topic(
                    text
                )

        if event.event_type == AgentEventType.SPEECH_STARTED:
            self._agent_state = self._agent_state.mark_speech_started(event.occurred_at)

        if event.event_type == AgentEventType.SPEECH_FINISHED:
            self._agent_state = self._agent_state.mark_speech_finished(event.occurred_at)

        return self.sync_from_activity_manager()

    def record_autonomous_plan_rejected(
        self,
        event: AgentEvent,
        *,
        rejected_at: datetime | None = None,
    ) -> None:
        """採用されなかった自律候補に短い再試行バックオフだけを適用する。"""

        if event.event_type != AgentEventType.CURIOSITY_PEAK:
            return
        self._last_autonomous_plan_rejected_at = (
            rejected_at or datetime.now(timezone.utc)
        )
        self._trace_logger.write(
            "agent_life_service:autonomous_plan:rejected",
            source_event_id=event.event_id,
            rejected_at=self._last_autonomous_plan_rejected_at,
            retry_backoff_seconds=self._autonomous_plan_retry_backoff_seconds,
        )

    def _persist_relationship_memory(
        self,
        memory: RelationshipMemory,
        source_event_id: str,
    ) -> None:
        if self._relationship_memory_store is None:
            return
        try:
            self._relationship_memory_store.save(memory)
        except Exception as error:
            self._trace_logger.error(
                "agent_life_service:relationship_persistence:failed",
                source_event_id=source_event_id,
                error_type=type(error).__name__,
            )

    def preview_relationship(self, event: AgentEvent) -> RelationshipState | None:
        """副作用なしで、このEvent適用後の相手との関係を返す。"""

        return self._relationship_state_updater.preview(
            self._agent_state.relationship_memory,
            event,
        )

    def sync_from_activity_manager(self) -> AgentState:
        """ActivityManager の状態を AgentState に同期する。"""

        before_memory = self._agent_state.memory
        pending = self._activity_manager.pending_activities()
        suspended = self._activity_manager.suspended_activities()
        foreground = self._activity_manager.foreground_activity
        ongoing = self._activity_manager.ongoing_activity
        unfinished = tuple(
            UnfinishedActivityMemory(
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                goal=activity.goal,
                status=activity.status.value,
                priority=activity.priority,
                updated_at=activity.updated_at,
            )
            for activity in self._activity_manager.list_activities()
            if activity.status.value in {"pending", "active", "waiting", "suspended"}
        )
        topic = self._autonomous_topic
        unrecovered_topic = (
            UnrecoveredTopicMemory(
                topic_id=topic.topic_id,
                source_activity_id=topic.source_activity_id,
                summary=topic.original_text,
                status=topic.status.value,
                importance=topic.importance,
                interrupted_at=topic.interrupted_at,
            )
            if topic is not None
            and topic.status
            in {TopicLifecycleStatus.INTERRUPTED, TopicLifecycleStatus.SUSPENDED}
            else None
        )
        self._agent_state = (
            self._agent_state.with_active_activity(
                self._activity_manager.foreground_activity
            )
            .with_pending_activities(pending)
            .with_suspended_activities(suspended)
            .with_memory(
                self._agent_state.memory.with_unfinished_activities(
                    unfinished
                ).with_unrecovered_topic(unrecovered_topic)
            )
            .with_situation(
                self._agent_state.current_situation.with_activity_snapshot(
                    active_activity_id=(
                        foreground.activity_id if foreground is not None else None
                    ),
                    active_activity_type=(
                        foreground.activity_type.value
                        if foreground is not None
                        else None
                    ),
                    pending_activity_count=len(pending),
                    suspended_activity_count=len(suspended),
                    ongoing_activity_id=(
                        ongoing.ongoing_activity_id if ongoing is not None else None
                    ),
                    ongoing_activity_type=(
                        ongoing.activity_type if ongoing is not None else None
                    ),
                    ongoing_activity_status=(
                        ongoing.status.value if ongoing is not None else None
                    ),
                )
            )
        )

        if self._agent_state.memory != before_memory:
            self._persist_agent_memory()

        return self._agent_state

    def learn_semantic_fact(
        self,
        *,
        subject: str,
        fact: str,
        importance: float = 0.5,
    ) -> AgentState:
        """意味記憶を短期会話ログやエピソード履歴と分けて保存する。"""

        self._agent_state = self._agent_state.with_memory(
            self._agent_state.memory.learn(
                SemanticMemory(subject=subject, fact=fact, importance=importance)
            )
        )
        self._persist_agent_memory()
        return self._agent_state

    def _persist_agent_memory(self) -> None:
        if self._agent_memory_store is None:
            return
        try:
            self._agent_memory_store.save(self._agent_state.memory.to_snapshot())
        except Exception as error:
            self._trace_logger.error(
                "agent_life_service:agent_memory_persistence:failed",
                error_type=type(error).__name__,
            )

    def update_emotion(self, emotion: EmotionState) -> AgentState:
        """感情・気分状態を更新する。"""

        self._agent_state = self._agent_state.with_emotion(emotion)
        return self._agent_state

    def update_drive(self, drive: DriveState) -> AgentState:
        """内的動機状態を更新する。"""

        self._agent_state = self._agent_state.with_drive(drive)
        return self._agent_state

    def _evaluate_topic_continuation(
        self, now: datetime
    ) -> TopicContinuationResult | None:
        topic = self._autonomous_topic
        if topic is None or topic.status not in {
            TopicLifecycleStatus.INTERRUPTED,
            TopicLifecycleStatus.SUSPENDED,
        }:
            return None
        result = self._topic_continuation_evaluator.evaluate(
            topic,
            emotion=self._agent_state.current_emotion,
            drive=self._agent_state.current_drive,
            now=now,
        )
        status_by_decision = {
            TopicContinuationDecision.SUSPEND_ORIGINAL: TopicLifecycleStatus.SUSPENDED,
            TopicContinuationDecision.ABANDON_ORIGINAL: TopicLifecycleStatus.ABANDONED,
            TopicContinuationDecision.START_NEW_TOPIC: TopicLifecycleStatus.ABANDONED,
            TopicContinuationDecision.WAIT: topic.status,
        }
        next_status = status_by_decision.get(
            result.decision, TopicLifecycleStatus.ACTIVE
        )
        self._autonomous_topic = topic.with_status(next_status)
        self._trace_logger.info(
            "agent_life_service:topic_continuation:evaluated",
            topic_id=topic.topic_id,
            previous_status=topic.status.value,
            next_status=next_status.value,
            decision=result.decision.value,
            reasons=list(result.reasons),
            reintroduction_required=result.reintroduction_required,
            selected_topic=result.selected_topic,
        )
        return result

    @staticmethod
    def _metric(metrics: dict[object, object], key: str, default: float) -> float:
        value = metrics.get(key, default)
        if not isinstance(value, (int, float)):
            return max(0.0, min(1.0, default))
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _estimate_importance(text: str) -> float:
        important_markers = ("大事", "将来", "目標", "価値", "約束", "やってみたい")
        return 0.75 if any(marker in text for marker in important_markers) else 0.4

    @staticmethod
    def _estimate_incompleteness(text: str) -> float:
        unfinished_markers = ("まず", "一つ目", "続き", "まだ", "……", "...")
        return 0.85 if any(marker in text for marker in unfinished_markers) else 0.25

    def _estimate_exhaustion(self, text: str) -> float:
        if not self._recent_autonomous_texts:
            return 0.0
        similarity = max(
            SequenceMatcher(None, text, previous).ratio()
            for previous in self._recent_autonomous_texts
        )
        return max(0.0, min(1.0, (similarity - 0.45) / 0.45))

    def _update_drive_by_elapsed_time(self, now: datetime) -> None:
        before_drive = self._agent_state.current_drive
        elapsed_seconds = (now - self._last_drive_updated_at).total_seconds()
        updated_drive = self._drive_state_updater.update_by_timestamps(
            self._agent_state.current_drive,
            previous_time=self._last_drive_updated_at,
            current_time=now,
        )
        self._agent_state = self._agent_state.with_drive(updated_drive)
        self._last_drive_updated_at = now
        after_drive = self._agent_state.current_drive
        self._trace_logger.write(
            "agent_life_service:drive_updated_by_elapsed_time",
            elapsed_seconds=elapsed_seconds,
            before_curiosity=before_drive.curiosity,
            before_engagement=before_drive.engagement,
            before_boredom=before_drive.boredom,
            before_energy=before_drive.energy,
            after_curiosity=after_drive.curiosity,
            after_engagement=after_drive.engagement,
            after_boredom=after_drive.boredom,
            after_energy=after_drive.energy,
        )

    def _update_emotion_by_elapsed_time(self, now: datetime) -> None:
        before = self._agent_state.current_emotion
        elapsed_seconds = max(
            0.0, (now - self._last_emotion_updated_at).total_seconds()
        )
        after = self._emotion_state_updater.decay(
            before, elapsed_seconds=elapsed_seconds
        )
        self._agent_state = self._agent_state.with_emotion(after)
        self._last_emotion_updated_at = max(self._last_emotion_updated_at, now)
        if after != before:
            self._trace_logger.debug(
                "agent_life_service:emotion_decayed",
                elapsed_seconds=elapsed_seconds,
                before_mood=before.mood.value,
                after_mood=after.mood.value,
                before_arousal=before.arousal,
                after_arousal=after.arousal,
                before_valence=before.valence,
                after_valence=after.valence,
                before_talkativeness=before.talkativeness,
                after_talkativeness=after.talkativeness,
            )

    def _autonomous_talk_interval_seconds(self) -> float:
        """テンションから次の自律発話までの最低間隔を決める。"""

        emotion = self._agent_state.current_emotion
        drive = self._agent_state.current_drive
        tension = (
            emotion.arousal * 0.45 + emotion.talkativeness * 0.45 + drive.energy * 0.10
        )
        tension = max(0.0, min(1.0, tension))

        minimum_interval_seconds = 8.0
        maximum_interval_seconds = 60.0
        return maximum_interval_seconds - (
            (maximum_interval_seconds - minimum_interval_seconds) * tension
        )

    def _is_within_pause(
        self,
        since: datetime | None,
        now: datetime,
        pause_seconds: float,
    ) -> bool:
        if since is None:
            return False

        return (now - since).total_seconds() < pause_seconds
