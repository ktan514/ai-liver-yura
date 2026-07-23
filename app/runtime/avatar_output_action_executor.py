from __future__ import annotations

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult
from app.ports.avatar_output import AvatarOutputPort
from app.utils.trace import TraceLogger


class AvatarOutputActionExecutor:
    """既存ActionExecutorを保ったままアバター出力Portを追加する。"""

    def __init__(self, delegate: object, avatar_output: AvatarOutputPort) -> None:
        self._delegate = delegate
        self._avatar_output = avatar_output
        self._trace_logger = TraceLogger()

    async def prepare(self, action_plan: ActionPlan) -> ActionPlan:
        prepare = getattr(self._delegate, "prepare", None)
        if callable(prepare):
            return await prepare(action_plan)
        return action_plan

    async def execute(
        self,
        action_plan: ActionPlan,
    ) -> ActionExecutionResult | None:
        try:
            if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
                await self._avatar_output.set_expression(action_plan.text)
            elif action_plan.action_type == ActionType.MOVE:
                await self._avatar_output.play_gesture(action_plan.text)
        except Exception as error:
            self._trace_logger.warning(
                "avatar_output_action_executor:output_failed",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                error_type=type(error).__name__,
            )
        execute = getattr(self._delegate, "execute", None)
        if not callable(execute):
            raise RuntimeError("delegate action executorにexecuteがありません。")
        return await execute(action_plan)


def attach_avatar_output(coordinator: object, avatar_output: AvatarOutputPort) -> None:
    """RuntimeCoordinatorのActionSchedulerへアバター出力を後付けする。"""

    scheduler = getattr(coordinator, "_action_scheduler", None)
    executor = getattr(scheduler, "_action_executor", None)
    if scheduler is None or executor is None:
        raise RuntimeError("ActionSchedulerへアバター出力を接続できません。")
    scheduler._action_executor = AvatarOutputActionExecutor(executor, avatar_output)
