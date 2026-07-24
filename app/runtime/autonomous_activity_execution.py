from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.utils.llm_trace import build_llm_trace_context


def prepare_autonomous_execution(activity: Activity) -> ActivityExecutionResult | None:
    """自律Activityの内容確定を、出力成功とは独立した実行事実として記録する。"""

    if activity.activity_type != ActivityType.AUTONOMOUS_TALK:
        return None
    existing = activity.context.get("activity_execution_result")
    if isinstance(existing, ActivityExecutionResult):
        return existing
    plan_value = activity.context.get("behavior_plan")
    plan = plan_value if isinstance(plan_value, dict) else {}
    event_payload_value = activity.context.get("event_payload")
    event_payload = event_payload_value if isinstance(event_payload_value, dict) else {}
    topic = str(
        plan.get("topic") or event_payload.get("selected_topic") or activity.goal
    )
    planning_reason = str(
        plan.get("planning_reason") or event_payload.get("reason") or "internal_drive"
    )
    trace = build_llm_trace_context(activity).trace_context
    result = ActivityExecutionResult(
        activity_type=ActivityType.AUTONOMOUS_TALK.value,
        operation=str(plan.get("operation") or "start"),
        status=ActivityExecutionStatus.SUCCEEDED,
        payload={
            "summary": f"{topic}について話す目的と内容を確定した",
            "selected_topic": topic,
            "goal": activity.goal,
            "planning_reason": planning_reason,
            "source_state_snapshot": activity.context.get(
                "autonomous_situation_context", {}
            ),
        },
        constraints=(
            dict(plan.get("constraints", {}))
            if isinstance(plan.get("constraints"), dict)
            else {}
        ),
        source_event_id=activity.source_event_id,
        activity_turn_id=trace.activity_turn_id,
        trace_id=trace.trace_id,
        parent_trace_id=trace.parent_trace_id,
        behavior_plan_id=trace.behavior_plan_id,
    )
    activity.context["activity_execution_result"] = result
    if isinstance(event_payload_value, dict):
        event_payload_value["activity_execution_result"] = result
    return result
