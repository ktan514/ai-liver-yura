from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from queue import Queue

from app.domain.activities import Activity, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
    ActivityPlanningService,
)
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue


class FakeActivityPlanningService:
    def __init__(self, planned_activity: PlannedActivity | None) -> None:
        self._planned_activity = planned_activity
        self.received_now: list[datetime | None] = []

    def plan_once(self, now: datetime | None = None) -> PlannedActivity | None:
        self.received_now.append(now)
        return self._planned_activity


# Fake classes for ActivityPlanningService tests
class FakeAgentState:
    def __init__(self) -> None:
        self.current_drive = None
        self.current_emotion = None


class FakeAgentLifeService:
    def __init__(self, event: AgentEvent | None) -> None:
        self.event = event
        self.agent_state = FakeAgentState()
        self.received_now: list[datetime | None] = []
        self.handled_events: list[AgentEvent] = []
        self.sync_count = 0

    def plan_next_event(self, now: datetime | None = None) -> AgentEvent | None:
        self.received_now.append(now)
        return self.event

    def handle_event(self, event: AgentEvent) -> None:
        self.handled_events.append(event)

    def sync_from_activity_manager(self) -> None:
        self.sync_count += 1


class FakeActivityManager:
    def __init__(self, activity: Activity) -> None:
        self.activity = activity
        self.handled_events: list[AgentEvent] = []

    def handle_event(self, event: AgentEvent) -> Activity:
        self.handled_events.append(event)
        return self.activity


class FakeEnrichActivityWithTopicMemoryUsecase:
    def __init__(self) -> None:
        self.received_activities: list[Activity] = []

    async def enrich(self, activity: Activity) -> Activity:
        self.received_activities.append(activity)
        enriched_context = dict(activity.context)
        enriched_context["similar_topic_memories"] = ["memory-1"]
        return replace(activity, context=enriched_context)


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


def _create_agent_event() -> AgentEvent:
    return AgentEvent(
        event_type=list(AgentEventType)[0],
        payload={"reason": "unit_test"},
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


def test_activity_planning_service_enriches_activity_before_returning_planned_activity() -> None:
    event = _create_agent_event()
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話す",
        priority=50,
        context={"original": "value"},
        interruptible=True,
    )
    agent_life_service = FakeAgentLifeService(event=event)
    activity_manager = FakeActivityManager(activity=activity)
    enrich_usecase = FakeEnrichActivityWithTopicMemoryUsecase()
    planning_service = ActivityPlanningService(
        agent_life_service=agent_life_service,  # type: ignore[arg-type]
        activity_manager=activity_manager,  # type: ignore[arg-type]
        enrich_activity_with_topic_memory_usecase=enrich_usecase,  # type: ignore[arg-type]
    )
    now = datetime.now(timezone.utc)

    planned_activity = planning_service.plan_once(now=now)

    assert planned_activity is not None
    assert planned_activity.activity is not activity
    assert planned_activity.activity.context == {
        "original": "value",
        "similar_topic_memories": ["memory-1"],
    }
    assert activity.context == {"original": "value"}
    assert enrich_usecase.received_activities == [activity]
    assert planned_activity.priority == 50
    assert planned_activity.planning_reason == event.event_type.value
    assert agent_life_service.received_now == [now]
    assert agent_life_service.handled_events == [event]
    assert agent_life_service.sync_count == 1
    assert activity_manager.handled_events == [event]


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
