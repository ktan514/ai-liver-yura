from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue

from app.common.trace import TraceLogger
from app.domain.activities import Activity
from app.domain.events import AgentEvent
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue


@dataclass(frozen=True)
class ActivityPlanningRequest:
    """ActivityPlannerThread への入力要求。"""

    now: datetime | None = None


class ActivityPlanningService:
    """Activity 計画の同期処理本体。Thread や Queue には依存しない。"""

    def __init__(
        self,
        agent_life_service: AgentLifeService,
        activity_manager: ActivityManager,
    ) -> None:
        self._agent_life_service = agent_life_service
        self._activity_manager = activity_manager

    def plan_once(self, now: datetime | None = None) -> PlannedActivity | None:
        """必要であれば Activity を1件計画する。"""

        event = self._agent_life_service.plan_next_event(now=now)
        if event is None:
            return None

        activity = self._create_activity(event)
        return PlannedActivity(
            activity=activity,
            source="agent_life_service",
            planning_reason=event.event_type.value,
            priority=activity.priority,
            planned_drive=self._agent_life_service.agent_state.current_drive,
            planned_emotion=self._agent_life_service.agent_state.current_emotion,
        )

    def _create_activity(self, event: AgentEvent) -> Activity:
        """Event から Activity を生成し、AgentState にも同期する。"""

        activity = self._activity_manager.handle_event(event)
        self._agent_life_service.handle_event(event)
        self._agent_life_service.sync_from_activity_manager()
        return activity


class ActivityPlannerThread(threading.Thread):
    """Activity 計画要求を Queue から受け取り、計画結果を Queue に出力する常駐処理。"""

    def __init__(
        self,
        request_queue: Queue[ActivityPlanningRequest],
        planned_activity_queue: PlannedActivityQueue,
        planning_service: ActivityPlanningService,
        idle_sleep_seconds: float = 0.1,
        max_queue_size: int = 3,
        daemon: bool = True,
    ) -> None:
        super().__init__(name="ActivityPlannerThread", daemon=daemon)
        self._request_queue = request_queue
        self._planned_activity_queue = planned_activity_queue
        self._planning_service = planning_service
        self._idle_sleep_seconds = idle_sleep_seconds
        self._max_queue_size = max_queue_size
        self._stop_requested = threading.Event()
        self._trace_logger = TraceLogger()

    def run_once(self, request: ActivityPlanningRequest) -> PlannedActivity | None:
        """Activity 計画要求を1件処理し、結果を PlannedActivityQueue に追加する。"""

        queue_size = self._planned_activity_queue.size()
        if queue_size >= self._max_queue_size:
            self._trace_logger.write(
                "activity_planner_thread:run_once:queue_full",
                queue_size=queue_size,
                max_queue_size=self._max_queue_size,
            )
            return None

        planned_activity = self._planning_service.plan_once(now=request.now)
        if planned_activity is None:
            self._trace_logger.write(
                "activity_planner_thread:run_once:no_activity",
                queue_size=queue_size,
                max_queue_size=self._max_queue_size,
            )
            return None

        self._planned_activity_queue.put(planned_activity)

        self._trace_logger.write(
            "activity_planner_thread:run_once:planned_activity_added",
            planned_activity_id=planned_activity.planned_activity_id,
            activity_id=planned_activity.activity.activity_id,
            activity_type=planned_activity.activity.activity_type.value,
            priority=planned_activity.effective_priority,
            queue_size=self._planned_activity_queue.size(),
        )

        return planned_activity

    def run(self) -> None:
        """stop() が呼ばれるまで Activity 計画要求を処理する。"""

        self._stop_requested.clear()
        self._trace_logger.write("activity_planner_thread:run:start")

        while not self._stop_requested.is_set():
            try:
                request = self._request_queue.get(timeout=self._idle_sleep_seconds)
            except Empty:
                continue

            try:
                self.run_once(request)
            finally:
                self._request_queue.task_done()

        self._trace_logger.write("activity_planner_thread:run:stopped")

    def stop(self) -> None:
        """継続実行処理を停止する。"""

        self._stop_requested.set()
        self._trace_logger.write("activity_planner_thread:stop:requested")

    @property
    def is_running(self) -> bool:
        """継続実行中かどうかを返す。"""

        return self.is_alive() and not self._stop_requested.is_set()