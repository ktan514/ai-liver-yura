from __future__ import annotations

from app.domain.actions import ActionPlan, ActionType


class ExecuteActionUsecase:
    """ActionPlan を実行する最小 UseCase。

    初期段階では外部 TTS / OBS / Live2D へ接続せず、標準出力に出す。
    後で Channel Executor へ分割する。
    """

    async def execute(self, action_plan: ActionPlan) -> None:
        if action_plan.action_type in (ActionType.SPEAK, ActionType.ASK, ActionType.REACT):
            print(f"[{action_plan.action_type.value}] {action_plan.text}")
            return

        if action_plan.action_type == ActionType.OBSERVE:
            print("[observe]")
            return

        if action_plan.action_type == ActionType.UPDATE_SUBTITLE:
            print(f"[subtitle] {action_plan.text}")
            return

        if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
            print(f"[expression] {action_plan.text}")
            return

        print(f"[{action_plan.action_type.value}] not implemented")
