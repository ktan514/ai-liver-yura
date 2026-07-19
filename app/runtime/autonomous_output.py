from __future__ import annotations

from app.domain.actions import ActionPlanGroup, ActionType
from app.domain.activity_turn_result import ActionExecutionStatus, ActivityOutputResult


def completed_speech_text(
    group: ActionPlanGroup,
    output_result: ActivityOutputResult,
) -> str | None:
    """Output実績から、実際に完了したSPEAK本文だけを返す。"""

    completed_ids = {
        result.action_id
        for result in output_result.action_results
        if result.action_type == ActionType.SPEAK.value
        and result.status == ActionExecutionStatus.COMPLETED
    }
    return next(
        (
            action.text
            for action in group.action_plans
            if action.action_type == ActionType.SPEAK
            and action.action_id in completed_ids
        ),
        None,
    )
