from __future__ import annotations

from app.domain.actions import ActionPlanGroup, ActionType
from app.domain.activities import ActivityResult
from app.domain.activity_turn_result import ActivityOutputResult


def build_activity_result(
    action_plan_group: ActionPlanGroup,
    output_result: ActivityOutputResult | None = None,
) -> ActivityResult:
    """Action群の実行結果を、発話に限定しないActivityResultへ変換する。"""

    result_by_id = (
        {result.action_id: result for result in output_result.action_results}
        if output_result is not None
        else {}
    )
    actions = []
    for action in action_plan_group.action_plans:
        execution = result_by_id.get(action.action_id)
        actions.append(
            {
                "action_id": action.action_id,
                "action_type": action.action_type.value,
                "text": action.text,
                "status": execution.status.value if execution is not None else None,
                "error": execution.error if execution is not None else None,
                "started_at": (
                    execution.started_at.isoformat() if execution is not None else None
                ),
                "finished_at": (
                    execution.finished_at.isoformat()
                    if execution is not None and execution.finished_at is not None
                    else None
                ),
            }
        )
    speech_text = next(
        (
            action.text
            for action in action_plan_group.action_plans
            if action.action_type == ActionType.SPEAK
        ),
        None,
    )
    if speech_text is not None:
        result_type = "speech_output"
        summary = speech_text
    elif action_plan_group.action_plans:
        result_type = "action_output"
        summary = ", ".join(
            action.action_type.value for action in action_plan_group.action_plans
        )
    else:
        result_type = "no_action"
        summary = "実行Actionなし"

    return ActivityResult(
        result_type=result_type,
        summary=summary,
        data={
            "output_unit_id": action_plan_group.group_id,
            "activity_turn_id": (
                output_result.activity_turn_id if output_result is not None else None
            ),
            "output_status": (
                output_result.status.value if output_result is not None else None
            ),
            "actions": actions,
        },
        succeeded=output_result is None or output_result.status.value == "completed",
        trace_id=output_result.trace_id if output_result is not None else None,
        parent_trace_id=(
            output_result.parent_trace_id if output_result is not None else None
        ),
        activity_turn_id=(
            output_result.activity_turn_id if output_result is not None else None
        ),
    )
