from __future__ import annotations

import asyncio
import heapq
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from app.core.contracts.activity_policy import ActivityPolicy
from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.domain.activity_turn_result import (
    ActionExecutionResult,
    ActionExecutionStatus,
    ActivityOutputResult,
    ActivityOutputStatus,
)
from app.utils.trace import TraceLogger


class ActionExecutor(Protocol):
    """ActionPlan を実行する Executor のインターフェース。"""

    async def execute(self, action_plan: ActionPlan) -> ActionExecutionResult | None:
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
        self._prevent_new_actions = False
        self._running_tasks: set[asyncio.Task[object]] = set()
        self._lifecycle_gate: ActivityPolicy | None = None

    def set_activity_policy(self, gate: ActivityPolicy) -> None:
        self._lifecycle_gate = gate

    def prevent_new_actions(self) -> None:
        self._prevent_new_actions = True

    def cancel_outputs(self) -> bool:
        self._prevent_new_actions = True
        current = asyncio.current_task()
        canceled = False
        for task in tuple(self._running_tasks):
            if task is not current and not task.done():
                task.cancel()
                canceled = True
        return canceled

    async def execute(self, action_plan_group: ActionPlanGroup) -> ActivityOutputResult:
        if self._prevent_new_actions:
            return self._canceled_before_start(action_plan_group)
        if self._lifecycle_gate is not None and action_plan_group.action_plans:
            metadata = action_plan_group.action_plans[0].metadata
            session_id = metadata.get("lifecycle_session_id")
            activity_type = metadata.get("lifecycle_activity_type")
            if isinstance(session_id, str):
                decision = self._lifecycle_gate.evaluate_policy(
                    "enqueue_action",
                    session_id,
                    activity_type=str(activity_type or ""),
                )
                if not decision.allowed:
                    return self._canceled_before_start(action_plan_group)
                operation_by_action = {
                    ActionType.SPEAK: "start_speech",
                    ActionType.UPDATE_SUBTITLE: "update_subtitle",
                    ActionType.CHANGE_EXPRESSION: "change_expression",
                    ActionType.MOVE: "start_motion",
                }
                for action in action_plan_group.action_plans:
                    operation = operation_by_action.get(action.action_type)
                    if operation is None:
                        continue
                    action_decision = self._lifecycle_gate.evaluate_policy(
                        operation,
                        session_id,
                        activity_type=str(activity_type or ""),
                    )
                    if not action_decision.allowed:
                        return self._canceled_before_start(action_plan_group)
        task = asyncio.current_task()
        if task is not None:
            self._running_tasks.add(task)
        try:
            return await self._execute_allowed(action_plan_group)
        finally:
            if task is not None:
                self._running_tasks.discard(task)

    async def _execute_allowed(self, action_plan_group: ActionPlanGroup) -> ActivityOutputResult:
        started_at = datetime.now(timezone.utc)
        turn_result = action_plan_group.activity_turn_result
        activity_turn_id = (
            turn_result.activity_turn_id if turn_result is not None else action_plan_group.group_id
        )
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
            output_result = ActivityOutputResult(
                status=ActivityOutputStatus.COMPLETED,
                output_unit_id=action_plan_group.group_id,
                activity_turn_id=activity_turn_id,
                ongoing_activity_id=turn_result.ongoing_activity_id if turn_result else None,
                source_event_id=turn_result.source_event_id if turn_result else None,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                activity_result_id=(
                    turn_result.output_result.activity_result_id
                    if turn_result is not None and turn_result.output_result is not None
                    else str(uuid4())
                ),
                trace_id=turn_result.trace_id if turn_result else None,
                parent_trace_id=turn_result.parent_trace_id if turn_result else None,
                behavior_plan_id=turn_result.behavior_plan_id if turn_result else None,
            )
            self._trace_output_result(output_result)
            return output_result

        try:
            if any(
                action_plan.action_type == ActionType.SPEAK
                for action_plan in action_plan_group.action_plans
            ):
                action_results = await self._execute_synchronized_output(
                    action_plan_group, activity_turn_id=activity_turn_id
                )
            else:
                action_results = list(
                    await asyncio.gather(
                        *(
                            self._execute_with_resource_locks(
                                action_plan,
                                activity_turn_id=activity_turn_id,
                                output_unit_id=action_plan_group.group_id,
                            )
                            for action_plan in action_plan_group.action_plans
                        )
                    )
                )
        except asyncio.CancelledError:
            now = datetime.now(timezone.utc)
            action_results = [
                ActionExecutionResult(
                    action_id=plan.action_id,
                    action_type=plan.action_type.value,
                    status=ActionExecutionStatus.CANCELED,
                    output_unit_id=action_plan_group.group_id,
                    activity_turn_id=activity_turn_id,
                    error="action_group_canceled",
                    started_at=started_at,
                    finished_at=now,
                )
                for plan in action_plan_group.action_plans
            ]
            output_result = self._build_output_result(
                action_plan_group,
                action_results,
                started_at=started_at,
                forced_status=ActivityOutputStatus.CANCELED,
                error="action_group_canceled",
            )
            self._trace_output_result(output_result)
            return output_result
        self._trace_logger.write(
            "action_scheduler:execute:finished",
            output_unit_id=action_plan_group.group_id,
            action_count=len(action_plan_group.action_plans),
            source_activity_id=action_plan_group.source_activity_id,
        )
        output_result = self._build_output_result(
            action_plan_group,
            action_results,
            started_at=started_at,
        )
        self._trace_output_result(output_result)
        return output_result

    def _canceled_before_start(self, group: ActionPlanGroup) -> ActivityOutputResult:
        turn = group.activity_turn_result
        now = datetime.now(timezone.utc)
        return ActivityOutputResult(
            status=ActivityOutputStatus.CANCELED,
            output_unit_id=group.group_id,
            activity_turn_id=turn.activity_turn_id if turn else group.group_id,
            source_event_id=turn.source_event_id if turn else None,
            error="output_prevented_by_emergency_stop",
            started_at=now,
            finished_at=now,
        )

    def _trace_output_result(self, result: ActivityOutputResult) -> None:
        self._trace_logger.info(
            "action_scheduler:output_result",
            trace_id=result.trace_id,
            parent_trace_id=result.parent_trace_id,
            activity_turn_id=result.activity_turn_id,
            output_unit_id=result.output_unit_id,
            activity_result_id=result.activity_result_id,
            output_status=result.status.value,
            failure_stage=result.failure_stage,
        )
        self._trace_logger.debug(
            "action_scheduler:output_result:actions",
            activity_turn_id=result.activity_turn_id,
            output_unit_id=result.output_unit_id,
            action_results=[
                {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "status": action.status.value,
                    "error": action.error,
                }
                for action in result.action_results
            ],
        )

    async def _execute_synchronized_output(
        self, action_plan_group: ActionPlanGroup, *, activity_turn_id: str
    ) -> list[ActionExecutionResult]:
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
        self._trace_logger.debug(
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
        self._trace_logger.debug(
            "action_scheduler:output_unit:dequeued",
            output_unit_id=output_unit_id,
            output_priority=action_plan_group.output_priority,
            queue_sequence=queue_sequence,
        )
        try:
            return await self._execute_locked_output(
                action_plan_group,
                resources=resources,
                queue_sequence=queue_sequence,
                activity_turn_id=activity_turn_id,
            )
        finally:
            self._output_gate.release()

    async def _execute_locked_output(
        self,
        action_plan_group: ActionPlanGroup,
        *,
        resources: list[ActionResource],
        queue_sequence: int,
        activity_turn_id: str,
    ) -> list[ActionExecutionResult]:
        output_unit_id = action_plan_group.group_id
        async with _MultiLock([self._locks[resource] for resource in resources]):
            self._trace_logger.debug(
                "action_scheduler:output_unit:started",
                output_unit_id=output_unit_id,
                output_priority=action_plan_group.output_priority,
                queue_sequence=queue_sequence,
                source_activity_id=action_plan_group.source_activity_id,
            )
            results: list[ActionExecutionResult] = []
            for action_plan in self._synchronized_action_order(action_plan_group):
                self._trace_logger.debug(
                    "action_scheduler:output_unit:action_started",
                    output_unit_id=output_unit_id,
                    action_id=action_plan.action_id,
                    action_type=action_plan.action_type.value,
                )
                results.append(
                    await self._execute_action(
                        action_plan,
                        activity_turn_id=activity_turn_id,
                        output_unit_id=action_plan_group.group_id,
                    )
                )
                self._trace_logger.debug(
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
            return results

    @staticmethod
    def _synchronized_action_order(
        action_plan_group: ActionPlanGroup,
    ) -> list[ActionPlan]:
        visual_types = {ActionType.UPDATE_SUBTITLE, ActionType.CHANGE_EXPRESSION}
        return sorted(
            action_plan_group.action_plans,
            key=lambda action_plan: action_plan.action_type not in visual_types,
        )

    async def _execute_with_resource_locks(
        self,
        action_plan: ActionPlan,
        *,
        activity_turn_id: str,
        output_unit_id: str,
    ) -> ActionExecutionResult:
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
            result = await self._execute_action(
                action_plan,
                activity_turn_id=activity_turn_id,
                output_unit_id=output_unit_id,
            )
            self._trace_logger.write(
                "action_scheduler:action:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
            )
            return result

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
            result = await self._execute_action(
                action_plan,
                activity_turn_id=activity_turn_id,
                output_unit_id=output_unit_id,
            )
            self._trace_logger.write(
                "action_scheduler:action:finished",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                resources=[resource.value for resource in resources],
            )
            return result

    async def _execute_action(
        self,
        action_plan: ActionPlan,
        *,
        activity_turn_id: str,
        output_unit_id: str,
    ) -> ActionExecutionResult:
        started_at = datetime.now(timezone.utc)
        try:
            result = await self._action_executor.execute(action_plan)
        except asyncio.CancelledError:
            return ActionExecutionResult(
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                status=ActionExecutionStatus.CANCELED,
                output_unit_id=action_plan.output_unit_id or output_unit_id,
                activity_turn_id=activity_turn_id,
                error="action_canceled",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        except Exception as error:
            self._trace_logger.warning(
                "action_scheduler:action:failed",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                activity_turn_id=activity_turn_id,
                error_type=type(error).__name__,
            )
            return ActionExecutionResult(
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                status=ActionExecutionStatus.FAILED,
                output_unit_id=action_plan.output_unit_id or output_unit_id,
                activity_turn_id=activity_turn_id,
                error=f"{type(error).__name__}: {error}",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        if isinstance(result, ActionExecutionResult):
            return ActionExecutionResult(
                action_id=result.action_id,
                action_type=result.action_type,
                status=result.status,
                output_unit_id=action_plan.output_unit_id
                or result.output_unit_id
                or output_unit_id,
                activity_turn_id=activity_turn_id,
                error=result.error,
                started_at=result.started_at,
                finished_at=result.finished_at,
            )
        return ActionExecutionResult(
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            status=ActionExecutionStatus.COMPLETED,
            output_unit_id=action_plan.output_unit_id or output_unit_id,
            activity_turn_id=activity_turn_id,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_output_result(
        group: ActionPlanGroup,
        action_results: list[ActionExecutionResult],
        *,
        started_at: datetime,
        forced_status: ActivityOutputStatus | None = None,
        error: str | None = None,
    ) -> ActivityOutputResult:
        completed = sum(
            result.status == ActionExecutionStatus.COMPLETED for result in action_results
        )
        failed = sum(result.status == ActionExecutionStatus.FAILED for result in action_results)
        canceled = sum(result.status == ActionExecutionStatus.CANCELED for result in action_results)
        if forced_status is not None:
            status = forced_status
        elif completed == len(action_results):
            status = ActivityOutputStatus.COMPLETED
        elif completed and (failed or canceled):
            status = ActivityOutputStatus.PARTIALLY_COMPLETED
        elif canceled and not failed:
            status = ActivityOutputStatus.CANCELED
        else:
            status = ActivityOutputStatus.FAILED
        turn_result = group.activity_turn_result
        planned_output = turn_result.output_result if turn_result is not None else None
        correlated_actions = tuple(
            replace(
                result,
                trace_id=turn_result.trace_id if turn_result is not None else None,
                parent_trace_id=(turn_result.parent_trace_id if turn_result is not None else None),
            )
            for result in action_results
        )
        return ActivityOutputResult(
            status=status,
            output_unit_id=group.group_id,
            activity_turn_id=(
                turn_result.activity_turn_id if turn_result is not None else group.group_id
            ),
            ongoing_activity_id=turn_result.ongoing_activity_id if turn_result else None,
            source_event_id=turn_result.source_event_id if turn_result else None,
            action_results=correlated_actions,
            failure_stage="action_execution"
            if status
            in {
                ActivityOutputStatus.PARTIALLY_COMPLETED,
                ActivityOutputStatus.FAILED,
                ActivityOutputStatus.CANCELED,
            }
            else None,
            error=error,
            activity_result_id=planned_output.activity_result_id
            if planned_output is not None
            else str(uuid4()),
            started_at=planned_output.started_at if planned_output is not None else started_at,
            finished_at=datetime.now(timezone.utc),
            trace_id=turn_result.trace_id if turn_result else None,
            parent_trace_id=turn_result.parent_trace_id if turn_result else None,
            behavior_plan_id=turn_result.behavior_plan_id if turn_result else None,
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
