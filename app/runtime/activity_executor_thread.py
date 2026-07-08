from __future__ import annotations

import asyncio
import threading

from app.common.trace import TraceLogger
from app.domain.actions import ActionPlanGroup
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue


class ActivityExecutorThread(threading.Thread):
    """PlannedActivityQueue から Activity を取り出して実行する常駐処理。"""

    def __init__(
        self,
        planned_activity_queue: PlannedActivityQueue,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        activity_manager: ActivityManager,
        agent_life_service: AgentLifeService,
        idle_sleep_seconds: float = 0.1,
        daemon: bool = True,
    ) -> None:
        super().__init__(name="ActivityExecutorThread", daemon=daemon)
        self._planned_activity_queue = planned_activity_queue
        self._action_planner = action_planner
        self._action_scheduler = action_scheduler
        self._activity_manager = activity_manager
        self._agent_life_service = agent_life_service
        self._idle_sleep_seconds = idle_sleep_seconds
        self._stop_requested = threading.Event()
        self._started_running = threading.Event()
        self._trace_logger = TraceLogger()

    async def run_once(self) -> ActionPlanGroup | None:
        """Queue から1件取り出し、ActionPlanGroup に変換して実行する。"""

        planned_activity = self._planned_activity_queue.get()
        if planned_activity is None:
            self._trace_logger.write(
                "activity_executor_thread:run_once:no_activity",
                queue_size=self._planned_activity_queue.size(),
            )
            return None

        self._trace_logger.write(
            "activity_executor_thread:run_once:start",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            activity_type=planned_activity.activity.activity_type.value,
            priority=planned_activity.effective_priority,
            source=planned_activity.source,
            planning_reason=planned_activity.planning_reason,
        )

        action_plan_group = await self._action_planner.plan(planned_activity.activity)
        self._trace_logger.write(
            "activity_executor_thread:run_once:actions_planned",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            action_count=len(action_plan_group.action_plans),
        )

        await self._action_scheduler.execute(action_plan_group)
        self._trace_logger.write(
            "activity_executor_thread:run_once:actions_executed",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            action_count=len(action_plan_group.action_plans),
        )

        completed_activity = self._activity_manager.complete_foreground_activity()
        self._agent_life_service.sync_from_activity_manager()
        self._trace_logger.write(
            "activity_executor_thread:run_once:activity_completed",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            completed=completed_activity is not None,
            completed_activity_id=completed_activity.activity_id if completed_activity is not None else None,
            completed_activity_type=completed_activity.activity_type.value if completed_activity is not None else None,
            active_activity_exists=self._agent_life_service.agent_state.active_activity is not None,
            pending_activity_count=len(self._agent_life_service.agent_state.pending_activities),
            suspended_activity_count=len(self._agent_life_service.agent_state.suspended_activities),
        )

        return action_plan_group

    def run(self) -> None:
        """stop() が呼ばれるまで Queue の Activity を実行し続ける。"""

        self._stop_requested.clear()
        self._started_running.clear()
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        """Thread 内の asyncio event loop で Activity 実行を継続する。"""

        self._started_running.set()
        self._trace_logger.write("activity_executor_thread:run:start")

        try:
            while not self._stop_requested.is_set():
                action_plan_group = await self.run_once()
                if action_plan_group is None:
                    await asyncio.sleep(self._idle_sleep_seconds)
        finally:
            self._started_running.clear()
            self._trace_logger.write("activity_executor_thread:run:stopped")

    def stop(self) -> None:
        """継続実行処理を停止する。"""

        self._stop_requested.set()
        self._trace_logger.write("activity_executor_thread:stop:requested")

    def enqueue(self, planned_activity: PlannedActivity) -> None:
        """実行予定 Activity を Queue に追加する。"""

        self._planned_activity_queue.put(planned_activity)
        self._trace_logger.write(
            "activity_executor_thread:enqueue:added",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            activity_type=planned_activity.activity.activity_type.value,
            priority=planned_activity.effective_priority,
            queue_size=self._planned_activity_queue.size(),
        )

    @property
    def is_running(self) -> bool:
        """継続実行中かどうかを返す。"""

        return (
            self.is_alive()
            and self._started_running.is_set()
            and not self._stop_requested.is_set()
        )