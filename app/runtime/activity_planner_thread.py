from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from queue import Empty, Queue

from app.domain.activities import Activity
from app.domain.autonomous_planning import (
    AutonomousSituationAnalysis,
    AutonomousSituationContext,
)
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.domain.trace_context import TraceContext, trace_context_from
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.autonomous_situation_evaluator import AutonomousSituationEvaluator
from app.runtime.behavior_planner import BehaviorPlanner
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue
from app.usecases.enrich_activity_with_topic_memory_usecase import (
    EnrichActivityWithTopicMemoryUsecase,
)
from app.utils.trace import TraceLogger


@dataclass(frozen=True)
class ActivityPlanningRequest:
    """ActivityPlannerThread への入力要求。"""

    now: datetime | None = None


class ActivityPlanningService:
    """Activity 計画の同期処理本体。Thread や Queue には依存しない。"""

    def __init__(
        self,
        agent_life_service: AgentLifeService,
        activity_manager: ActivityManager,
        enrich_activity_with_topic_memory_usecase: (
            EnrichActivityWithTopicMemoryUsecase | None
        ) = None,
        behavior_planner: BehaviorPlanner | None = None,
        autonomous_situation_evaluator: AutonomousSituationEvaluator | None = None,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
        available_activity_definitions: Callable[[], tuple[object, ...]] | None = None,
    ) -> None:
        self._agent_life_service = agent_life_service
        self._activity_manager = activity_manager
        self._enrich_activity_with_topic_memory_usecase = (
            enrich_activity_with_topic_memory_usecase
        )
        self._behavior_planner = behavior_planner
        self._autonomous_situation_evaluator = (
            autonomous_situation_evaluator or AutonomousSituationEvaluator()
        )
        self._short_term_memory = short_term_memory
        self._topic_history = topic_history
        self._available_activity_definitions = available_activity_definitions
        self._trace_logger = TraceLogger()

    def plan_once(self, now: datetime | None = None) -> PlannedActivity | None:
        """必要であれば Activity を1件計画する。"""

        event = self._agent_life_service.plan_next_event(now=now)
        if event is None:
            return None

        autonomous_plan = None
        if (
            event.event_type == AgentEventType.CURIOSITY_PEAK
            and self._behavior_planner is not None
        ):
            source_event = event
            event, autonomous_plan = self._plan_autonomous_event(event, now=now)
            if event is None:
                self._agent_life_service.record_autonomous_plan_rejected(
                    source_event,
                    rejected_at=now,
                )
                return None

        activity = self._create_activity(event)
        activity = self._enrich_activity(activity)
        return PlannedActivity(
            activity=activity,
            source="agent_life_service",
            planning_reason=(
                autonomous_plan.planning_reason
                if autonomous_plan is not None
                and autonomous_plan.planning_reason is not None
                else event.event_type.value
            ),
            priority=activity.priority,
            planned_drive=self._agent_life_service.agent_state.current_drive,
            planned_emotion=self._agent_life_service.agent_state.current_emotion,
            planned_topic=(
                autonomous_plan.topic if autonomous_plan is not None else None
            ),
            not_before=self._not_before(event),
        )

    @staticmethod
    def _not_before(event: AgentEvent) -> datetime | None:
        value = event.payload.get("not_before")
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _plan_autonomous_event(
        self, event: AgentEvent, *, now: datetime | None
    ) -> tuple[AgentEvent | None, ActivityPlan | None]:
        state = self._agent_life_service.agent_state
        topic = self._agent_life_service.autonomous_topic
        ongoing = self._activity_manager.ongoing_activity
        definitions = (
            self._available_activity_definitions()
            if self._available_activity_definitions is not None
            else ()
        )
        recent_topic_summary = ""
        if self._topic_history is not None:
            recent_topic_summary = "\n".join(
                entry.summary for entry in self._topic_history.recent_entries(limit=3)
            )
        context = AutonomousSituationContext(
            source_event_id=event.event_id,
            agent_state={
                "attention_target": state.attention_target,
                "active_activity": (
                    state.active_activity.activity_type.value
                    if state.active_activity is not None
                    else None
                ),
                "situation": state.current_situation.as_context(),
                "memory": state.memory.as_context(),
            },
            drive_state=asdict(state.current_drive),
            emotion_state=asdict(state.current_emotion),
            relationship_state=(
                state.relationship_memory.current.as_context()
                if state.relationship_memory.current is not None
                else {}
            ),
            topic_state=asdict(topic) if topic is not None else {},
            recent_speech_summary=(
                self._short_term_memory.build_recent_speech_summary(limit=3)
                if self._short_term_memory is not None
                else ""
            ),
            recent_topic_summary=recent_topic_summary,
            interrupted_topic=asdict(topic) if topic is not None else None,
            stream_status=state.stream_status,
            ongoing_activity=(
                {
                    "ongoing_activity_id": ongoing.ongoing_activity_id,
                    "activity_type": ongoing.activity_type,
                    "status": ongoing.status.value,
                    "goal": ongoing.goal,
                }
                if ongoing is not None
                else None
            ),
            available_activity_definitions=tuple(
                str(getattr(definition, "activity_type", definition))
                for definition in definitions
            ),
            current_time_context=(now or datetime.now(timezone.utc))
            .astimezone()
            .isoformat(),
            event_context=dict(event.payload),
            trace_context=event.trace_context,
        )
        planner = self._behavior_planner
        if planner is None:
            return event, None
        analysis = self._evaluate_autonomous_situation(event, context, planner)
        if analysis is None:
            return None, None
        plan = planner.plan_autonomous(context, analysis)
        if plan.decision in {BehaviorDecision.WAIT, BehaviorDecision.NO_ACTION}:
            return None, plan
        payload = {
            **event.payload,
            "autonomous_situation_context": asdict(context),
            "autonomous_situation_analysis": asdict(analysis),
            "behavior_plan": {
                "decision": plan.decision.value,
                "activity_type": plan.activity_type,
                "operation": (
                    plan.operation.value if plan.operation is not None else None
                ),
                "goal": plan.goal,
                "topic": plan.topic,
                "planning_reason": plan.planning_reason,
                "autonomous_action": plan.autonomous_action,
                "constraints": dict(plan.constraints),
                "planner_constraints": list(plan.planner_constraints),
                "behavior_plan_id": plan.behavior_plan_id,
            },
        }
        return (
            replace(
                event,
                payload=payload,
                trace_context=event.trace_context.derive(
                    behavior_plan_id=plan.behavior_plan_id
                ),
            ),
            plan,
        )

    def _evaluate_autonomous_situation(
        self,
        event: AgentEvent,
        context: AutonomousSituationContext,
        planner: BehaviorPlanner,
    ) -> AutonomousSituationAnalysis | None:
        if str(event.payload.get("selected_topic") or "").strip():
            return self._autonomous_situation_evaluator.evaluate(context)

        recent_memories = self._load_recent_topic_memory_context()
        conversation_history: tuple[dict[str, object], ...] = ()
        if self._short_term_memory is not None:
            conversation_history = tuple(
                {"role": item.role, "text": item.text}
                for item in self._short_term_memory.recent_conversation(limit=6)
            )
        definition = ActivityDefinition(
            activity_type="autonomous_talk",
            display_name="自律発話",
            required_capability=None,
            provider_plugin_id="runtime",
            description="現在状態を総合して具体的な話題を選び、短く自律的に話す",
            supported_operations=(ActivityOperation.START,),
            constraints_schema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 120,
                        "description": "このTurnで実際に扱う具体的な話題",
                    },
                    "topic_relation": {
                        "type": "string",
                        "enum": ["continue", "shift", "new"],
                        "description": "直近話題との関係",
                    },
                },
                "required": ["topic", "topic_relation"],
                "additionalProperties": False,
            },
        )
        planning_context = BehaviorPlanningContext(
            user_text="",
            source_event_id=context.source_event_id,
            available_capabilities=frozenset(),
            event_type=AgentEventType.CURIOSITY_PEAK.value,
            authority_role="system",
            instruction_trusted=True,
            activity_definitions=(definition,),
            drive=dict(context.drive_state),
            emotion=dict(context.emotion_state),
            relationship=dict(context.relationship_state),
            situation={
                "agent_state": dict(context.agent_state),
                "topic_state": dict(context.topic_state),
                "recent_speech_summary": context.recent_speech_summary,
                "recent_topic_summary": context.recent_topic_summary,
                "stream_status": context.stream_status,
                "current_time": context.current_time_context,
                "event": dict(context.event_context),
            },
            memory={"topic_memories": list(recent_memories)},
            conversation_history=conversation_history,
            related_knowledge=recent_memories,
            trace_context=context.trace_context,
        )
        try:
            situation = asyncio.run(planner.evaluate_situation(planning_context))
        except Exception as error:
            self._trace_logger.warning(
                "activity_planning_service:autonomous_situation_failed",
                source_event_id=context.source_event_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return None
        topic = str(situation.constraints.get("topic") or "").strip()
        if situation.activity_candidate != "autonomous_talk" or not topic:
            self._trace_logger.warning(
                "activity_planning_service:autonomous_topic_unresolved",
                source_event_id=context.source_event_id,
                activity_candidate=situation.activity_candidate,
                reason=situation.reason,
            )
            return None
        relation = str(situation.constraints.get("topic_relation") or "new")
        action = {
            "continue": "topic_continue",
            "shift": "topic_shift",
            "new": "autonomous_talk",
        }.get(relation, "autonomous_talk")
        analysis = self._autonomous_situation_evaluator.evaluate(
            replace(
                context,
                event_context={
                    **context.event_context,
                    "selected_topic": topic,
                    "continuation_decision": (
                        "resume_original"
                        if relation == "continue"
                        else "start_new_topic"
                        if relation == "shift"
                        else ""
                    ),
                },
            )
        )
        merged_constraints = {
            **analysis.constraints,
            "topic_relation": relation,
            "avoid_repetition": True,
            "do_not_claim_external_execution": True,
        }
        result = replace(
            analysis,
            suggested_action=action,
            topic_candidate=topic,
            planning_reason=situation.reason or analysis.planning_reason,
            relation_to_interrupted_topic=relation,
            constraints=merged_constraints,
        )
        self._trace_logger.info(
            "activity_planning_service:autonomous_topic_selected",
            source_event_id=context.source_event_id,
            topic=topic,
            topic_relation=relation,
            recent_memory_count=len(recent_memories),
        )
        return result

    def _load_recent_topic_memory_context(self) -> tuple[dict[str, object], ...]:
        usecase = self._enrich_activity_with_topic_memory_usecase
        if usecase is None:
            return ()
        return asyncio.run(usecase.load_recent_context())

    def _create_activity(self, event: AgentEvent) -> Activity:
        """Event から Activity を生成し、AgentState にも同期する。"""

        activity = self._activity_manager.handle_event(event)
        self._agent_life_service.handle_event(event)
        self._agent_life_service.sync_from_activity_manager()
        return activity

    def _enrich_activity(self, activity: Activity) -> Activity:
        """Activity に関連長期記憶を追加する。"""

        if self._enrich_activity_with_topic_memory_usecase is None:
            return activity

        enriched = asyncio.run(
            self._enrich_activity_with_topic_memory_usecase.enrich(activity)
        )
        if enriched is activity:
            return activity
        canonical = self._activity_manager.update_activity_context(
            activity.activity_id,
            dict(enriched.context),
        )
        return canonical or enriched

    def cancel_planned_activity(self, planned: PlannedActivity, *, reason: str) -> None:
        self._activity_manager.cancel_activity(
            planned.activity.activity_id, reason=reason
        )
        self._agent_life_service.sync_from_activity_manager()


class ActivityPlannerThread(threading.Thread):
    """Activity 計画要求を Queue から受け取り、計画結果を Queue に出力する常駐処理。"""

    def __init__(
        self,
        request_queue: Queue[ActivityPlanningRequest],
        planned_activity_queue: PlannedActivityQueue,
        planning_service: ActivityPlanningService,
        idle_sleep_seconds: float = 0.1,
        max_queue_size: int = 3,
        daemon: bool = True,
    ) -> None:
        super().__init__(name="ActivityPlannerThread", daemon=daemon)
        self._request_queue = request_queue
        self._planned_activity_queue = planned_activity_queue
        self._planning_service = planning_service
        self._idle_sleep_seconds = idle_sleep_seconds
        self._max_queue_size = max_queue_size
        self._stop_requested = threading.Event()
        self._planning = threading.Event()
        self._cancellation_lock = threading.Lock()
        self._autonomous_cancellation_generation = 0
        self._canceling_trace_context: TraceContext | None = None
        self._trace_logger = TraceLogger()

    def run_once(self, request: ActivityPlanningRequest) -> PlannedActivity | None:
        """Activity 計画要求を1件処理し、結果を PlannedActivityQueue に追加する。"""

        queue_size = self._planned_activity_queue.size()
        if queue_size >= self._max_queue_size:
            self._trace_logger.write(
                "activity_planner_thread:run_once:queue_full",
                queue_size=queue_size,
                max_queue_size=self._max_queue_size,
            )
            return None

        with self._cancellation_lock:
            generation = self._autonomous_cancellation_generation
        planned_activity = self._planning_service.plan_once(now=request.now)
        if planned_activity is None:
            self._trace_logger.write(
                "activity_planner_thread:run_once:no_activity",
                queue_size=queue_size,
                max_queue_size=self._max_queue_size,
            )
            return None

        with self._cancellation_lock:
            canceled_during_planning = (
                generation != self._autonomous_cancellation_generation
                and planned_activity.activity.activity_type.value == "autonomous_talk"
            )
            if not canceled_during_planning:
                self._planned_activity_queue.put(planned_activity)
        if canceled_during_planning:
            canceled_trace = trace_context_from(planned_activity.activity.context)
            self._planning_service.cancel_planned_activity(
                planned_activity,
                reason="user_text_received_during_planning",
            )
            self._trace_logger.info(
                "activity_planner_thread:autonomous_planning_canceled",
                canceling_trace_id=(
                    self._canceling_trace_context.trace_id
                    if self._canceling_trace_context is not None
                    else None
                ),
                canceled_trace_id=(
                    canceled_trace.trace_id if canceled_trace is not None else None
                ),
                planned_activity_id=planned_activity.planned_activity_id,
                activity_id=planned_activity.activity.activity_id,
                reason="user_text_received_during_planning",
            )
            return None

        self._trace_logger.write(
            "activity_planner_thread:run_once:planned_activity_added",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            activity_type=planned_activity.activity.activity_type.value,
            priority=planned_activity.effective_priority,
            queue_size=self._planned_activity_queue.size(),
        )

        return planned_activity

    def run(self) -> None:
        """stop() が呼ばれるまで Activity 計画要求を処理する。"""

        self._stop_requested.clear()
        self._trace_logger.write("activity_planner_thread:run:start")

        while not self._stop_requested.is_set():
            try:
                request = self._request_queue.get(timeout=self._idle_sleep_seconds)
            except Empty:
                continue

            try:
                self._planning.set()
                self.run_once(request)
            finally:
                self._planning.clear()
                self._request_queue.task_done()

        self._trace_logger.write("activity_planner_thread:run:stopped")

    def stop(self) -> None:
        """継続実行処理を停止する。"""

        self._stop_requested.set()
        self._trace_logger.write("activity_planner_thread:stop:requested")

    def cancel_inflight_autonomous(
        self,
        *,
        source_event_id: str,
        trace_context: TraceContext | None = None,
    ) -> None:
        with self._cancellation_lock:
            self._autonomous_cancellation_generation += 1
            generation = self._autonomous_cancellation_generation
            self._canceling_trace_context = trace_context
        self._trace_logger.info(
            "activity_planner_thread:autonomous_cancel_checkpoint",
            source_event_id=source_event_id,
            cancellation_generation=generation,
            canceling_trace_id=trace_context.trace_id if trace_context else None,
            cancel_reason="user_text_received",
        )

    @property
    def is_running(self) -> bool:
        """継続実行中かどうかを返す。"""

        return self.is_alive() and not self._stop_requested.is_set()

    @property
    def is_busy(self) -> bool:
        """Activity計画要求を処理中かどうかを返す。"""

        return self._planning.is_set()
