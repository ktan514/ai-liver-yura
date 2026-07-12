from __future__ import annotations

from uuid import uuid4

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.domain.activities import Activity, ActivityType
from app.ports.response_generator import ResponseGenerator
from app.utils.trace import TraceLogger


class ActionPlanner:
    """Activity から最小 ActionPlanGroup を作る。"""

    def __init__(self, response_generator: ResponseGenerator) -> None:
        self._response_generator = response_generator
        self._trace_logger = TraceLogger()

    async def plan(self, activity: Activity) -> ActionPlanGroup:
        self._trace_logger.write(
            "action_planner:plan:start",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
            activity_priority=activity.priority,
        )
        if activity.activity_type in {
            ActivityType.CONVERSATION_WITH_USER,
            ActivityType.STARTUP_REACTION,
            ActivityType.STREAM_OPENING_GREETING,
            ActivityType.STREAM_CLOSING_GREETING,
        }:
            response_text = await self._response_generator.generate_response(activity)
            output_unit_id = str(uuid4())
            self._trace_logger.write(
                "action_planner:plan:response_generated",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                response_length=len(response_text),
            )
            speak_plan = ActionPlan(
                action_type=ActionType.SPEAK,
                text=response_text,
                required_resources={ActionResource.MOUTH},
                source_activity_id=activity.activity_id,
                output_unit_id=output_unit_id,
            )
            subtitle_plan = ActionPlan(
                action_type=ActionType.UPDATE_SUBTITLE,
                text=response_text,
                required_resources={ActionResource.SUBTITLE},
                source_activity_id=activity.activity_id,
                output_unit_id=output_unit_id,
            )
            expression_text = "smile"
            if activity.activity_type == ActivityType.STREAM_CLOSING_GREETING:
                expression_text = "soft_smile"

            expression_plan = ActionPlan(
                action_type=ActionType.CHANGE_EXPRESSION,
                text=expression_text,
                required_resources={ActionResource.FACE},
                source_activity_id=activity.activity_id,
                output_unit_id=output_unit_id,
            )
            action_plan_group = ActionPlanGroup(
                action_plans=[speak_plan, subtitle_plan, expression_plan],
                source_activity_id=activity.activity_id,
                output_priority=self._output_priority(activity.activity_type),
                group_id=output_unit_id,
            )
            self._trace_logger.write(
                "action_planner:plan:actions_created",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                action_types=[
                    action_plan.action_type.value for action_plan in action_plan_group.action_plans
                ],
                action_count=len(action_plan_group.action_plans),
                output_unit_id=output_unit_id,
            )
            return action_plan_group

        if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            response_text = await self._response_generator.generate_response(activity)
            output_unit_id = str(uuid4())
            self._trace_logger.write(
                "action_planner:plan:response_generated",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                response_length=len(response_text),
            )
            speak_plan = ActionPlan(
                action_type=ActionType.SPEAK,
                text=response_text,
                required_resources={ActionResource.MOUTH},
                source_activity_id=activity.activity_id,
                output_unit_id=output_unit_id,
            )
            subtitle_plan = ActionPlan(
                action_type=ActionType.UPDATE_SUBTITLE,
                text=response_text,
                required_resources={ActionResource.SUBTITLE},
                source_activity_id=activity.activity_id,
                output_unit_id=output_unit_id,
            )
            action_plan_group = ActionPlanGroup(
                action_plans=[speak_plan, subtitle_plan],
                source_activity_id=activity.activity_id,
                output_priority=self._output_priority(activity.activity_type),
                group_id=output_unit_id,
            )
            self._trace_logger.write(
                "action_planner:plan:actions_created",
                activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                action_types=[
                    action_plan.action_type.value for action_plan in action_plan_group.action_plans
                ],
                action_count=len(action_plan_group.action_plans),
                output_unit_id=output_unit_id,
            )
            return action_plan_group

        observe_plan = ActionPlan(
            action_type=ActionType.OBSERVE,
            text="",
            required_resources={ActionResource.EYES},
            source_activity_id=activity.activity_id,
        )
        action_plan_group = ActionPlanGroup(
            action_plans=[observe_plan],
            source_activity_id=activity.activity_id,
        )
        self._trace_logger.write(
            "action_planner:plan:actions_created",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            action_types=[
                action_plan.action_type.value for action_plan in action_plan_group.action_plans
            ],
            action_count=len(action_plan_group.action_plans),
        )
        return action_plan_group

    @staticmethod
    def _output_priority(activity_type: ActivityType) -> int:
        """音声出力ではユーザー応答を優先し、同一優先度内は到着順を維持する。"""

        if activity_type == ActivityType.CONVERSATION_WITH_USER:
            return 100
        if activity_type == ActivityType.AUTONOMOUS_TALK:
            return 10
        return 50
