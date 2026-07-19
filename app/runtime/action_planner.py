from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from app.core.contracts.activity_policy import ActivityPolicy
from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.activity_turn_result import (
    ActivityOutputResult,
    ActivityOutputStatus,
    ActivityTurnResult,
    CharacterGenerationResult,
    CharacterGenerationStatus,
)
from app.domain.character_response import (
    ActivityExecutionResult,
    CharacterResponse,
    ReactionPlan,
    ReactionSegment,
    VoiceIntent,
)
from app.domain.trace_context import trace_context_from
from app.ports.response_generator import ResponseGenerator
from app.runtime.character_response_pipeline import CharacterResponsePipeline
from app.shared.contracts.plugins.runtime import MemoryPolicy
from app.utils.llm_trace import build_llm_trace_context
from app.utils.trace import TraceLogger


class ActionPlanner:
    """Activity から最小 ActionPlanGroup を作る。"""

    def __init__(
        self,
        response_generator: ResponseGenerator,
        character_response_pipeline: CharacterResponsePipeline | None = None,
        activity_is_active: Callable[[str], bool] | None = None,
    ) -> None:
        self._response_generator = response_generator
        self._character_response_pipeline = character_response_pipeline
        self._activity_is_active = activity_is_active
        self._trace_logger = TraceLogger()
        self._lifecycle_gate: ActivityPolicy | None = None

    def set_activity_policy(self, gate: ActivityPolicy) -> None:
        self._lifecycle_gate = gate

    async def plan(self, activity: Activity) -> ActionPlanGroup:
        self._require_lifecycle(activity, "start_llm_generation")
        self._trace_logger.write(
            "action_planner:plan:start",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
            activity_priority=activity.priority,
        )
        if activity.activity_type in {
            ActivityType.CONVERSATION_WITH_USER,
            ActivityType.DIRECTED_TALK,
            ActivityType.PLUGIN_ACTIVITY,
            ActivityType.STARTUP_REACTION,
            ActivityType.STREAM_OPENING_GREETING,
            ActivityType.STREAM_MAIN_SEGMENT,
            ActivityType.STREAM_COMMENT_RESPONSE,
            ActivityType.STREAM_CLOSING_GREETING,
        }:
            prepared_response = activity.context.get("prepared_response_text")
            character_response = None
            character_generation_result = None
            safe_rejection_response = self._safe_rejection_response(activity)
            if self._character_response_pipeline is not None:
                (
                    character_response,
                    character_generation_result,
                ) = await self._character_response_pipeline.generate_with_result(
                    activity
                )
                response_text = character_response.speech
                response_source = "validated_character_response"
            elif safe_rejection_response is not None:
                response_text = safe_rejection_response
                response_source = "safety_replacement"
                self._trace_logger.warning(
                    "action_planner:unsafe_execution_claim_prevented",
                    activity_id=activity.activity_id,
                    replacement_used=True,
                )
            elif isinstance(prepared_response, str):
                response_text = prepared_response
                response_source = "prepared_response"
            else:
                response_text, fallback_used = (
                    await self._generate_response_with_safe_fallback(activity)
                )
                response_source = (
                    "conversation_fallback" if fallback_used else "llm_generation"
                )
            if activity.activity_type == ActivityType.STREAM_COMMENT_RESPONSE:
                event_payload = activity.context.get("event_payload")
                style = (
                    event_payload.get("response_style")
                    if isinstance(event_payload, dict)
                    else None
                )
                limit = style.get("max_characters") if isinstance(style, dict) else 140
                max_characters = limit if isinstance(limit, int) and limit > 0 else 140
                response_text = response_text[:max_characters].strip()
                if character_generation_result is not None:
                    character_generation_result = replace(
                        character_generation_result, adopted_text=response_text
                    )
            if character_generation_result is None:
                character_generation_result = self._generation_result(
                    activity,
                    response_text,
                    fallback_used=response_source
                    in {"safety_replacement", "conversation_fallback"},
                )
            self._trace_logger.info(
                "action_planner:character_result",
                activity_id=activity.activity_id,
                activity_turn_id=character_generation_result.activity_turn_id,
                character_generation_result_id=character_generation_result.result_id,
                character_status=character_generation_result.status.value,
            )
            activity.context["character_generation_result"] = (
                character_generation_result
            )
            self._trace_logger.debug(
                "action_planner:response_adopted",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                response_source=response_source,
                response_length=len(response_text),
            )
            trace_context = build_llm_trace_context(activity)
            self._trace_logger.llm_response(
                purpose=trace_context.purpose,
                provider="action_planner",
                model=response_source,
                activity_id=activity.activity_id,
                raw_response=None,
                adopted_text=response_text,
                fallback_used=response_source
                in {"safety_replacement", "conversation_fallback"},
                stage="final_output",
                llm_role=trace_context.llm_role,
                model_key=trace_context.model_key or response_source,
                service="action_planner",
                request_id=trace_context.request_id,
                attempt=trace_context.attempt,
                **trace_context.trace_context.derive(
                    character_generation_result_id=character_generation_result.result_id
                ).as_log_fields(),
            )
            self._trace_logger.info(
                "action_planner:response_generated",
                source_activity_type=activity.activity_type.value,
                activity_id=activity.activity_id,
                plugin_id=activity.context.get("plugin_id"),
                session_id=activity.context.get("plugin_session_id"),
                response_length=len(response_text),
            )
            output_unit_id = str(uuid4())
            self._require_lifecycle(activity, "create_action_plan")
            self._trace_logger.write(
                "action_planner:plan:response_generated",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                response_length=len(response_text),
            )
            action_plans = self._reaction_action_plans(
                activity,
                character_response,
                fallback_speech=response_text,
                output_unit_id=output_unit_id,
                base_metadata=self._lifecycle_metadata(activity),
                skip_topic_memory=self._should_skip_topic_memory(activity),
            )
            action_plan_group = ActionPlanGroup(
                action_plans=action_plans,
                source_activity_id=activity.activity_id,
                output_priority=self._output_priority(activity.activity_type),
                group_id=output_unit_id,
                activity_turn_result=self._turn_result(
                    activity, character_generation_result, output_unit_id=output_unit_id
                ),
            )
            self._trace_logger.write(
                "action_planner:plan:actions_created",
                **build_llm_trace_context(activity)
                .trace_context.derive(
                    character_generation_result_id=character_generation_result.result_id,
                    output_unit_id=output_unit_id,
                )
                .as_log_fields(),
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                action_types=[
                    action_plan.action_type.value
                    for action_plan in action_plan_group.action_plans
                ],
                action_count=len(action_plan_group.action_plans),
                required_resources=sorted(
                    {
                        resource.value
                        for action in action_plan_group.action_plans
                        for resource in action.required_resources
                    }
                ),
            )
            return action_plan_group

        if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            if not self._is_activity_active(activity.activity_id):
                return self._checkpoint_group(activity, None)
            if self._character_response_pipeline is None:
                raise RuntimeError(
                    "AUTONOMOUS_TALKにはCharacterResponsePipelineが必要です。"
                )
            (
                character_response,
                character_generation_result,
            ) = await self._character_response_pipeline.generate_with_result(activity)
            response_text = character_response.speech
            self._trace_logger.info(
                "action_planner:character_result",
                activity_id=activity.activity_id,
                activity_turn_id=character_generation_result.activity_turn_id,
                character_generation_result_id=character_generation_result.result_id,
                character_status=character_generation_result.status.value,
            )
            activity.context["character_generation_result"] = (
                character_generation_result
            )
            if not self._is_activity_active(activity.activity_id):
                self._trace_logger.info(
                    "action_planner:autonomous_canceled_after_character",
                    activity_id=activity.activity_id,
                    activity_turn_id=character_generation_result.activity_turn_id,
                    character_generation_result_id=character_generation_result.result_id,
                )
                return self._checkpoint_group(activity, character_generation_result)
            output_unit_id = str(uuid4())
            self._trace_logger.write(
                "action_planner:plan:response_generated",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                response_length=len(response_text),
            )
            action_plans = self._reaction_action_plans(
                activity,
                character_response,
                fallback_speech=response_text,
                output_unit_id=output_unit_id,
                base_metadata={},
                skip_topic_memory=False,
            )
            action_plan_group = ActionPlanGroup(
                action_plans=action_plans,
                source_activity_id=activity.activity_id,
                output_priority=self._output_priority(activity.activity_type),
                group_id=output_unit_id,
                activity_turn_result=self._turn_result(
                    activity, character_generation_result, output_unit_id=output_unit_id
                ),
            )
            self._trace_logger.write(
                "action_planner:plan:actions_created",
                **build_llm_trace_context(activity)
                .trace_context.derive(
                    character_generation_result_id=character_generation_result.result_id,
                    output_unit_id=output_unit_id,
                )
                .as_log_fields(),
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                action_types=[
                    action_plan.action_type.value
                    for action_plan in action_plan_group.action_plans
                ],
                action_count=len(action_plan_group.action_plans),
                required_resources=sorted(
                    {
                        resource.value
                        for action in action_plan_group.action_plans
                        for resource in action.required_resources
                    }
                ),
            )
            return action_plan_group

        output_unit_id = str(uuid4())
        observe_plan = ActionPlan(
            action_type=ActionType.OBSERVE,
            text="",
            required_resources={ActionResource.EYES},
            source_activity_id=activity.activity_id,
            output_unit_id=output_unit_id,
        )
        action_plan_group = ActionPlanGroup(
            action_plans=[observe_plan],
            source_activity_id=activity.activity_id,
            group_id=output_unit_id,
            activity_turn_result=self._turn_result(
                activity, None, output_unit_id=output_unit_id
            ),
        )
        self._trace_logger.write(
            "action_planner:plan:actions_created",
            **build_llm_trace_context(activity)
            .trace_context.derive(output_unit_id=output_unit_id)
            .as_log_fields(),
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            action_types=[
                action_plan.action_type.value
                for action_plan in action_plan_group.action_plans
            ],
            action_count=len(action_plan_group.action_plans),
            required_resources=[ActionResource.EYES.value],
        )
        return action_plan_group

    def _require_lifecycle(self, activity: Activity, operation: str) -> None:
        if self._lifecycle_gate is None:
            return
        payload = activity.context.get("event_payload")
        session_id = payload.get("session_id") if isinstance(payload, dict) else None
        if not isinstance(session_id, str):
            return
        decision = self._lifecycle_gate.evaluate_policy(
            operation,
            session_id,
            activity_type=activity.activity_type.value,
        )
        if not decision.allowed:
            raise RuntimeError(
                decision.reason_code or "lifecycle.operation_not_allowed"
            )

    @staticmethod
    def _lifecycle_metadata(
        activity: Activity, *, skip_topic_memory: bool = False
    ) -> dict[str, object]:
        payload = activity.context.get("event_payload")
        session_id = payload.get("session_id") if isinstance(payload, dict) else None
        metadata: dict[str, object] = {
            "lifecycle_session_id": session_id,
            "lifecycle_activity_type": activity.activity_type.value,
        }
        if skip_topic_memory:
            metadata["skip_topic_memory"] = True
        return metadata

    @staticmethod
    def _reaction_action_plans(
        activity: Activity,
        response: CharacterResponse | None,
        *,
        fallback_speech: str,
        output_unit_id: str,
        base_metadata: dict[str, object],
        skip_topic_memory: bool,
    ) -> list[ActionPlan]:
        plan = (
            response.effective_reaction_plan()
            if response is not None
            else ReactionPlan(
                (ReactionSegment(fallback_speech, voice_intent=VoiceIntent()),)
            )
        )
        actions: list[ActionPlan] = []
        for index, segment in enumerate(plan.segments):
            segment_metadata = {
                **base_metadata,
                "reaction_segment_index": index,
                "reaction_segment_count": len(plan.segments),
            }
            speak_metadata = {
                **segment_metadata,
                "voice_intent": segment.voice_intent,
                "pause_after_seconds": segment.pause_after_seconds,
            }
            if skip_topic_memory:
                speak_metadata["skip_topic_memory"] = True
            actions.extend(
                (
                    ActionPlan(
                        action_type=ActionType.SPEAK,
                        text=segment.speech,
                        required_resources={ActionResource.MOUTH},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata=speak_metadata,
                    ),
                    ActionPlan(
                        action_type=ActionType.UPDATE_SUBTITLE,
                        text=segment.speech,
                        required_resources={ActionResource.SUBTITLE},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata=dict(segment_metadata),
                    ),
                    ActionPlan(
                        action_type=ActionType.CHANGE_EXPRESSION,
                        text=segment.expression,
                        required_resources={ActionResource.FACE},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata=dict(segment_metadata),
                    ),
                )
            )
            if segment.gesture:
                actions.append(
                    ActionPlan(
                        action_type=ActionType.MOVE,
                        text=segment.gesture,
                        required_resources={ActionResource.BODY},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata=dict(segment_metadata),
                    )
                )
        return actions

    async def _generate_response_with_safe_fallback(
        self, activity: Activity
    ) -> tuple[str, bool]:
        try:
            return await self._response_generator.generate_response(activity), False
        except Exception as error:
            payload = activity.context.get("event_payload")
            fallback = (
                payload.get("safe_conversation_fallback")
                if isinstance(payload, dict)
                else None
            )
            if not isinstance(fallback, str) or not fallback.strip():
                raise
            self._trace_logger.warning(
                "action_planner:conversation_generation_fallback",
                activity_id=activity.activity_id,
                error_type=type(error).__name__,
            )
            return fallback, True

    @staticmethod
    def _safe_rejection_response(activity: Activity) -> str | None:
        payload = activity.context.get("event_payload")
        if not isinstance(payload, dict) or not payload.get(
            "execution_request_unmatched"
        ):
            return None
        fallback = payload.get("safe_conversation_fallback")
        return fallback if isinstance(fallback, str) and fallback.strip() else None

    @staticmethod
    def _should_skip_topic_memory(activity: Activity) -> bool:
        plugin_policy = activity.context.get("plugin_memory_policy")
        if isinstance(plugin_policy, MemoryPolicy):
            return plugin_policy.skip_topic_memory
        return activity.activity_type == ActivityType.PLUGIN_ACTIVITY

    @staticmethod
    def _output_priority(activity_type: ActivityType) -> int:
        """音声出力ではユーザー応答を優先し、同一優先度内は到着順を維持する。"""

        if activity_type in {
            ActivityType.CONVERSATION_WITH_USER,
            ActivityType.DIRECTED_TALK,
            ActivityType.PLUGIN_ACTIVITY,
        }:
            return 100
        if activity_type == ActivityType.AUTONOMOUS_TALK:
            return 10
        return 50

    def _is_activity_active(self, activity_id: str) -> bool:
        return self._activity_is_active is None or self._activity_is_active(activity_id)

    def _checkpoint_group(
        self,
        activity: Activity,
        character_result: CharacterGenerationResult | None,
    ) -> ActionPlanGroup:
        output_unit_id = str(uuid4())
        return ActionPlanGroup(
            source_activity_id=activity.activity_id,
            output_priority=self._output_priority(activity.activity_type),
            group_id=output_unit_id,
            activity_turn_result=self._turn_result(
                activity,
                character_result,
                output_unit_id=output_unit_id,
            ),
        )

    @staticmethod
    def _correlation_ids(activity: Activity) -> tuple[str, str | None]:
        turn = activity.context.get("activity_turn")
        turn_id = getattr(turn, "turn_id", None)
        ongoing = activity.context.get("ongoing_activity")
        ongoing_id = getattr(ongoing, "ongoing_activity_id", None)
        trace = trace_context_from(activity.context)
        return (
            str(
                turn_id
                or activity.context.get("activity_turn_id")
                or (trace.activity_turn_id if trace is not None else None)
                or activity.activity_id
            ),
            (
                str(
                    ongoing_id
                    or (trace.ongoing_activity_id if trace is not None else None)
                )
                if ongoing_id is not None
                or (trace is not None and trace.ongoing_activity_id)
                else None
            ),
        )

    @classmethod
    def _generation_result(
        cls, activity: Activity, text: str, *, fallback_used: bool
    ) -> CharacterGenerationResult:
        turn_id, ongoing_id = cls._correlation_ids(activity)
        now = datetime.now(timezone.utc)
        trace = build_llm_trace_context(activity).trace_context
        return CharacterGenerationResult(
            status=(
                CharacterGenerationStatus.FALLBACK_USED
                if fallback_used
                else CharacterGenerationStatus.VALIDATED
            ),
            activity_turn_id=turn_id,
            ongoing_activity_id=ongoing_id,
            source_event_id=activity.source_event_id,
            adopted_text=text,
            attempts=1,
            started_at=now,
            finished_at=now,
            trace_id=trace.trace_id,
            parent_trace_id=trace.parent_trace_id,
            behavior_plan_id=trace.behavior_plan_id,
        )

    @classmethod
    def _turn_result(
        cls,
        activity: Activity,
        character_result: CharacterGenerationResult | None,
        *,
        output_unit_id: str | None = None,
    ) -> ActivityTurnResult:
        turn_id, ongoing_id = cls._correlation_ids(activity)
        execution_value = activity.context.get("activity_execution_result")
        payload = activity.context.get("event_payload")
        if not isinstance(execution_value, ActivityExecutionResult) and isinstance(
            payload, dict
        ):
            execution_value = payload.get("activity_execution_result")
        execution_result = (
            execution_value
            if isinstance(execution_value, ActivityExecutionResult)
            else None
        )
        trace = build_llm_trace_context(activity).trace_context
        if execution_result is not None and execution_result.trace_id is None:
            execution_result = replace(
                execution_result,
                source_event_id=execution_result.source_event_id
                or activity.source_event_id,
                activity_turn_id=execution_result.activity_turn_id or turn_id,
                ongoing_activity_id=execution_result.ongoing_activity_id or ongoing_id,
                trace_id=trace.trace_id,
                parent_trace_id=trace.parent_trace_id,
                behavior_plan_id=trace.behavior_plan_id,
            )
            activity.context["activity_execution_result"] = execution_result
            if isinstance(payload, dict) and "activity_execution_result" in payload:
                payload["activity_execution_result"] = execution_result
        confirmation_value = (
            payload.get("pending_confirmation") if isinstance(payload, dict) else None
        )
        confirmation = (
            confirmation_value if isinstance(confirmation_value, dict) else {}
        )
        aggregate = ActivityTurnResult(
            activity_turn_id=turn_id,
            activity_type=(
                execution_result.activity_type
                if execution_result is not None
                else activity.activity_type.value
            ),
            source_event_id=activity.source_event_id,
            ongoing_activity_id=ongoing_id,
            operation=(
                execution_result.operation if execution_result is not None else None
            ),
            confirmation_id=cls._optional_context_value(
                confirmation, "confirmation_id"
            ),
            confirmation_source_event_id=cls._optional_context_value(
                confirmation, "source_event_id"
            ),
            resolution_event_id=cls._optional_context_value(
                confirmation, "resolution_event_id"
            ),
            candidate_activity_type=cls._optional_context_value(
                confirmation, "candidate_activity_type"
            ),
            candidate_operation=cls._optional_context_value(
                confirmation, "candidate_operation"
            ),
            confirmation_resolution=cls._optional_context_value(
                confirmation, "resolution"
            ),
            final_behavior_plan_id=cls._optional_context_value(
                confirmation, "final_behavior_plan_id"
            ),
            execution_result=execution_result,
            character_result=character_result,
            trace_id=trace.trace_id,
            parent_trace_id=trace.parent_trace_id,
            behavior_plan_id=trace.behavior_plan_id,
        )
        if output_unit_id is None:
            return aggregate
        return aggregate.with_output(
            ActivityOutputResult(
                status=ActivityOutputStatus.PLANNED,
                output_unit_id=output_unit_id,
                activity_turn_id=turn_id,
                ongoing_activity_id=ongoing_id,
                source_event_id=activity.source_event_id,
                trace_id=trace.trace_id,
                parent_trace_id=trace.parent_trace_id,
                behavior_plan_id=trace.behavior_plan_id,
            )
        )

    @staticmethod
    def _optional_context_value(context: dict[object, object], key: str) -> str | None:
        value = context.get(key)
        return str(value) if value is not None else None
