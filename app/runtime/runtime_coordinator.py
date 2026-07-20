from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, replace
from queue import Queue
from time import monotonic
from typing import Any, cast

from app.core.plugins import PluginManager
from app.core.plugins.user_request import UserRequestKind, interpret_user_request
from app.domain.actions import ActionPlanGroup
from app.domain.activities import (
    Activity,
    ActivityStatus,
    ActivityType,
    OngoingActivity,
)
from app.domain.activity_turn_result import ActivityTurnResult
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    ActivityPlan,
    ActivityPlanEvaluation,
    BehaviorDecision,
    BehaviorPlanningContext,
    OngoingActivityPlanningContext,
)
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.domain.pending_confirmation import (
    ConfirmationResolutionKind,
    PendingConfirmation,
)
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
)
from app.runtime.activity_registry import ActivityRegistry
from app.runtime.activity_result_builder import build_activity_result
from app.runtime.activity_turn_result_factory import (
    action_planning_failure_group,
    canceled_output_group,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_execution import prepare_autonomous_execution
from app.runtime.autonomous_output import completed_speech_text
from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_filter import DefaultEventFilter, EventFilter
from app.runtime.event_prioritizer import DefaultEventPrioritizer, EventPrioritizer
from app.runtime.event_queue import EventQueue
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.pending_confirmation import (
    ConfirmationResolver,
    PendingConfirmationManager,
)
from app.shared.contracts.plugins.runtime import (
    CommandHandler,
    PlannedActivityInterpreter,
    PluginActivityState,
    PluginActivityStatus,
    PluginCapability,
    UserIntentInterpreter,
)
from app.utils.trace import TraceLogger


class RuntimeCoordinator:
    """外部イベント処理と常駐 Thread の起動・停止を調停する中核。"""

    def __init__(
        self,
        event_queue: EventQueue,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        activity_planning_request_queue: Queue[ActivityPlanningRequest],
        activity_planner_thread: ActivityPlannerThread,
        activity_executor_thread: ActivityExecutorThread,
        event_filter: EventFilter | None = None,
        event_prioritizer: EventPrioritizer | None = None,
        event_buffer: EventBuffer | None = None,
        agent_life_service: AgentLifeService | None = None,
        plugin_manager: PluginManager | None = None,
        behavior_planner: BehaviorPlanner | None = None,
        activity_plan_validator: ActivityPlanValidator | None = None,
        activity_registry: ActivityRegistry | None = None,
        pending_confirmation_manager: PendingConfirmationManager | None = None,
        confirmation_resolver: ConfirmationResolver | None = None,
        autonomous_planning_enabled: bool = True,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
        require_startup_completion: bool = False,
        async_initializers: tuple[Callable[[], Awaitable[None]], ...] = (),
        autonomous_planning_poll_seconds: float = 0.5,
    ) -> None:
        self._event_queue = event_queue
        self._activity_manager = activity_manager
        self._action_planner = action_planner
        self._action_scheduler = action_scheduler
        self._activity_planning_request_queue = activity_planning_request_queue
        self._activity_planner_thread = activity_planner_thread
        self._activity_executor_thread = activity_executor_thread
        self._event_filter = event_filter or DefaultEventFilter()
        self._event_prioritizer = event_prioritizer or DefaultEventPrioritizer()
        self._event_buffer = event_buffer or EventBuffer()
        self._agent_life_service = agent_life_service or AgentLifeService(
            activity_manager
        )
        self._plugin_manager = plugin_manager
        self._behavior_planner = behavior_planner
        self._activity_plan_validator = activity_plan_validator
        self._activity_registry = activity_registry
        self._pending_confirmation_manager = pending_confirmation_manager
        self._confirmation_resolver = confirmation_resolver or ConfirmationResolver()
        self._ongoing_activity_coordinator = OngoingActivityCoordinator(
            activity_manager
        )
        self._last_behavior_evaluation: ActivityPlanEvaluation | None = None
        self._last_behavior_fallback_plan: ActivityPlan | None = None
        self._running = False
        self._thread_join_timeout_seconds = 1.0
        self._trace_logger = TraceLogger()
        self._event_subscribers: list[
            tuple[
                AgentEventType,
                Callable[[AgentEvent], Awaitable[object]],
                Callable[[AgentEvent], bool] | None,
            ]
        ] = []
        self._event_enrichers: list[Callable[[AgentEvent], AgentEvent]] = []
        self._autonomous_planning_enabled = autonomous_planning_enabled
        self._short_term_memory = short_term_memory
        self._topic_history = topic_history
        self._startup_completed = not require_startup_completion
        self._async_initializers = async_initializers
        self._initializers_completed = False
        self._autonomous_planning_poll_seconds = max(
            autonomous_planning_poll_seconds, 0.05
        )
        self._last_autonomous_planning_request_at: float | None = None
        self._idle_sleep_seconds = 0.05

    @property
    def autonomous_planning_enabled(self) -> bool:
        return self._autonomous_planning_enabled

    @property
    def plugin_manager(self) -> PluginManager | None:
        return self._plugin_manager

    @property
    def activity_manager(self) -> ActivityManager:
        return self._activity_manager

    @property
    def agent_state(self) -> AgentState:
        """管理・診断用途のimmutableな現在状態スナップショット。"""

        return self._agent_life_service.agent_state

    def diagnostic_snapshot(self) -> dict[str, object]:
        """会話本文や外部秘密を含めず、Coreの現在状態を診断用に返す。"""

        state = self._agent_life_service.agent_state
        foreground = self._activity_manager.foreground_activity
        ongoing = self._activity_manager.ongoing_activity
        relationship = state.relationship_memory.current
        manager = self._plugin_manager
        plugin_statuses: dict[str, str] = {}
        if manager is not None:
            for plugin in manager.list_plugins():
                status = manager.status(plugin.plugin_id)
                plugin_statuses[plugin.plugin_id] = (
                    status.value if status is not None else "unknown"
                )
        return {
            "emotion": asdict(state.current_emotion),
            "drive": asdict(state.current_drive),
            "relationship": (
                {
                    "present": True,
                    "role": relationship.role,
                    "familiarity": relationship.familiarity,
                    "trust": relationship.trust,
                    "affinity": relationship.affinity,
                    "interaction_count": relationship.interaction_count,
                }
                if relationship is not None
                else {"present": False}
            ),
            "relationship_count": len(state.relationship_memory.relationships),
            "memory": {
                "episodic_count": len(state.memory.episodic),
                "semantic_count": len(state.memory.semantic),
                "unfinished_activity_count": len(state.memory.unfinished_activities),
                "unrecovered_topic_count": len(state.memory.unrecovered_topics),
                "emotion_history_count": len(state.memory.emotion_history),
            },
            "situation": {
                "last_event_type": state.current_situation.last_event_type,
                "last_event_at": (
                    state.current_situation.last_event_at.isoformat()
                    if state.current_situation.last_event_at is not None
                    else None
                ),
                "input_source": state.current_situation.input_source,
                "active_activity_type": state.current_situation.active_activity_type,
                "pending_activity_count": state.current_situation.pending_activity_count,
                "suspended_activity_count": state.current_situation.suspended_activity_count,
                "ongoing_activity_type": state.current_situation.ongoing_activity_type,
                "ongoing_activity_status": state.current_situation.ongoing_activity_status,
            },
            "activity": {
                "foreground_id": (
                    foreground.activity_id if foreground is not None else None
                ),
                "foreground_type": (
                    foreground.activity_type.value if foreground is not None else None
                ),
                "foreground_status": (
                    foreground.status.value if foreground is not None else None
                ),
                "pending_count": len(self._activity_manager.pending_activities()),
                "suspended_count": len(self._activity_manager.suspended_activities()),
                "ongoing_id": (
                    ongoing.ongoing_activity_id if ongoing is not None else None
                ),
                "ongoing_type": ongoing.activity_type if ongoing is not None else None,
                "ongoing_status": ongoing.status.value if ongoing is not None else None,
            },
            "plugins": (
                {
                    "statuses": plugin_statuses,
                    "available_capabilities": sorted(manager.list_capabilities()),
                }
                if manager is not None
                else {"statuses": {}, "available_capabilities": []}
            ),
            "stream_status": state.stream_status,
        }

    @property
    def last_behavior_evaluation(self) -> ActivityPlanEvaluation | None:
        return self._last_behavior_evaluation

    @property
    def last_behavior_fallback_plan(self) -> ActivityPlan | None:
        return self._last_behavior_fallback_plan

    @property
    def pending_confirmation(self) -> PendingConfirmation | None:
        manager = self._pending_confirmation_manager
        return manager.current() if manager is not None else None

    async def _execute_explicit_activity(self, activity: Activity) -> ActionPlanGroup:
        prepare_autonomous_execution(activity)
        try:
            action_plan_group = await self._action_planner.plan(activity)
        except Exception as error:
            action_plan_group = action_planning_failure_group(activity, error)
            if action_plan_group.activity_turn_result is not None:
                self._activity_manager.record_turn_result(
                    action_plan_group.activity_turn_result
                )
            self._trace_logger.warning(
                "runtime_coordinator:action_planning:failed",
                activity_id=activity.activity_id,
                failure_stage="action_planning",
                error_type=type(error).__name__,
            )
            self._activity_manager.complete_processed_activity(activity.activity_id)
            self._agent_life_service.sync_from_activity_manager()
            raise
        output_result = await self._action_scheduler.execute(action_plan_group)
        if (
            output_result is not None
            and action_plan_group.activity_turn_result is not None
        ):
            self._activity_manager.record_output_result(
                action_plan_group.activity_turn_result, output_result
            )
        self._activity_manager.complete_processed_activity(activity.activity_id)
        self._agent_life_service.sync_from_activity_manager()
        return action_plan_group

    async def publish_event(self, event: AgentEvent) -> None:
        await self.publish_events([event])

    async def submit_user_text(
        self,
        text: str,
        *,
        source: str = "external",
        authority: InputAuthority = InputAuthority.USER,
    ) -> None:
        """本番入力AdapterからUSER_TEXTを共通ルーティングへ投入する公開入口。"""

        await self.publish_event(
            AgentEvent(
                event_type=AgentEventType.USER_TEXT,
                payload={"text": text, "source": source},
                authority=authority,
            )
        )

    async def execute_external_event(
        self, event: AgentEvent, *, missing_result_code: str = "activity_turn.missing"
    ) -> ActivityTurnResult:
        """Execute an outer-layer event through the shared Activity/Action pipeline."""

        group = await self._handle_event(event)
        base = group.activity_turn_result
        if base is None:
            raise RuntimeError(missing_result_code)
        return self._activity_manager.get_turn_result(base.activity_turn_id) or base

    async def execute_external_activity(self, activity: Activity) -> ActivityTurnResult:
        """Register and execute an Activity supplied through a Core contract."""

        registered = self._activity_manager.register_plugin_activity(activity)
        group = await self._execute_explicit_activity(registered)
        base = group.activity_turn_result
        if base is None:
            raise RuntimeError("activity_turn.missing")
        return self._activity_manager.get_turn_result(base.activity_turn_id) or base

    def cancel_outputs(self) -> bool:
        return self._action_scheduler.cancel_outputs()

    def configure_activity_policy(self, policy: object) -> None:
        """Install a policy through component-owned structural contracts."""

        gate = cast(Any, policy)
        self._activity_manager.set_activity_policy(gate)
        self._action_planner.set_activity_policy(gate)
        self._action_scheduler.set_activity_policy(gate)

    def subscribe_event(
        self,
        event_type: AgentEventType,
        handler: Callable[[AgentEvent], Awaitable[object]],
        *,
        predicate: Callable[[AgentEvent], bool] | None = None,
    ) -> None:
        self._event_subscribers.append((event_type, handler, predicate))

    def register_event_enricher(
        self, enricher: Callable[[AgentEvent], AgentEvent]
    ) -> None:
        self._event_enrichers.append(enricher)

    async def publish_events(self, events: list[AgentEvent]) -> None:
        self._trace_logger.write(
            "runtime_coordinator:publish_events:start",
            event_count=len(events),
        )
        for event in events:
            filtered_event = self._event_filter.filter(event)
            if filtered_event is None:
                continue
            self._agent_life_service.handle_event(filtered_event)
            subscriber = next(
                (
                    handler
                    for event_type, handler, predicate in self._event_subscribers
                    if filtered_event.event_type == event_type
                    and (predicate is None or predicate(filtered_event))
                ),
                None,
            )
            if subscriber is not None:
                await subscriber(filtered_event)
                continue
            if filtered_event.event_type == AgentEventType.USER_TEXT:
                self._trace_logger.info(
                    "runtime_coordinator:event_received",
                    **filtered_event.trace_context.as_log_fields(),
                    event_type=filtered_event.event_type.value,
                    source=str(filtered_event.payload.get("source") or "unknown"),
                    priority=filtered_event.priority,
                )
                self._trace_logger.user_input(
                    source=str(filtered_event.payload.get("source") or "unknown"),
                    event_id=filtered_event.event_id,
                    text=str(filtered_event.payload.get("text") or ""),
                    trace_id=filtered_event.trace_context.trace_id,
                    parent_trace_id=filtered_event.trace_context.parent_trace_id,
                    activity_turn_id=filtered_event.trace_context.activity_turn_id,
                    confirmation_id=filtered_event.trace_context.confirmation_id,
                )
                if (
                    self._behavior_planner is not None
                    and self._activity_plan_validator is not None
                ):
                    routed_event = await self._route_behavior(filtered_event)
                elif self._has_plugin_capability(
                    PluginCapability.USER_INTENT_INTERPRETER.value
                ):
                    routed_event = await self._route_plugin_user_input(filtered_event)
                else:
                    routed_event = self._with_plugin_availability(filtered_event)
                if routed_event is None:
                    continue
                filtered_event = routed_event
            elif (
                filtered_event.event_type == AgentEventType.APP_STARTED
                and self._behavior_planner is not None
                and self._activity_plan_validator is not None
            ):
                routed_event = await self._route_behavior(filtered_event)
                if routed_event is None:
                    continue
                filtered_event = routed_event
            self._trace_logger.write(
                "runtime_coordinator:publish_events:filtered",
                event_type=event.event_type.value,
                event_id=event.event_id,
            )
            prioritized_event = self._event_prioritizer.prioritize(filtered_event)
            foreground_before_input = self._activity_manager.foreground_activity
            prepared_activity = self._activity_manager.prepare_user_input(
                prioritized_event
            )
            if prioritized_event.event_type == AgentEventType.USER_TEXT:
                self._activity_planner_thread.cancel_inflight_autonomous(
                    source_event_id=prioritized_event.event_id,
                    trace_context=prioritized_event.trace_context,
                )
                if (
                    foreground_before_input is not None
                    and foreground_before_input.activity_type
                    == ActivityType.AUTONOMOUS_TALK
                ):
                    self._agent_life_service.interrupt_autonomous_topic(
                        activity_id=foreground_before_input.activity_id,
                        fallback_text=foreground_before_input.goal,
                    )
                discarded_deferred = self._activity_manager.discard_deferred_autonomous(
                    reason="user_conversation_started"
                )
                canceled = self._activity_executor_thread.cancel_pending_autonomous(
                    source_event_id=prioritized_event.event_id,
                    reason="user_text_received",
                )
                if canceled:
                    self._trace_logger.info(
                        "runtime_coordinator:user_input:pending_autonomous_canceled",
                        event_id=prioritized_event.event_id,
                        planned_activity_ids=[
                            item.planned_activity_id for item in canceled
                        ],
                        activity_ids=[item.activity.activity_id for item in canceled],
                    )
                if discarded_deferred:
                    self._trace_logger.info(
                        "runtime_coordinator:user_input:deferred_autonomous_discarded",
                        event_id=prioritized_event.event_id,
                        activity_ids=[
                            activity.activity_id for activity in discarded_deferred
                        ],
                        reason="restart_with_fresh_context_after_conversation",
                    )
            if prepared_activity is not None:
                self._agent_life_service.sync_from_activity_manager()
                self._trace_logger.info(
                    "runtime_coordinator:user_input:conversation_prepared",
                    event_id=prioritized_event.event_id,
                    activity_id=prepared_activity.activity_id,
                    activity_type=prepared_activity.activity_type.value,
                )
            self._trace_logger.write(
                "runtime_coordinator:publish_events:prioritized",
                event_type=prioritized_event.event_type.value,
                event_id=prioritized_event.event_id,
                priority=prioritized_event.priority,
                discardable=prioritized_event.discardable,
                replace_key=prioritized_event.replace_key,
            )
            self._event_buffer.put(prioritized_event)

        for buffered_event in self._event_buffer.drain():
            self._trace_logger.write(
                "runtime_coordinator:publish_events:queue_put",
                event_type=buffered_event.event_type.value,
                event_id=buffered_event.event_id,
                priority=buffered_event.priority,
                discardable=buffered_event.discardable,
                replace_key=buffered_event.replace_key,
                queue_empty_before_put=self._event_queue.empty(),
            )
            await self._event_queue.put(buffered_event)

    def _has_plugin_capability(self, capability: str) -> bool:
        manager = self._plugin_manager
        return manager is not None and capability in manager.list_capabilities()

    def _conversation_history(self) -> tuple[dict[str, object], ...]:
        if self._short_term_memory is None:
            return ()
        return tuple(
            {
                "role": item.role,
                "text": item.text,
                "counterpart_id": item.counterpart_id,
                "display_name": item.display_name,
                "created_at": (
                    item.created_at.isoformat() if item.created_at is not None else None
                ),
            }
            for item in self._short_term_memory.recent_conversation(limit=6)
        )

    def _related_knowledge(
        self, memory_context: dict[str, object]
    ) -> tuple[dict[str, object], ...]:
        knowledge: list[dict[str, object]] = []
        semantic_facts = memory_context.get("semantic_facts")
        if isinstance(semantic_facts, list):
            knowledge.extend(
                dict(item) for item in semantic_facts if isinstance(item, dict)
            )
        if self._topic_history is not None:
            knowledge.extend(
                {
                    "category": item.category.value,
                    "summary": item.summary,
                    "source_text": item.source_text,
                    "activity_type": item.activity_type,
                }
                for item in self._topic_history.recent_entries(limit=5)
            )
        return tuple(knowledge)

    @staticmethod
    def _startup_activity_definition() -> ActivityDefinition:
        return ActivityDefinition(
            activity_type=ActivityType.STARTUP_REACTION.value,
            display_name="起動直後の反応",
            required_capability=None,
            provider_plugin_id="runtime",
            description="現在状態を総合して起動直後の最初のActivityを行う",
            supported_operations=(ActivityOperation.START,),
            constraints_schema={"type": "object", "additionalProperties": True},
        )

    async def _route_behavior(self, event: AgentEvent) -> AgentEvent | None:
        planner = self._behavior_planner
        validator = self._activity_plan_validator
        manager = self._plugin_manager
        if planner is None or validator is None or manager is None:
            return self._with_plugin_availability(event)
        agent_state = self._agent_life_service.agent_state
        ongoing = self._activity_manager.ongoing_activity
        relationship = self._agent_life_service.preview_relationship(event)
        relationship_context = (
            relationship.as_context() if relationship is not None else {}
        )
        situation_context = agent_state.current_situation.as_context()
        memory_context = agent_state.memory.as_context()
        conversation_history = self._conversation_history()
        related_knowledge = self._related_knowledge(memory_context)
        event = replace(
            event,
            payload={
                **event.payload,
                "input_authority": {
                    "role": event.authority.role,
                    "instruction_trusted": event.authority.instruction_trusted,
                },
                "relationship": relationship_context,
                "situation": situation_context,
                "memory": memory_context,
                "emotion": asdict(agent_state.current_emotion),
                "drive": asdict(agent_state.current_drive),
                "conversation_history": conversation_history,
                "related_knowledge": related_knowledge,
            },
        )
        definitions = (
            self._activity_registry.list_definitions()
            if self._activity_registry is not None
            else manager.list_activity_definitions()
        )
        if event.event_type == AgentEventType.APP_STARTED:
            definitions = (*definitions, self._startup_activity_definition())
        planning_context = BehaviorPlanningContext(
            user_text=str(event.payload.get("text") or ""),
            source_event_id=event.event_id,
            available_capabilities=manager.list_capabilities(),
            event_type=event.event_type.value,
            request_kind=(
                interpret_user_request(str(event.payload.get("text") or "")).kind.value
                if event.event_type == AgentEventType.USER_TEXT
                else None
            ),
            authority_role=event.authority.role,
            instruction_trusted=event.authority.instruction_trusted,
            activity_definitions=definitions,
            active_activity_definition=manager.active_activity_definition(),
            ongoing_activity_type=(
                ongoing.activity_type if ongoing is not None else None
            ),
            ongoing_activity=self._ongoing_planning_context(ongoing),
            drive=asdict(agent_state.current_drive),
            emotion=asdict(agent_state.current_emotion),
            relationship=relationship_context,
            situation=situation_context,
            memory=memory_context,
            conversation_history=conversation_history,
            related_knowledge=related_knowledge,
            last_activity_result=self._activity_manager.last_activity_result,
            trace_context=event.trace_context,
        )
        situation_payload: dict[str, object]
        confirmation_payload: dict[str, object] = {}
        plan: ActivityPlan | None = None
        pending_manager = self._pending_confirmation_manager
        pending = pending_manager.current() if pending_manager is not None else None
        if pending is not None:
            event = replace(
                event,
                trace_context=event.trace_context.derive(
                    parent_trace_id=pending.original_trace_id,
                    confirmation_id=pending.confirmation_id,
                ),
            )
            planning_context = replace(
                planning_context, trace_context=event.trace_context
            )
            assert pending_manager is not None
            resolution = self._confirmation_resolver.resolve(
                planning_context.user_text,
                pending,
                trace_context=event.trace_context,
            )
            if resolution.kind == ConfirmationResolutionKind.NEW_REQUEST:
                pending_manager.resolve(
                    pending,
                    resolution,
                    resolution_event_id=event.event_id,
                    trace_context=event.trace_context,
                )
            elif resolution.kind == ConfirmationResolutionKind.AFFIRMATIVE:
                resolved = pending_manager.resolve(
                    pending,
                    resolution,
                    resolution_event_id=event.event_id,
                    trace_context=event.trace_context,
                )
                plan = self._confirmed_plan(resolved.candidate_plan)
                snapshot_analysis = resolved.context_snapshot.get("situation_analysis")
                situation_payload = (
                    dict(snapshot_analysis)
                    if isinstance(snapshot_analysis, dict)
                    else {}
                )
                confirmation_payload = self._confirmation_payload(
                    resolved,
                    resolution=resolution.kind.value,
                    final_plan=plan,
                )
                self._trace_logger.debug(
                    "pending_confirmation:confirmed_plan",
                    confirmation_id=resolved.confirmation_id,
                    final_plan=plan,
                    plugin_handler_will_be_called=plan.required_capability is not None,
                )
            elif resolution.kind in {
                ConfirmationResolutionKind.NEGATIVE,
                ConfirmationResolutionKind.CANCEL,
            }:
                resolved = pending_manager.resolve(
                    pending,
                    resolution,
                    resolution_event_id=event.event_id,
                    trace_context=event.trace_context,
                )
                return self._confirmation_response_event(
                    event,
                    resolved,
                    resolution=resolution.kind.value,
                    waiting=False,
                )
            else:
                revised = pending_manager.revise(
                    pending,
                    resolution,
                    source_event_id=event.event_id,
                    constraint_validation=validator.validate_constraints,
                )
                return self._confirmation_response_event(
                    event,
                    revised or pending,
                    resolution=(
                        resolution.kind.value
                        if revised is not None
                        else "max_attempts_reached"
                    ),
                    waiting=revised is not None,
                )
        if plan is None:
            situation = await planner.evaluate_situation(planning_context)
            plan = await planner.plan(planning_context, situation)
            situation_payload = asdict(situation)
        if plan.decision == BehaviorDecision.ASK_CONFIRMATION:
            if pending_manager is None:
                return self._with_plugin_availability(event)
            self._last_behavior_evaluation = validator.validate(plan)
            self._last_behavior_fallback_plan = None
            created = pending_manager.create(
                plan,
                source_event_id=event.event_id,
                current_ongoing_activity_id=(
                    ongoing.ongoing_activity_id if ongoing is not None else None
                ),
                context_snapshot={"situation_analysis": situation_payload},
                trace_context=event.trace_context,
            )
            return self._confirmation_response_event(
                event,
                created,
                resolution=None,
                waiting=True,
            )
        evaluation = validator.validate(plan)
        plan = evaluation.plan
        event = replace(
            event,
            trace_context=event.trace_context.derive(
                behavior_plan_id=plan.behavior_plan_id
            ),
        )
        self._last_behavior_evaluation = evaluation
        self._last_behavior_fallback_plan = None
        self._trace_logger.info(
            "behavior_planner:activity_plan_evaluated",
            **event.trace_context.derive(
                behavior_plan_id=plan.behavior_plan_id
            ).as_log_fields(),
            decision=plan.decision.value,
            activity_type=plan.activity_type,
            operation=plan.operation.value if plan.operation else None,
            speech_act=plan.speech_act.value,
            required_capability=plan.required_capability,
            provider_plugin_id=plan.provider_plugin_id,
            accepted=evaluation.accepted,
            reason=plan.reason,
        )
        behavior_payload: dict[str, object] = {
            "situation_analysis": situation_payload,
            "behavior_plan": self._plan_payload(plan),
            "behavior_plan_result": asdict(evaluation.result),
            "ongoing_transition": self._ongoing_transition_payload(
                plan,
                current_status=ongoing.status.value if ongoing is not None else None,
            ),
            **confirmation_payload,
            "trace_context": event.trace_context.derive(
                behavior_plan_id=plan.behavior_plan_id
            ),
        }
        if not evaluation.accepted:
            behavior_payload["activity_execution_result"] = ActivityExecutionResult(
                activity_type=plan.activity_type,
                operation=plan.operation.value if plan.operation else None,
                status=ActivityExecutionStatus.REJECTED,
                capability=plan.required_capability,
                provider=plan.provider_plugin_id,
                payload={"summary": evaluation.result.summary},
                failure_reason=str(
                    evaluation.result.data.get("reason") or "activity_rejected"
                ),
                constraints=plan.constraints,
                source_event_id=event.event_id,
                trace_id=event.trace_context.trace_id,
                parent_trace_id=event.trace_context.parent_trace_id,
                behavior_plan_id=plan.behavior_plan_id,
            )
            fallback_plan = planner.fallback_after_rejection(evaluation)
            self._last_behavior_fallback_plan = fallback_plan
            behavior_payload["behavior_fallback_plan"] = self._plan_payload(
                fallback_plan
            )
            fallback_event = self._with_execution_fallback(
                event,
                contexts=[{"activity_plan_result": asdict(evaluation.result)}],
                reason="activity_capability_rejected",
                confidence=plan.confidence,
            )
            return replace(
                fallback_event,
                payload={**fallback_event.payload, **behavior_payload},
            )
        if plan.decision == BehaviorDecision.SWITCH_ACTIVITY:
            routed = await self._route_activity_switch(event, plan, planning_context)
            if routed is None:
                return None
        elif plan.required_capability is not None:
            routed = await self._route_plugin_user_input(
                event,
                plugin_id=plan.provider_plugin_id,
                required_capability=plan.required_capability,
                activity_plan=plan,
            )
            if routed is None:
                return None
        else:
            routed = self._with_plugin_availability(event)
            execution_rejected = bool(routed.payload.get("execution_request_unmatched"))
            behavior_payload["activity_execution_result"] = ActivityExecutionResult(
                activity_type=plan.activity_type,
                operation=plan.operation.value if plan.operation else None,
                status=(
                    ActivityExecutionStatus.REJECTED
                    if execution_rejected
                    else ActivityExecutionStatus.WAITING_INPUT
                ),
                payload={
                    "summary": (
                        "要求された外部処理は実行されなかった"
                        if execution_rejected
                        else "Conversation Activityの応答Turnを生成する"
                    )
                },
                failure_reason=(
                    str(routed.payload.get("execution_match_reason"))
                    if execution_rejected
                    else None
                ),
                constraints=plan.constraints,
                source_event_id=event.event_id,
                trace_id=event.trace_context.trace_id,
                parent_trace_id=event.trace_context.parent_trace_id,
                behavior_plan_id=plan.behavior_plan_id,
            )
        return replace(routed, payload={**routed.payload, **behavior_payload})

    @staticmethod
    def _confirmed_plan(plan: ActivityPlan) -> ActivityPlan:
        if plan.requested_new_activity:
            decision = BehaviorDecision.SWITCH_ACTIVITY
        elif plan.operation == ActivityOperation.START:
            decision = BehaviorDecision.START_ACTIVITY
        elif plan.operation in {ActivityOperation.CONTINUE, ActivityOperation.STOP}:
            decision = BehaviorDecision.CONTINUE_ACTIVITY
        else:
            decision = BehaviorDecision.CONVERSATION
        return replace(
            plan,
            decision=decision,
            activity_type=(
                "conversation"
                if decision == BehaviorDecision.CONVERSATION
                else plan.activity_type
            ),
            required_capability=(
                None
                if decision == BehaviorDecision.CONVERSATION
                else plan.required_capability
            ),
            provider_plugin_id=(
                None
                if decision == BehaviorDecision.CONVERSATION
                else plan.provider_plugin_id
            ),
            planner_constraints=tuple(
                item
                for item in plan.planner_constraints
                if "確認" not in item and "低確信度" not in item
            )
            + ("確認解決後もCapabilityを再検証する",),
            confidence=1.0,
            reason=f"confirmed:{plan.reason}",
        )

    def _confirmation_response_event(
        self,
        event: AgentEvent,
        pending: PendingConfirmation,
        *,
        resolution: str | None,
        waiting: bool,
    ) -> AgentEvent:
        payload = self._confirmation_payload(pending, resolution=resolution)
        summary = (
            pending.question
            if waiting
            else self._confirmation_resolution_summary(resolution)
        )
        conversation_plan = ActivityPlan(
            decision=(
                BehaviorDecision.ASK_CONFIRMATION
                if waiting
                else BehaviorDecision.CONVERSATION
            ),
            activity_type="confirmation" if waiting else "conversation",
            goal=summary,
            operation=ActivityOperation.DISCUSS,
            planner_constraints=(
                "確認対象を変更しない",
                "確認前のActivity実行・停止・切替を主張しない",
                "内部用語を発話しない",
            ),
            confidence=pending.candidate_confidence,
            reason=resolution or "pending_confirmation_created",
        )
        result = ActivityExecutionResult(
            activity_type="confirmation",
            operation=pending.candidate_operation,
            status=(
                ActivityExecutionStatus.WAITING_INPUT
                if waiting
                else ActivityExecutionStatus.CANCELED
            ),
            payload={"summary": summary, "question": pending.question},
            failure_reason=None if waiting else resolution,
            constraints=dict(pending.candidate_constraints),
            source_event_id=event.event_id,
        )
        routed = self._with_plugin_availability(event)
        return replace(
            routed,
            payload={
                **routed.payload,
                "behavior_plan": self._plan_payload(conversation_plan),
                "activity_execution_result": result,
                **payload,
            },
        )

    @staticmethod
    def _confirmation_payload(
        pending: PendingConfirmation,
        *,
        resolution: str | None,
        final_plan: ActivityPlan | None = None,
    ) -> dict[str, object]:
        return {
            "pending_confirmation": {
                "confirmation_id": pending.confirmation_id,
                "source_event_id": pending.source_event_id,
                "resolution_event_id": pending.resolution_event_id,
                "confirmation_type": pending.confirmation_type.value,
                "status": pending.status.value,
                "candidate_activity_type": pending.candidate_activity_type,
                "candidate_operation": pending.candidate_operation,
                "candidate_goal": pending.candidate_goal,
                "candidate_constraints": dict(pending.candidate_constraints),
                "candidate_confidence": pending.candidate_confidence,
                "candidate_constraints_schema_version": (
                    pending.candidate_constraints_schema_version
                ),
                "current_ongoing_activity_id": pending.current_ongoing_activity_id,
                "question": pending.question,
                "attempt_count": pending.attempt_count,
                "max_attempts": pending.max_attempts,
                "resolution": resolution,
                "final_behavior_plan": (
                    RuntimeCoordinator._plan_payload(final_plan)
                    if final_plan is not None
                    else None
                ),
                "final_behavior_plan_id": (
                    f"{pending.confirmation_id}:{pending.resolution_event_id}"
                    if final_plan is not None
                    and pending.resolution_event_id is not None
                    else None
                ),
                "original_trace_id": pending.original_trace_id,
                "resolution_trace_id": pending.resolution_trace_id,
                "parent_trace_id": pending.parent_trace_id,
            }
        }

    @staticmethod
    def _confirmation_resolution_summary(resolution: str | None) -> str:
        if resolution == ConfirmationResolutionKind.NEGATIVE.value:
            return "確認候補は実行せず、現在の状態を維持する"
        if resolution == ConfirmationResolutionKind.CANCEL.value:
            return "確認を取り消し、候補は実行しない"
        return "意図を確定できなかったため、候補は実行しない"

    async def _route_plugin_user_input(
        self,
        event: AgentEvent,
        *,
        plugin_id: str | None = None,
        required_capability: str | None = None,
        activity_plan: ActivityPlan | None = None,
    ) -> AgentEvent | None:
        manager = self._plugin_manager
        if manager is None:
            return self._with_plugin_availability(event)
        if activity_plan is not None and self._activity_plan_validator is not None:
            immediate_evaluation = self._activity_plan_validator.validate(activity_plan)
            activity_plan = immediate_evaluation.plan
            if not immediate_evaluation.accepted:
                self._trace_logger.info(
                    "activity_constraints:rejected_before_plugin_handler",
                    activity_type=activity_plan.activity_type,
                    reason=immediate_evaluation.result.data.get("reason"),
                )
                return self._with_execution_fallback(
                    event,
                    contexts=[
                        {"activity_plan_result": asdict(immediate_evaluation.result)}
                    ],
                    reason=str(
                        immediate_evaluation.result.data.get("reason")
                        or "activity_plan_rejected_before_execution"
                    ),
                    confidence=activity_plan.confidence,
                )
        text = str(event.payload.get("text") or "")
        for plugin in manager.get_plugins_by_capability(
            PluginCapability.USER_INTENT_INTERPRETER.value
        ):
            if plugin_id is not None and plugin.plugin_id != plugin_id:
                continue
            planned_interpreter = getattr(plugin, "interpret_activity_plan", None)
            if activity_plan is not None and callable(planned_interpreter):
                intent_result = await cast(
                    PlannedActivityInterpreter, plugin
                ).interpret_activity_plan(activity_plan, text)
            else:
                interpreter = cast(UserIntentInterpreter, plugin)
                intent_result = await interpreter.interpret_user_text(text)
            if not intent_result.handled:
                continue
            if intent_result.conversation_context.get("execution_requested") is False:
                return replace(
                    event,
                    payload={
                        **event.payload,
                        "plugin_contexts": [dict(intent_result.conversation_context)],
                        **dict(intent_result.conversation_context),
                        "available_plugin_capabilities": sorted(
                            manager.list_capabilities()
                        ),
                        "execution_performed": False,
                    },
                )
            if required_capability is not None and not manager.is_capability_available(
                required_capability, plugin.plugin_id
            ):
                self._trace_logger.warning(
                    "runtime_coordinator:activity_capability_rejected_before_execution",
                    plugin_id=plugin.plugin_id,
                    capability=required_capability,
                )
                return self._with_execution_fallback(
                    event,
                    contexts=[dict(intent_result.conversation_context)],
                    reason="activity_capability_revoked_before_execution",
                    confidence=intent_result.confidence,
                )
            if not manager.is_capability_available(
                PluginCapability.COMMAND_HANDLER.value, plugin.plugin_id
            ):
                self._trace_logger.warning(
                    "runtime_coordinator:capability_execution_rejected",
                    plugin_id=plugin.plugin_id,
                    capability=PluginCapability.COMMAND_HANDLER.value,
                    reason="unavailable_before_execution",
                )
                return self._with_execution_fallback(
                    event,
                    contexts=[dict(intent_result.conversation_context)],
                    reason="selected_capability_unavailable",
                    confidence=intent_result.confidence,
                )
            self._trace_logger.info(
                "runtime_coordinator:capability_matched",
                plugin_id=plugin.plugin_id,
                capability=PluginCapability.COMMAND_HANDLER.value,
                confidence=intent_result.confidence,
            )
            operation = self._activity_operation(activity_plan, intent_result)
            constraints = activity_plan.constraints if activity_plan is not None else {}
            session_before = self._plugin_session_context(plugin)
            turn_started = False
            if operation != "start":
                try:
                    ongoing = self._ongoing_activity_coordinator.verify_context(
                        session_id=self._optional_context_str(
                            session_before, "session_id"
                        ),
                        plugin_id=plugin.plugin_id,
                    )
                    if ongoing is None:
                        raise RuntimeError("継続対象のOngoingActivityがありません。")
                    self._ongoing_activity_coordinator.begin_turn(
                        input_text=text,
                        source_event_id=event.event_id,
                        operation=operation,
                        constraints=(
                            ongoing.context.get("constraints", constraints)
                            if isinstance(
                                ongoing.context.get("constraints", constraints), dict
                            )
                            else constraints
                        ),
                    )
                    turn_started = True
                except RuntimeError as error:
                    self._trace_logger.error(
                        "runtime_coordinator:ongoing_activity_sync_rejected",
                        plugin_id=plugin.plugin_id,
                        operation=operation,
                        reason=str(error),
                    )
                    self._rollback_plugin_and_ongoing(
                        plugin, reason="ongoing_activity_context_mismatch"
                    )
                    return self._with_execution_fallback(
                        event,
                        contexts=[dict(intent_result.conversation_context)],
                        reason="ongoing_activity_context_mismatch",
                        confidence=intent_result.confidence,
                    )
            handler = cast(CommandHandler, plugin)
            execution = await handler.execute_command(intent_result)
            for capability in execution.unavailable_capabilities:
                if manager.is_capability_available(capability, plugin.plugin_id):
                    manager.set_capability_availability(
                        plugin.plugin_id, capability, available=False
                    )
                    self._trace_logger.warning(
                        "runtime_coordinator:capability_revoked_after_failure",
                        plugin_id=plugin.plugin_id,
                        capability=capability,
                        reason=execution.reason,
                    )
            if execution.handled and execution.activity_request is not None:
                request = execution.activity_request
                try:
                    execution_result, ongoing_snapshot = (
                        self._synchronize_plugin_activity(
                            plugin=plugin,
                            activity_state=request.state,
                            request_context=dict(request.context),
                            activity_kind=request.activity_kind,
                            activity_type=(
                                activity_plan.activity_type
                                if activity_plan is not None
                                else request.activity_kind
                            ),
                            response_text=request.response_text,
                            capability=required_capability,
                            operation=operation,
                            constraints=constraints,
                            goal=(
                                activity_plan.goal
                                if activity_plan is not None
                                else f"Plugin {request.plugin_id} の継続Activityを実行する"
                            ),
                            input_text=text,
                            source_event_id=event.event_id,
                            turn_started=turn_started,
                        )
                    )
                except Exception as error:
                    self._trace_logger.error(
                        "runtime_coordinator:plugin_ongoing_activity_sync_failed",
                        plugin_id=plugin.plugin_id,
                        operation=operation,
                        error_type=type(error).__name__,
                    )
                    return self._with_execution_fallback(
                        event,
                        contexts=[dict(request.context)],
                        reason="ongoing_activity_sync_failed",
                        confidence=intent_result.confidence,
                    )
                activity = Activity(
                    activity_type=ActivityType.PLUGIN_ACTIVITY,
                    goal=f"Plugin {request.plugin_id} のActivityを実行する",
                    priority=request.priority,
                    context={
                        **dict(request.context),
                        "plugin_id": request.plugin_id,
                        "prepared_response_text": request.response_text,
                        "plugin_memory_policy": request.memory_policy,
                        "ongoing_activity": ongoing_snapshot,
                        "ongoing_activity_id": ongoing_snapshot.ongoing_activity_id,
                        "activity_execution_result": execution_result,
                        "ongoing_transition": self._ongoing_transition_payload(
                            activity_plan,
                            current_status=ongoing_snapshot.status.value,
                            stopped=(
                                operation == "stop"
                                and ongoing_snapshot.status
                                in {ActivityStatus.COMPLETED, ActivityStatus.CANCELED}
                            ),
                            transition_result="succeeded",
                        ),
                    },
                    interruptible=False,
                )
                registered = self._activity_manager.register_plugin_activity(activity)
                await self._execute_explicit_activity(registered)
                self._trace_logger.info(
                    "runtime_coordinator:plugin_activity_executed",
                    plugin_id=request.plugin_id,
                    activity_id=registered.activity_id,
                    activity_kind=request.activity_kind,
                )
                return None
            if bool(execution.conversation_context.get("execution_requested")):
                if turn_started:
                    failed_result = ActivityExecutionResult(
                        activity_type=(
                            activity_plan.activity_type
                            if activity_plan is not None
                            else "plugin_activity"
                        ),
                        operation=operation,
                        status=ActivityExecutionStatus.FAILED,
                        capability=required_capability,
                        provider=plugin.plugin_id,
                        payload={"summary": execution.reason or "Plugin実行に失敗した"},
                        failure_reason=execution.reason or "execution_not_completed",
                        constraints=constraints,
                    )
                    failure_state = execution.activity_state
                    can_continue = (
                        failure_state is not None
                        and failure_state.status
                        in {
                            PluginActivityStatus.WAITING_INPUT,
                            PluginActivityStatus.SUSPENDED,
                        }
                    )
                    failure_context = dict(execution.conversation_context)
                    if failure_state is not None:
                        failure_context.update(
                            {
                                "plugin_session_id": failure_state.session_id,
                                "plugin_activity_status": failure_state.status.value,
                            }
                        )
                    self._ongoing_activity_coordinator.record_execution(
                        failed_result,
                        context_updates=failure_context,
                        expected_input=(
                            failure_state.expected_input
                            if can_continue and failure_state is not None
                            else ""
                        ),
                        waiting_input=can_continue,
                    )
                    if not can_continue:
                        self._ongoing_activity_coordinator.cancel(
                            reason=execution.reason or "plugin_continue_failed"
                        )
                return self._with_execution_fallback(
                    event,
                    contexts=[dict(execution.conversation_context)],
                    reason=execution.reason or "execution_not_completed",
                    confidence=intent_result.confidence,
                )
            return replace(
                event,
                payload={
                    **event.payload,
                    "plugin_contexts": [dict(execution.conversation_context)],
                    **dict(execution.conversation_context),
                    "plugin_intent_reason": intent_result.reason,
                    "available_plugin_capabilities": sorted(
                        manager.list_capabilities()
                    ),
                    "execution_performed": False,
                },
            )
        return self._with_plugin_availability(event)

    def _synchronize_plugin_activity(
        self,
        *,
        plugin: object,
        activity_state: PluginActivityState,
        request_context: dict[str, object],
        activity_kind: str,
        activity_type: str,
        response_text: str,
        capability: str | None,
        operation: str,
        constraints: dict[str, object],
        goal: str,
        input_text: str,
        source_event_id: str,
        turn_started: bool,
    ) -> tuple[ActivityExecutionResult, OngoingActivity]:
        plugin_id = str(
            request_context.get("plugin_id") or getattr(plugin, "plugin_id", "")
        )
        session_id = activity_state.session_id
        session_status = activity_state.status
        is_terminal = session_status in {
            PluginActivityStatus.COMPLETED,
            PluginActivityStatus.CANCELED,
        }
        result_status = (
            ActivityExecutionStatus.CANCELED
            if session_status == PluginActivityStatus.CANCELED
            else (
                ActivityExecutionStatus.SUCCEEDED
                if session_status == PluginActivityStatus.COMPLETED
                else ActivityExecutionStatus.WAITING_INPUT
            )
        )
        execution_result = ActivityExecutionResult(
            activity_type=activity_type,
            operation=operation,
            status=result_status,
            capability=capability,
            provider=plugin_id,
            payload={
                "summary": response_text,
                "activity_kind": activity_kind,
                "ongoing": not is_terminal,
            },
            constraints=dict(constraints),
        )
        context_updates = {
            "plugin_id": plugin_id,
            "capability": capability,
            "plugin_session_id": session_id,
            "plugin_state_version": request_context.get("plugin_state_version"),
            "plugin_activity_status": session_status.value,
            "constraints": dict(constraints),
        }
        if operation == "start":
            try:
                ongoing = self._ongoing_activity_coordinator.start(
                    activity_type=activity_type,
                    goal=goal,
                    expected_input=activity_state.expected_input,
                    end_condition=activity_state.end_condition,
                    context=context_updates,
                    input_text=input_text,
                    source_event_id=source_event_id,
                    operation=operation,
                    constraints=constraints,
                )
                linker = getattr(plugin, "link_ongoing_activity", None)
                if not callable(linker):
                    raise RuntimeError(
                        "PluginがOngoingActivity関連付けに対応していません。"
                    )
                linker(ongoing.ongoing_activity_id)
                context_updates["ongoing_activity_id"] = ongoing.ongoing_activity_id
            except Exception:
                self._rollback_plugin_and_ongoing(
                    plugin, reason="ongoing_activity_start_failed"
                )
                raise
        else:
            verified = self._ongoing_activity_coordinator.verify_context(
                session_id=session_id,
                plugin_id=plugin_id,
            )
            if verified is None or not turn_started:
                raise RuntimeError("Plugin継続Turnが開始されていません。")
            ongoing = verified
            context_updates["ongoing_activity_id"] = verified.ongoing_activity_id

        recorded = self._ongoing_activity_coordinator.record_execution(
            execution_result,
            context_updates=context_updates,
            expected_input="" if is_terminal else activity_state.expected_input,
            waiting_input=session_status == PluginActivityStatus.WAITING_INPUT,
        )
        if session_status == PluginActivityStatus.COMPLETED:
            terminal = self._ongoing_activity_coordinator.complete(
                reason="plugin_session_completed"
            )
            if terminal is not None:
                recorded = terminal
        elif session_status == PluginActivityStatus.CANCELED:
            terminal = self._ongoing_activity_coordinator.cancel(
                reason="plugin_session_canceled"
            )
            if terminal is not None:
                recorded = terminal
        elif session_status == PluginActivityStatus.SUSPENDED:
            paused = self._ongoing_activity_coordinator.pause(
                reason="plugin_session_paused"
            )
            if paused is not None:
                recorded = paused
        self._trace_logger.info(
            "runtime_coordinator:plugin_ongoing_activity_synchronized",
            plugin_id=plugin_id,
            ongoing_activity_id=recorded.ongoing_activity_id,
            session_id=session_id,
            operation=operation,
            ongoing_status=recorded.status.value,
            session_status=session_status.value,
            activity_turn_id=recorded.turns[-1].turn_id if recorded.turns else None,
        )
        return execution_result, recorded

    @staticmethod
    def _optional_context_str(context: dict[str, object], key: str) -> str | None:
        value = context.get(key)
        return str(value) if value is not None else None

    @staticmethod
    def _plugin_session_context(plugin: object) -> dict[str, object]:
        snapshot = getattr(plugin, "snapshot", None)
        value = snapshot() if callable(snapshot) else {}
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _activity_operation(
        activity_plan: ActivityPlan | None,
        intent_result: object,
    ) -> str:
        if activity_plan is not None and activity_plan.operation is not None:
            return activity_plan.operation.value
        command = getattr(intent_result, "command", None)
        operation = getattr(command, "operation", None)
        return str(operation) if operation is not None else "continue"

    def _rollback_plugin_and_ongoing(self, plugin: object, *, reason: str) -> None:
        self._ongoing_activity_coordinator.cancel(reason=reason)
        rollback = getattr(plugin, "rollback_active_session", None)
        if callable(rollback):
            rollback(reason)
        self._trace_logger.warning(
            "runtime_coordinator:plugin_ongoing_activity_rolled_back",
            plugin_id=getattr(plugin, "plugin_id", None),
            reason=reason,
        )

    @staticmethod
    def _plan_payload(plan: ActivityPlan) -> dict[str, object]:
        payload = asdict(plan)
        payload["decision"] = plan.decision.value
        payload["operation"] = plan.operation.value if plan.operation else None
        payload["speech_act"] = plan.speech_act.value
        payload["ongoing_input_decision"] = (
            plan.ongoing_input_decision.value
            if plan.ongoing_input_decision is not None
            else None
        )
        return payload

    async def _route_activity_switch(
        self,
        event: AgentEvent,
        plan: ActivityPlan,
        planning_context: BehaviorPlanningContext,
    ) -> AgentEvent | None:
        validator = self._activity_plan_validator
        current = planning_context.active_activity_definition
        if validator is None or current is None:
            return self._with_execution_fallback(
                event,
                contexts=[],
                reason="switch_current_activity_definition_missing",
                confidence=plan.confidence,
            )
        stop_plan = ActivityPlan(
            decision=BehaviorDecision.CONTINUE_ACTIVITY,
            activity_type=current.activity_type,
            goal=f"{current.display_name}を停止してActivityを切り替える",
            required_capability=current.required_capability,
            provider_plugin_id=current.provider_plugin_id,
            operation=ActivityOperation.STOP,
            planner_constraints=("停止成功後だけ新しいActivityを開始する",),
            speech_act=plan.speech_act,
            confidence=plan.confidence,
            reason="switch_stop_current",
            ongoing_input_decision=plan.ongoing_input_decision,
            current_activity_type=current.activity_type,
        )
        stop_evaluation = validator.validate(stop_plan)
        if not stop_evaluation.accepted:
            self._trace_logger.warning(
                "runtime_coordinator:activity_switch_stop_rejected",
                current_activity_type=current.activity_type,
                requested_activity_type=plan.activity_type,
            )
            return self._with_execution_fallback(
                event,
                contexts=[{"stop_result": asdict(stop_evaluation.result)}],
                reason="switch_stop_rejected",
                confidence=plan.confidence,
            )
        stop_routed = await self._route_plugin_user_input(
            event,
            plugin_id=current.provider_plugin_id,
            required_capability=current.required_capability,
            activity_plan=stop_plan,
        )
        if (
            stop_routed is not None
            or self._activity_manager.ongoing_activity is not None
        ):
            self._trace_logger.warning(
                "runtime_coordinator:activity_switch_stop_failed",
                current_activity_type=current.activity_type,
                requested_activity_type=plan.activity_type,
            )
            return self._with_execution_fallback(
                stop_routed or event,
                contexts=[],
                reason="switch_stop_failed",
                confidence=plan.confidence,
            )
        routed = await self._route_plugin_user_input(
            event,
            plugin_id=plan.provider_plugin_id,
            required_capability=plan.required_capability,
            activity_plan=plan,
        )
        self._trace_logger.info(
            "runtime_coordinator:activity_switch_finished",
            previous_activity_type=current.activity_type,
            requested_activity_type=plan.activity_type,
            started=routed is None,
        )
        return routed

    @staticmethod
    def _ongoing_planning_context(
        ongoing: OngoingActivity | None,
    ) -> OngoingActivityPlanningContext | None:
        if ongoing is None:
            return None
        summary_keys = (
            "plugin_id",
            "capability",
            "plugin_session_id",
            "plugin_state_version",
            "plugin_activity_status",
        )
        constraints = ongoing.context.get("constraints")
        recent_turns: tuple[dict[str, object], ...] = tuple(
            {
                "turn_id": turn.turn_id,
                "sequence": turn.sequence,
                "operation": turn.operation,
                "input": turn.input_text,
                "execution_status": (
                    turn.execution_result.status.value
                    if turn.execution_result is not None
                    else None
                ),
            }
            for turn in ongoing.turns[-3:]
        )
        return OngoingActivityPlanningContext(
            ongoing_activity_id=ongoing.ongoing_activity_id,
            activity_type=ongoing.activity_type,
            status=ongoing.status.value,
            goal=ongoing.goal,
            constraints=dict(constraints) if isinstance(constraints, dict) else {},
            expected_input=ongoing.expected_input,
            turn_count=len(ongoing.turns),
            current_operation=ongoing.turns[-1].operation if ongoing.turns else None,
            plugin_state_summary={
                key: ongoing.context[key]
                for key in summary_keys
                if key in ongoing.context
            },
            recent_turns=recent_turns,
        )

    @staticmethod
    def _ongoing_transition_payload(
        plan: ActivityPlan | None,
        *,
        current_status: str | None,
        stopped: bool = False,
        transition_result: str | None = None,
    ) -> dict[str, object]:
        if plan is None:
            return {}
        return {
            "ongoing_input_decision": (
                plan.ongoing_input_decision.value
                if plan.ongoing_input_decision is not None
                else None
            ),
            "current_activity_status": current_status,
            "current_activity_preserved": plan.current_activity_preserved
            and not stopped,
            "current_activity_paused": plan.current_activity_paused,
            "current_activity_stopped": stopped,
            "requested_new_activity": plan.requested_new_activity,
            "transition_result": transition_result,
        }

    def _with_plugin_availability(self, event: AgentEvent) -> AgentEvent:
        capabilities = (
            sorted(self._plugin_manager.list_capabilities())
            if self._plugin_manager is not None
            else []
        )
        interpretation = interpret_user_request(str(event.payload.get("text") or ""))
        if interpretation.kind == UserRequestKind.EXECUTION:
            self._trace_logger.info(
                "runtime_coordinator:execution_request_unmatched",
                confidence=interpretation.confidence,
                reason=interpretation.reason,
                available_capability_count=len(capabilities),
            )
            return self._with_execution_fallback(
                event,
                contexts=[],
                reason=interpretation.reason,
                confidence=interpretation.confidence,
            )
        return replace(
            event,
            payload={
                **event.payload,
                "available_plugin_capabilities": capabilities,
                "user_request_kind": interpretation.kind.value,
                "execution_performed": False,
            },
        )

    def _with_execution_fallback(
        self,
        event: AgentEvent,
        *,
        contexts: list[dict[str, object]],
        reason: str,
        confidence: float,
    ) -> AgentEvent:
        capabilities = (
            sorted(self._plugin_manager.list_capabilities())
            if self._plugin_manager is not None
            else []
        )
        self._trace_logger.info(
            "runtime_coordinator:conversation_fallback_selected",
            reason=reason,
            confidence=confidence,
            available_capability_count=len(capabilities),
        )
        return replace(
            event,
            payload={
                **event.payload,
                "available_plugin_capabilities": capabilities,
                "plugin_contexts": contexts,
                "user_request_kind": UserRequestKind.EXECUTION.value,
                "execution_request_unmatched": True,
                "execution_performed": False,
                "execution_match_confidence": confidence,
                "execution_match_reason": reason,
                "safe_conversation_fallback": "今はそれを一緒にできないんだ。別のお話をしよう。",
                "available_alternative": "文字での通常会話",
            },
        )

    async def run_once(self) -> ActionPlanGroup | None:
        self._trace_logger.write(
            "runtime_coordinator:run_once:start",
            queue_empty=self._event_queue.empty(),
            drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
            drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
            drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
            drive_energy=self._agent_life_service.agent_state.current_drive.energy,
        )
        if self._event_queue.empty():
            if not self._autonomous_planning_enabled:
                self._trace_logger.write(
                    "runtime_coordinator:run_once:autonomous_planning_disabled"
                )
                return None
            if not self._startup_completed:
                return None
            now = monotonic()
            request_recently_sent = (
                self._last_autonomous_planning_request_at is not None
                and now - self._last_autonomous_planning_request_at
                < self._autonomous_planning_poll_seconds
            )
            if (
                request_recently_sent
                or not self._activity_planning_request_queue.empty()
                or self._activity_planner_thread.is_busy
            ):
                return None
            self._activity_planning_request_queue.put(ActivityPlanningRequest())
            self._last_autonomous_planning_request_at = now
            self._trace_logger.write(
                "runtime_coordinator:run_once:activity_planning_requested",
                request_queue_size=self._activity_planning_request_queue.qsize(),
            )
            self._trace_logger.write("runtime_coordinator:run_once:no_event")
            return None

        event = await self._event_queue.get()
        self._trace_logger.write(
            "runtime_coordinator:run_once:queue_get",
            level=(
                "DEBUG"
                if self._is_agent_state_only_event(event) or event.discardable
                else "INFO"
            ),
            event_type=event.event_type.value,
            event_id=event.event_id,
            priority=event.priority,
            discardable=event.discardable,
            replace_key=event.replace_key,
        )
        result = await self._handle_event(event)
        if event.event_type == AgentEventType.APP_STARTED:
            self._startup_completed = True
            self._trace_logger.info(
                "runtime_coordinator:startup_completed",
                source_event_id=event.event_id,
            )
        return result

    async def run(self) -> None:
        self._running = True
        self._trace_logger.info("runtime_coordinator:run:start")

        await self._run_async_initializers()
        self._start_threads()

        while self._running:
            action_plan_group = await self.run_once()
            if action_plan_group is None:
                self._trace_logger.write("runtime_coordinator:run:idle_sleep")
                await asyncio.sleep(self._idle_sleep_seconds)

    async def _run_async_initializers(self) -> None:
        if self._initializers_completed:
            return
        for initializer in self._async_initializers:
            try:
                await initializer()
            except Exception as error:
                self._trace_logger.error(
                    "runtime_coordinator:async_initializer_failed",
                    initializer=getattr(initializer, "__qualname__", type(initializer).__name__),
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
        self._initializers_completed = True

    def stop(self) -> None:
        self._trace_logger.info("runtime_coordinator:stop")
        self._running = False
        self._stop_threads()
        if self._plugin_manager is not None:
            self._plugin_manager.shutdown_plugins()
        self._ongoing_activity_coordinator.cancel(reason="runtime_stopped")

    def _start_threads(self) -> None:
        """常駐 Thread を必要に応じて起動する。"""

        if not self._autonomous_planning_enabled:
            self._trace_logger.info(
                "runtime_coordinator:threads:skipped",
                reason="autonomous_planning_disabled",
            )
            return

        if not self._activity_planner_thread.is_alive():
            self._activity_planner_thread.start()

        if not self._activity_executor_thread.is_alive():
            self._activity_executor_thread.start()

        self._trace_logger.info(
            "runtime_coordinator:threads:start",
            activity_planner_thread_alive=self._activity_planner_thread.is_alive(),
            activity_executor_thread_alive=self._activity_executor_thread.is_alive(),
        )

    def _stop_threads(self) -> None:
        """常駐 Thread に停止要求を送り、終了を待つ。"""

        if not self._autonomous_planning_enabled:
            return

        self._activity_planner_thread.stop()
        self._activity_executor_thread.stop()

        if self._activity_planner_thread.is_alive():
            self._activity_planner_thread.join(
                timeout=self._thread_join_timeout_seconds
            )

        if self._activity_executor_thread.is_alive():
            self._activity_executor_thread.join(
                timeout=self._thread_join_timeout_seconds
            )

        self._trace_logger.info(
            "runtime_coordinator:threads:stopped",
            activity_planner_thread_alive=self._activity_planner_thread.is_alive(),
            activity_executor_thread_alive=self._activity_executor_thread.is_alive(),
        )

    async def _handle_event(self, event: AgentEvent) -> ActionPlanGroup:
        for enricher in self._event_enrichers:
            event = enricher(event)
        self._agent_life_service.handle_event(event)
        if not isinstance(event.payload.get("relationship"), dict):
            relationship = self._agent_life_service.preview_relationship(event)
            if relationship is not None:
                event = replace(
                    event,
                    payload={
                        **event.payload,
                        "relationship": relationship.as_context(),
                    },
                )
        if not isinstance(event.payload.get("situation"), dict):
            situation = (
                self._agent_life_service.agent_state.current_situation.as_context()
            )
            event = replace(
                event,
                payload={
                    **event.payload,
                    "situation": situation,
                },
            )
        if not isinstance(event.payload.get("memory"), dict):
            event = replace(
                event,
                payload={
                    **event.payload,
                    "memory": self._agent_life_service.agent_state.memory.as_context(),
                },
            )
        self._trace_logger.write(
            "runtime_coordinator:handle_event:start",
            event_type=event.event_type.value,
            event_id=event.event_id,
            priority=event.priority,
            discardable=event.discardable,
            replace_key=event.replace_key,
        )
        if self._is_agent_state_only_event(event):
            self._agent_life_service.handle_event(event)
            self._trace_logger.write(
                "runtime_coordinator:handle_event:state_only",
                event_type=event.event_type.value,
                drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
                drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
                drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
                drive_energy=self._agent_life_service.agent_state.current_drive.energy,
            )
            return ActionPlanGroup()

        activity = self._activity_manager.handle_event(event)
        self._trace_logger.write(
            "runtime_coordinator:handle_event:activity_created",
            event_type=event.event_type.value,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
        )
        self._agent_life_service.handle_event(event)
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_updated",
            drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
            drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
            drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
            drive_energy=self._agent_life_service.agent_state.current_drive.energy,
        )
        prepare_autonomous_execution(activity)
        try:
            action_plan_group = await self._action_planner.plan(activity)
        except Exception as error:
            action_plan_group = action_planning_failure_group(activity, error)
            if action_plan_group.activity_turn_result is not None:
                self._activity_manager.record_turn_result(
                    action_plan_group.activity_turn_result
                )
            self._trace_logger.warning(
                "runtime_coordinator:action_planning:failed",
                activity_id=activity.activity_id,
                event_id=event.event_id,
                failure_stage="action_planning",
                error_type=type(error).__name__,
            )
            self._activity_manager.complete_processed_activity(activity.activity_id)
            self._agent_life_service.sync_from_activity_manager()
            return action_plan_group
        self._trace_logger.write(
            "runtime_coordinator:handle_event:actions_planned",
            activity_type=activity.activity_type.value,
            action_types=[
                action_plan.action_type.value
                for action_plan in action_plan_group.action_plans
            ],
        )
        current_activity = self._activity_manager.get_activity(activity.activity_id)
        if (
            current_activity is not None
            and current_activity.status != ActivityStatus.ACTIVE
        ):
            self._trace_logger.info(
                "runtime_coordinator:handle_event:actions_canceled",
                event_id=event.event_id,
                activity_id=current_activity.activity_id,
                activity_type=current_activity.activity_type.value,
                activity_status=current_activity.status.value,
                action_ids=[
                    action.action_id for action in action_plan_group.action_plans
                ],
                action_types=[
                    action.action_type.value
                    for action in action_plan_group.action_plans
                ],
                source_activity_ids=[
                    action.source_activity_id
                    for action in action_plan_group.action_plans
                ],
                reason="activity_suspended_before_action_execution",
            )
            canceled_group = canceled_output_group(
                action_plan_group, reason="activity_suspended_before_action_execution"
            )
            if canceled_group.activity_turn_result is not None:
                self._activity_manager.record_turn_result(
                    canceled_group.activity_turn_result
                )
            self._agent_life_service.sync_from_activity_manager()
            return canceled_group
        self._trace_logger.write(
            "runtime_coordinator:handle_event:actions_execute_start"
        )
        output_result = await self._action_scheduler.execute(action_plan_group)
        if (
            output_result is not None
            and action_plan_group.activity_turn_result is not None
        ):
            self._activity_manager.record_output_result(
                action_plan_group.activity_turn_result, output_result
            )
        autonomous_output_saved = False
        if (
            activity.activity_type == ActivityType.AUTONOMOUS_TALK
            and output_result is not None
        ):
            speech_text = completed_speech_text(action_plan_group, output_result)
            if speech_text is not None:
                self._agent_life_service.record_autonomous_output(
                    activity_id=activity.activity_id,
                    text=speech_text,
                    context=activity.context,
                )
                autonomous_output_saved = True
                self._trace_logger.info(
                    "runtime_coordinator:autonomous_memory_saved",
                    activity_id=activity.activity_id,
                    output_unit_id=output_result.output_unit_id,
                    reason="speak_completed",
                )
            else:
                self._trace_logger.info(
                    "runtime_coordinator:autonomous_memory_not_saved",
                    activity_id=activity.activity_id,
                    output_unit_id=output_result.output_unit_id,
                    reason="speak_not_completed",
                )
        self._trace_logger.write(
            "runtime_coordinator:handle_event:actions_execute_finished"
        )
        completed_activity = self._activity_manager.complete_processed_activity(
            activity.activity_id,
            result=build_activity_result(action_plan_group, output_result),
        )
        if (
            activity.activity_type == ActivityType.AUTONOMOUS_TALK
            and autonomous_output_saved
        ):
            self._agent_life_service.complete_autonomous_topic(
                activity_id=activity.activity_id
            )
        self._trace_logger.write(
            "runtime_coordinator:handle_event:foreground_activity_completed",
            completed=completed_activity is not None,
            activity_id=(
                completed_activity.activity_id
                if completed_activity is not None
                else None
            ),
            activity_type=(
                completed_activity.activity_type.value
                if completed_activity is not None
                else None
            ),
            activity_status=(
                completed_activity.status.value
                if completed_activity is not None
                else None
            ),
        )
        self._agent_life_service.sync_from_activity_manager()
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_synced_after_activity_complete",
            active_activity_exists=self._agent_life_service.agent_state.active_activity
            is not None,
            pending_activity_count=len(
                self._agent_life_service.agent_state.pending_activities
            ),
            suspended_activity_count=len(
                self._agent_life_service.agent_state.suspended_activities
            ),
        )
        return action_plan_group

    def _is_agent_state_only_event(self, event: AgentEvent) -> bool:
        return event.event_type in (
            AgentEventType.SPEECH_STARTED,
            AgentEventType.SPEECH_FINISHED,
        )
