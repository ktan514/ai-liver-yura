from __future__ import annotations

import time
from datetime import datetime, timezone
from queue import Queue

from app.domain.activities import Activity, ActivityType
from app.runtime.activity_planner_thread import ActivityPlannerThread, ActivityPlanningRequest
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue


class FakeActivityPlanningService:
    def __init__(self, planned_activity: PlannedActivity | None) -> None:
        self._planned_activity = planned_activity
        self.received_now: list[datetime | None] = []

    def plan_once(self, now: datetime | None = None) -> PlannedActivity | None:
        self.received_now.append(now)
        return self._planned_activity


def _create_planned_activity(priority: int = 10) -> PlannedActivity:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話す",
        priority=priority,
        context={},
        interruptible=True,
    )
    return PlannedActivity(
        activity=activity,
        source="test",
        planning_reason="unit_test",
        priority=priority,
    )


def _create_thread(
    request_queue: Queue[ActivityPlanningRequest],
    planned_activity_queue: PlannedActivityQueue,
    planning_service: FakeActivityPlanningService,
    max_queue_size: int = 3,
) -> ActivityPlannerThread:
    return ActivityPlannerThread(
        request_queue=request_queue,
        planned_activity_queue=planned_activity_queue,
        planning_service=planning_service,  # type: ignore[arg-type]
        idle_sleep_seconds=0.01,
        max_queue_size=max_queue_size,
    )


# Thread 起動直後のタイミング差を吸収するため、起動状態になるまで待つ。
def _wait_until_running(thread: ActivityPlannerThread, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if thread.is_running:
            return True
        time.sleep(0.01)
    return False


def test_run_once_adds_planned_activity_to_queue() -> None:
    request_queue: Queue[ActivityPlanningRequest] = Queue()
    planned_activity_queue = PlannedActivityQueue()
    planned_activity = _create_planned_activity(priority=30)
    planning_service = FakeActivityPlanningService(planned_activity)
    thread = _create_thread(request_queue, planned_activity_queue, planning_service)
    now = datetime.now(timezone.utc)

    result = thread.run_once(ActivityPlanningRequest(now=now))

    assert result == planned_activity
    assert planned_activity_queue.get() == planned_activity
    assert planning_service.received_now == [now]


def test_run_once_returns_none_when_service_returns_none() -> None:
    request_queue: Queue[ActivityPlanningRequest] = Queue()
    planned_activity_queue = PlannedActivityQueue()
    planning_service = FakeActivityPlanningService(None)
    thread = _create_thread(request_queue, planned_activity_queue, planning_service)

    result = thread.run_once(ActivityPlanningRequest())

    assert result is None
    assert planned_activity_queue.size() == 0
    assert planning_service.received_now == [None]


def test_run_once_does_not_plan_when_output_queue_is_full() -> None:
    request_queue: Queue[ActivityPlanningRequest] = Queue()
    planned_activity_queue = PlannedActivityQueue()
    planned_activity_queue.put(_create_planned_activity(priority=10))
    planning_service = FakeActivityPlanningService(_create_planned_activity(priority=90))
    thread = _create_thread(
        request_queue,
        planned_activity_queue,
        planning_service,
        max_queue_size=1,
    )

    result = thread.run_once(ActivityPlanningRequest())

    assert result is None
    assert planned_activity_queue.size() == 1
    assert planning_service.received_now == []


def test_run_processes_request_queue_until_stopped() -> None:
    request_queue: Queue[ActivityPlanningRequest] = Queue()
    planned_activity_queue = PlannedActivityQueue()
    planned_activity = _create_planned_activity(priority=40)
    planning_service = FakeActivityPlanningService(planned_activity)
    thread = _create_thread(request_queue, planned_activity_queue, planning_service)

    thread.start()

    try:
        assert _wait_until_running(thread) is True
        request_queue.put(ActivityPlanningRequest())
        request_queue.join()
    finally:
        thread.stop()
        thread.join(timeout=1.0)

    assert thread.is_alive() is False
    assert thread.is_running is False
    assert planned_activity_queue.get() == planned_activity
    assert planning_service.received_now == [None]


def test_stop_changes_running_state() -> None:
    request_queue: Queue[ActivityPlanningRequest] = Queue()
    planned_activity_queue = PlannedActivityQueue()
    planning_service = FakeActivityPlanningService(None)
    thread = _create_thread(request_queue, planned_activity_queue, planning_service)

    thread.start()

    try:
        assert _wait_until_running(thread) is True
    finally:
        thread.stop()
        thread.join(timeout=1.0)

    assert thread.is_alive() is False
    assert thread.is_running is False
