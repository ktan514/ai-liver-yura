from __future__ import annotations

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.domain.activities import Activity, ActivityType
from app.runtime.response_generator import ResponseGenerator


class ActionPlanner:
    """Activity から最小 ActionPlanGroup を作る。"""

    def __init__(self, response_generator: ResponseGenerator) -> None:
        self._response_generator = response_generator

    async def plan(self, activity: Activity) -> ActionPlanGroup:
        if activity.activity_type == ActivityType.CONVERSATION_WITH_USER:
            response_text = await self._response_generator.generate_response(activity)
            speak_plan = ActionPlan(
                action_type=ActionType.SPEAK,
                text=response_text,
                required_resources={ActionResource.MOUTH},
                source_activity_id=activity.activity_id,
            )
            subtitle_plan = ActionPlan(
                action_type=ActionType.UPDATE_SUBTITLE,
                text=response_text,
                required_resources={ActionResource.SUBTITLE},
                source_activity_id=activity.activity_id,
            )
            expression_plan = ActionPlan(
                action_type=ActionType.CHANGE_EXPRESSION,
                text="smile",
                required_resources={ActionResource.FACE},
                source_activity_id=activity.activity_id,
            )
            return ActionPlanGroup(
                action_plans=[speak_plan, subtitle_plan, expression_plan],
                source_activity_id=activity.activity_id,
            )

        if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
            response_text = await self._response_generator.generate_response(activity)
            speak_plan = ActionPlan(
                action_type=ActionType.SPEAK,
                text=response_text,
                required_resources={ActionResource.MOUTH},
                source_activity_id=activity.activity_id,
            )
            subtitle_plan = ActionPlan(
                action_type=ActionType.UPDATE_SUBTITLE,
                text=response_text,
                required_resources={ActionResource.SUBTITLE},
                source_activity_id=activity.activity_id,
            )
            return ActionPlanGroup(
                action_plans=[speak_plan, subtitle_plan],
                source_activity_id=activity.activity_id,
            )

        observe_plan = ActionPlan(
            action_type=ActionType.OBSERVE,
            text="",
            required_resources={ActionResource.EYES},
            source_activity_id=activity.activity_id,
        )
        return ActionPlanGroup(
            action_plans=[observe_plan],
            source_activity_id=activity.activity_id,
        )
