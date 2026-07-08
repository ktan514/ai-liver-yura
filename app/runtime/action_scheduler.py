from __future__ import annotations

import asyncio
from typing import Protocol

from app.common.trace import TraceLogger

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource


class ActionExecutor(Protocol):
    """ActionPlan を実行する Executor のインターフェース。"""

    async def execute(self, action_plan: ActionPlan) -> None:
        """ActionPlan を実行する。"""


class ActionScheduler:
    """ActionPlanGroup をリソース単位で安全に実行する。"""

    def __init__(self, action_executor: ActionExecutor) -> None:
        self._action_executor = action_executor
        self._locks: dict[ActionResource, asyncio.Lock] = {
            resource: asyncio.Lock() for resource in ActionResource
        }
        self._trace_logger = TraceLogger()

    async def execute(self, action_plan_group: ActionPlanGroup) -> None:
        self._trace_logger.write(
            "action_scheduler:execute:start",
            action_count=len(action_plan_group.action_plans),
            source_activity_id=action_plan_group.source_activity_id,
            action_types=[
                action_plan.action_type.value
                for action_plan in action_plan_group.action_plans
            ],
        )
        if action_plan_group.is_empty():
            self._trace_logger.write("action_scheduler:execute:empty")
            return

        await asyncio.gather(
            *(
                self._execute_with_resource_locks(action_plan)
                for action_plan in action_plan_group.action_plans
            )
        )
        self._trace_logger.write(
            "action_scheduler:execute:finished",
            action_count=len(action_plan_group.action_plans),
            source_activity_id=action_plan_group.source_activity_id,
        )

    async def _execute_with_resource_locks(self, action_plan: ActionPlan) -> None:
        self._trace_logger.write(
            "action_scheduler:action:start",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            source_activity_id=action_plan.source_activity_id,
            required_resources=[
                resource.value for resource in action_plan.required_resources
            ],
        )
        resources = sorted(action_plan.required_resources, key=lambda resource: resource.value)

        if not resources:
            self._trace_logger.write(
                "action_scheduler:action:execute_without_locks",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            await self._action_executor.execute(action_plan)
            self._trace_logger.write(
                "action_scheduler:action:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return

        self._trace_logger.write(
            "action_scheduler:action:waiting_locks",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            resources=[resource.value for resource in resources],
        )
        async with _MultiLock([self._locks[resource] for resource in resources]):
            self._trace_logger.write(
                "action_scheduler:action:locks_acquired",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                resources=[resource.value for resource in resources],
            )
            await self._action_executor.execute(action_plan)
            self._trace_logger.write(
                "action_scheduler:action:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                resources=[resource.value for resource in resources],
            )


class _MultiLock:
    """複数 Lock を固定順で取得して、リソース競合時のデッドロックを防ぐ。"""

    def __init__(self, locks: list[asyncio.Lock]) -> None:
        self._locks = locks

    async def __aenter__(self) -> None:
        for lock in self._locks:
            await lock.acquire()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        for lock in reversed(self._locks):
            lock.release()