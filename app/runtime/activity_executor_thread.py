from __future__ import annotations

import asyncio
import threading

from app.domain.actions import ActionPlanGroup
from app.domain.activities import ActivityStatus, ActivityType
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue
from app.utils.trace import TraceLogger


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

        current_activity = self._activity_manager.get_activity(
            planned_activity.activity.activity_id
        )
        if current_activity is not None and current_activity.status != ActivityStatus.ACTIVE:
            self._trace_logger.info(
                "activity_executor_thread:run_once:activity_skipped",
                planned_activity_id=planned_activity.planned_activity_id,
                activity_id=current_activity.activity_id,
                activity_type=current_activity.activity_type.value,
                activity_status=current_activity.status.value,
                reason="activity_not_active_before_action_planning",
            )
            return None

        action_plan_group = await self._action_planner.plan(planned_activity.activity)
        self._trace_logger.write(
            "activity_executor_thread:run_once:actions_planned",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            action_count=len(action_plan_group.action_plans),
        )

        current_activity = self._activity_manager.get_activity(
            planned_activity.activity.activity_id
        )
        if current_activity is not None and current_activity.status != ActivityStatus.ACTIVE:
            self._trace_logger.info(
                "activity_executor_thread:run_once:actions_canceled",
                planned_activity_id=planned_activity.planned_activity_id,
                activity_id=current_activity.activity_id,
                activity_status=current_activity.status.value,
                action_ids=[action.action_id for action in action_plan_group.action_plans],
                action_types=[
                    action.action_type.value for action in action_plan_group.action_plans
                ],
                source_activity_ids=[
                    action.source_activity_id for action in action_plan_group.action_plans
                ],
                reason="activity_not_active_before_action_execution",
            )
            return ActionPlanGroup(source_activity_id=current_activity.activity_id)

        await self._action_scheduler.execute(action_plan_group)
        self._trace_logger.write(
            "activity_executor_thread:run_once:actions_executed",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            action_count=len(action_plan_group.action_plans),
        )

        completed_activity = self._activity_manager.complete_processed_activity(
            planned_activity.activity.activity_id
        )
        self._agent_life_service.sync_from_activity_manager()
        self._trace_logger.write(
            "activity_executor_thread:run_once:activity_completed",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            completed=completed_activity is not None,
            completed_activity_id=completed_activity.activity_id
            if completed_activity is not None
            else None,
            completed_activity_type=completed_activity.activity_type.value
            if completed_activity is not None
            else None,
            active_activity_exists=self._agent_life_service.agent_state.active_activity is not None,
            pending_activity_count=len(self._agent_life_service.agent_state.pending_activities),
            suspended_activity_count=len(self._agent_life_service.agent_state.suspended_activities),
        )

        return action_plan_group

    def cancel_pending_autonomous(
        self,
        *,
        source_event_id: str,
        reason: str,
    ) -> list[PlannedActivity]:
        """Queue内の未実行自律Activityを取り除き、CANCELEDへ変更する。"""

        discarded = self._planned_activity_queue.discard_where(
            lambda item: item.activity.activity_type == ActivityType.AUTONOMOUS_TALK
        )
        for planned_activity in discarded:
            self._activity_manager.cancel_activity(
                planned_activity.activity.activity_id,
                reason=reason,
            )
            self._trace_logger.info(
                "activity_executor_thread:pending_autonomous_canceled",
                planned_activity_id=planned_activity.planned_activity_id,
                activity_id=planned_activity.activity.activity_id,
                activity_type=planned_activity.activity.activity_type.value,
                source_event_id=source_event_id,
                reason=reason,
            )
        return discarded

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
            self.is_alive() and self._started_running.is_set() and not self._stop_requested.is_set()
        )
