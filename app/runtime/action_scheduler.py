

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource


ActionExecutor = Callable[[ActionPlan], Awaitable[None]]


class ActionScheduler:
    """ActionPlanGroup をリソース単位で安全に実行する。"""

    def __init__(self, action_executor: ActionExecutor) -> None:
        self._action_executor = action_executor
        self._locks: dict[ActionResource, asyncio.Lock] = {
            resource: asyncio.Lock() for resource in ActionResource
        }

    async def execute(self, action_plan_group: ActionPlanGroup) -> None:
        if action_plan_group.is_empty():
            return

        await asyncio.gather(
            *(
                self._execute_with_resource_locks(action_plan)
                for action_plan in action_plan_group.action_plans
            )
        )

    async def _execute_with_resource_locks(self, action_plan: ActionPlan) -> None:
        resources = sorted(action_plan.required_resources, key=lambda resource: resource.value)

        if not resources:
            await self._action_executor(action_plan)
            return

        async with _MultiLock([self._locks[resource] for resource in resources]):
            await self._action_executor(action_plan)


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