from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue


class FakeActionPlanner:
    def __init__(self) -> None:
        self.planned_activities: list[Activity] = []

    async def plan(self, activity: Activity) -> ActionPlanGroup:
        self.planned_activities.append(activity)
        return ActionPlanGroup(
            action_plans=[
                ActionPlan(
                    action_type=ActionType.OBSERVE,
                    text="observe",
                    source_activity_id=activity.activity_id,
                )
            ]
        )


class FakeActionScheduler:
    def __init__(self) -> None:
        self.executed_groups: list[ActionPlanGroup] = []

    async def execute(self, action_plan_group: ActionPlanGroup) -> None:
        self.executed_groups.append(action_plan_group)


class BlockingActionPlanner(FakeActionPlanner):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def plan(self, activity: Activity) -> ActionPlanGroup:
        self.started.set()
        await self.release.wait()
        return await super().plan(activity)


class BlockingFirstActionScheduler(FakeActionScheduler):
    def __init__(self) -> None:
        super().__init__()
        self.first_started = threading.Event()
        self.release_first = threading.Event()

    async def execute(self, action_plan_group: ActionPlanGroup) -> None:
        self.executed_groups.append(action_plan_group)
        if len(self.executed_groups) == 1:
            self.first_started.set()
            while not self.release_first.is_set():
                await asyncio.sleep(0.01)


def _create_activity(
    activity_type: ActivityType = ActivityType.IDLE_OBSERVATION,
    priority: int = 10,
    goal: str = "状態を観察する",
) -> Activity:
    return Activity(
        activity_type=activity_type,
        goal=goal,
        priority=priority,
        context={},
        interruptible=True,
    )


# Thread 起動直後のタイミング差を吸収するため、起動状態になるまで待つ。
def _wait_until_running(
    thread: ActivityExecutorThread, timeout_seconds: float = 1.0
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if thread.is_running:
            return True
        time.sleep(0.01)
    return False


def _wait_until(predicate: object, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return True
        time.sleep(0.01)
    return False


def _create_activity_executor_thread(
    planned_activity_queue: PlannedActivityQueue,
    action_planner: FakeActionPlanner,
    action_scheduler: FakeActionScheduler,
    idle_sleep_seconds: float = 0.1,
    activity_manager: ActivityManager | None = None,
) -> ActivityExecutorThread:
    activity_manager = activity_manager or ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    return ActivityExecutorThread(
        planned_activity_queue=planned_activity_queue,
        action_planner=action_planner,  # type: ignore[arg-type]
        action_scheduler=action_scheduler,  # type: ignore[arg-type]
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
        idle_sleep_seconds=idle_sleep_seconds,
    )


@pytest.mark.asyncio
async def test_run_once_returns_none_when_queue_is_empty() -> None:
    queue = PlannedActivityQueue()
    action_planner = FakeActionPlanner()
    action_scheduler = FakeActionScheduler()
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
    )

    result = await thread.run_once()

    assert result is None
    assert action_planner.planned_activities == []
    assert action_scheduler.executed_groups == []


@pytest.mark.asyncio
async def test_run_once_plans_and_executes_next_activity() -> None:
    queue = PlannedActivityQueue()
    activity = _create_activity(priority=30)
    planned_activity = PlannedActivity(
        activity=activity, source="test", planning_reason="unit test"
    )
    action_planner = FakeActionPlanner()
    action_scheduler = FakeActionScheduler()
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
    )

    queue.put(planned_activity)
    result = await thread.run_once()

    assert result is not None
    assert result == action_scheduler.executed_groups[0]
    assert action_planner.planned_activities == [activity]
    assert len(action_scheduler.executed_groups) == 1
    assert len(action_scheduler.executed_groups[0].action_plans) == 1
    assert (
        action_scheduler.executed_groups[0].action_plans[0].source_activity_id
        == activity.activity_id
    )
    assert queue.is_empty() is True


@pytest.mark.asyncio
async def test_run_once_does_not_execute_autonomous_activity_suspended_by_user_input() -> (
    None
):
    queue = PlannedActivityQueue()
    activity_manager = ActivityManager()
    autonomous = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8)
    )
    queue.put(PlannedActivity(activity=autonomous))
    action_planner = FakeActionPlanner()
    action_scheduler = FakeActionScheduler()
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        activity_manager=activity_manager,
    )
    activity_manager.prepare_user_input(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "しりとりしたい"},
        )
    )

    result = await thread.run_once()

    assert result is None
    assert action_planner.planned_activities == []
    assert action_scheduler.executed_groups == []


def test_cancel_pending_autonomous_removes_queue_item_and_cancels_activity() -> None:
    queue = PlannedActivityQueue()
    activity_manager = ActivityManager()
    autonomous = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8)
    )
    planned = PlannedActivity(activity=autonomous)
    queue.put(planned)
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=FakeActionPlanner(),
        action_scheduler=FakeActionScheduler(),
        activity_manager=activity_manager,
    )

    canceled = thread.cancel_pending_autonomous(
        source_event_id="user-event",
        reason="user_text_received",
    )

    assert canceled == [planned]
    assert queue.is_empty()
    canceled_activity = activity_manager.get_activity(autonomous.activity_id)
    assert canceled_activity is not None
    assert canceled_activity.status.value == "canceled"


@pytest.mark.asyncio
async def test_user_input_during_action_planning_discards_generated_actions() -> None:
    queue = PlannedActivityQueue()
    activity_manager = ActivityManager()
    autonomous = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8)
    )
    queue.put(PlannedActivity(activity=autonomous))
    action_planner = BlockingActionPlanner()
    action_scheduler = FakeActionScheduler()
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        activity_manager=activity_manager,
    )
    execution_task = asyncio.create_task(thread.run_once())
    await action_planner.started.wait()

    activity_manager.prepare_user_input(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "入力"})
    )
    action_planner.release.set()
    result = await execution_task

    assert result is not None
    assert result.is_empty()
    assert action_scheduler.executed_groups == []


@pytest.mark.asyncio
async def test_run_once_executes_highest_priority_activity_first() -> None:
    queue = PlannedActivityQueue()
    low_activity = _create_activity(priority=10, goal="低優先度")
    high_activity = _create_activity(priority=90, goal="高優先度")
    action_planner = FakeActionPlanner()
    action_scheduler = FakeActionScheduler()
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
    )

    queue.put(PlannedActivity(activity=low_activity))
    queue.put(PlannedActivity(activity=high_activity))

    await thread.run_once()

    assert action_planner.planned_activities == [high_activity]
    assert queue.size() == 1
    next_planned_activity = queue.peek()

    assert next_planned_activity is not None
    assert next_planned_activity.activity == low_activity


def test_enqueue_adds_planned_activity_to_queue() -> None:
    queue = PlannedActivityQueue()
    action_planner = FakeActionPlanner()
    action_scheduler = FakeActionScheduler()
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
    )
    planned_activity = PlannedActivity(activity=_create_activity())

    thread.enqueue(planned_activity)

    assert queue.size() == 1
    assert queue.peek() == planned_activity


def test_run_sets_running_until_stopped() -> None:
    queue = PlannedActivityQueue()
    action_planner = FakeActionPlanner()
    action_scheduler = FakeActionScheduler()
    thread = _create_activity_executor_thread(
        planned_activity_queue=queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        idle_sleep_seconds=0.01,
    )

    thread.start()

    try:
        assert _wait_until_running(thread) is True
    finally:
        thread.stop()
        thread.join(timeout=1.0)

    assert thread.is_alive() is False
    assert thread.is_running is False


def test_thread_prepares_next_autonomous_speech_while_first_output_is_running() -> (
    None
):
    queue = PlannedActivityQueue()
    activity_manager = ActivityManager()
    first = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8)
    )
    second = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8)
    )
    queue.extend([PlannedActivity(activity=first), PlannedActivity(activity=second)])
    planner = FakeActionPlanner()
    scheduler = BlockingFirstActionScheduler()
    thread = _create_activity_executor_thread(
        queue,
        planner,
        scheduler,
        idle_sleep_seconds=0.01,
        activity_manager=activity_manager,
    )

    thread.start()
    try:
        assert scheduler.first_started.wait(timeout=1.0)
        assert _wait_until(lambda: len(planner.planned_activities) == 2)
        assert planner.planned_activities == [first, second]
        assert len(scheduler.executed_groups) == 1
        scheduler.release_first.set()
        assert _wait_until(lambda: len(scheduler.executed_groups) == 2)
    finally:
        scheduler.release_first.set()
        thread.stop()
        thread.join(timeout=1.0)


def test_prepared_marker_is_written_to_manager_for_detached_enriched_activity() -> (
    None
):
    queue = PlannedActivityQueue()
    activity_manager = ActivityManager()
    canonical = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, priority=8)
    )
    enriched = replace(
        canonical,
        context={**canonical.context, "similar_topic_memories": ["memory-1"]},
    )
    queue.put(PlannedActivity(activity=enriched))
    scheduler = BlockingFirstActionScheduler()
    thread = _create_activity_executor_thread(
        queue,
        FakeActionPlanner(),
        scheduler,
        idle_sleep_seconds=0.01,
        activity_manager=activity_manager,
    )

    thread.start()
    try:
        assert scheduler.first_started.wait(timeout=1.0)
        managed = activity_manager.get_activity(canonical.activity_id)
        assert managed is not None
        assert managed.context["action_plan_prepared"] is True
    finally:
        scheduler.release_first.set()
        thread.stop()
        thread.join(timeout=1.0)


def test_thread_waits_for_causal_activity_completion_before_planning_next() -> None:
    queue = PlannedActivityQueue()
    activity_manager = ActivityManager()
    first = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT, priority=8)
    )
    second = activity_manager.handle_event(
        AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT, priority=8)
    )
    queue.extend([PlannedActivity(activity=first), PlannedActivity(activity=second)])
    planner = FakeActionPlanner()
    scheduler = BlockingFirstActionScheduler()
    thread = _create_activity_executor_thread(
        queue,
        planner,
        scheduler,
        idle_sleep_seconds=0.01,
        activity_manager=activity_manager,
    )

    thread.start()
    try:
        assert scheduler.first_started.wait(timeout=1.0)
        time.sleep(0.05)
        assert planner.planned_activities == [first]
        scheduler.release_first.set()
        assert _wait_until(lambda: planner.planned_activities == [first, second])
    finally:
        scheduler.release_first.set()
        thread.stop()
        thread.join(timeout=1.0)
