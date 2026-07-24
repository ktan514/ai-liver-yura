from __future__ import annotations

from typing import Protocol

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult
from app.ports.avatar_output import AvatarOutputPort
from app.utils.trace import TraceLogger


class ActionExecutorPort(Protocol):
    async def prepare(self, action_plan: ActionPlan) -> ActionPlan: ...

    async def execute(
        self, action_plan: ActionPlan
    ) -> ActionExecutionResult | None: ...


class AvatarOutputActionExecutor:
    """既存ActionExecutorへAvatar Outputを明示的に合成するDecorator。"""

    def __init__(
        self,
        delegate: ActionExecutorPort,
        avatar_output: AvatarOutputPort | None,
    ) -> None:
        self._delegate = delegate
        self._avatar_output = avatar_output
        self._trace_logger = TraceLogger()

    async def prepare(self, action_plan: ActionPlan) -> ActionPlan:
        return await self._delegate.prepare(action_plan)

    async def execute(
        self,
        action_plan: ActionPlan,
    ) -> ActionExecutionResult | None:
        if self._avatar_output is not None:
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
        return await self._delegate.execute(action_plan)


def compose_avatar_output_executor(
    delegate: ActionExecutorPort,
    avatar_output: AvatarOutputPort | None,
) -> AvatarOutputActionExecutor:
    """Composition Rootで利用する明示的な合成関数。"""

    return AvatarOutputActionExecutor(delegate, avatar_output)
