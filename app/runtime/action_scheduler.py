from __future__ import annotations

import asyncio
import heapq
import threading
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.utils.trace import TraceLogger


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
        self._output_gate = _PriorityOutputGate()

    async def execute(self, action_plan_group: ActionPlanGroup) -> None:
        self._trace_logger.write(
            "action_scheduler:execute:start",
            output_unit_id=action_plan_group.group_id,
            action_count=len(action_plan_group.action_plans),
            source_activity_id=action_plan_group.source_activity_id,
            action_types=[
                action_plan.action_type.value for action_plan in action_plan_group.action_plans
            ],
        )
        if action_plan_group.is_empty():
            self._trace_logger.write("action_scheduler:execute:empty")
            return

        if any(
            action_plan.action_type == ActionType.SPEAK
            for action_plan in action_plan_group.action_plans
        ):
            await self._execute_synchronized_output(action_plan_group)
        else:
            await asyncio.gather(
                *(
                    self._execute_with_resource_locks(action_plan)
                    for action_plan in action_plan_group.action_plans
                )
            )
        self._trace_logger.write(
            "action_scheduler:execute:finished",
            output_unit_id=action_plan_group.group_id,
            action_count=len(action_plan_group.action_plans),
            source_activity_id=action_plan_group.source_activity_id,
        )

    async def _execute_synchronized_output(self, action_plan_group: ActionPlanGroup) -> None:
        """字幕・表情・音声を、追い越しのない1つの出力単位として実行する。"""

        resources = sorted(
            {
                resource
                for action_plan in action_plan_group.action_plans
                for resource in action_plan.required_resources
            },
            key=lambda resource: resource.value,
        )
        output_unit_id = action_plan_group.group_id
        self._trace_logger.info(
            "action_scheduler:output_unit:waiting",
            output_unit_id=output_unit_id,
            output_priority=action_plan_group.output_priority,
            source_activity_id=action_plan_group.source_activity_id,
            resources=[resource.value for resource in resources],
        )
        queue_sequence = await asyncio.to_thread(
            self._output_gate.acquire,
            action_plan_group.output_priority,
        )
        self._trace_logger.info(
            "action_scheduler:output_unit:dequeued",
            output_unit_id=output_unit_id,
            output_priority=action_plan_group.output_priority,
            queue_sequence=queue_sequence,
        )
        try:
            await self._execute_locked_output(
                action_plan_group,
                resources=resources,
                queue_sequence=queue_sequence,
            )
        finally:
            self._output_gate.release()

    async def _execute_locked_output(
        self,
        action_plan_group: ActionPlanGroup,
        *,
        resources: list[ActionResource],
        queue_sequence: int,
    ) -> None:
        output_unit_id = action_plan_group.group_id
        async with _MultiLock([self._locks[resource] for resource in resources]):
            self._trace_logger.info(
                "action_scheduler:output_unit:started",
                output_unit_id=output_unit_id,
                output_priority=action_plan_group.output_priority,
                queue_sequence=queue_sequence,
                source_activity_id=action_plan_group.source_activity_id,
            )
            for action_plan in self._synchronized_action_order(action_plan_group):
                self._trace_logger.info(
                    "action_scheduler:output_unit:action_started",
                    output_unit_id=output_unit_id,
                    action_id=action_plan.action_id,
                    action_type=action_plan.action_type.value,
                )
                await self._action_executor.execute(action_plan)
                self._trace_logger.info(
                    "action_scheduler:output_unit:action_finished",
                    output_unit_id=output_unit_id,
                    action_id=action_plan.action_id,
                    action_type=action_plan.action_type.value,
                )
            self._trace_logger.info(
                "action_scheduler:output_unit:finished",
                output_unit_id=output_unit_id,
                source_activity_id=action_plan_group.source_activity_id,
            )

    @staticmethod
    def _synchronized_action_order(
        action_plan_group: ActionPlanGroup,
    ) -> list[ActionPlan]:
        visual_types = {ActionType.UPDATE_SUBTITLE, ActionType.CHANGE_EXPRESSION}
        return sorted(
            action_plan_group.action_plans,
            key=lambda action_plan: action_plan.action_type not in visual_types,
        )

    async def _execute_with_resource_locks(self, action_plan: ActionPlan) -> None:
        self._trace_logger.write(
            "action_scheduler:action:start",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            source_activity_id=action_plan.source_activity_id,
            required_resources=[resource.value for resource in action_plan.required_resources],
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


@dataclass(order=True, slots=True)
class _OutputWaiter:
    sort_priority: int
    sequence: int
    token: object = field(compare=False)


class _PriorityOutputGate:
    """イベントループをまたいで、音声出力を優先度順に1件ずつ通す。"""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._waiting: list[_OutputWaiter] = []
        self._next_sequence = 0
        self._active = False

    def acquire(self, priority: int) -> int:
        token = object()
        with self._condition:
            sequence = self._next_sequence
            self._next_sequence += 1
            waiter = _OutputWaiter(-priority, sequence, token)
            heapq.heappush(self._waiting, waiter)
            while self._active or self._waiting[0].token is not token:
                self._condition.wait()
            heapq.heappop(self._waiting)
            self._active = True
            return sequence

    def release(self) -> None:
        with self._condition:
            self._active = False
            self._condition.notify_all()
