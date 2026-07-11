from __future__ import annotations


import asyncio
from queue import Queue

from app.utils.trace import TraceLogger

from app.domain.actions import ActionPlanGroup
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_planner_thread import ActivityPlannerThread, ActivityPlanningRequest
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_filter import DefaultEventFilter, EventFilter
from app.runtime.event_prioritizer import DefaultEventPrioritizer, EventPrioritizer
from app.runtime.event_queue import EventQueue


class RuntimeCoordinator:
    """外部イベント処理と常駐 Thread の起動・停止を調停する中核。"""

    def __init__(
        self,
        event_queue: EventQueue,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        activity_planning_request_queue: Queue[ActivityPlanningRequest],
        activity_planner_thread: ActivityPlannerThread,
        activity_executor_thread: ActivityExecutorThread,
        event_filter: EventFilter | None = None,
        event_prioritizer: EventPrioritizer | None = None,
        event_buffer: EventBuffer | None = None,
        agent_life_service: AgentLifeService | None = None,
    ) -> None:
        self._event_queue = event_queue
        self._activity_manager = activity_manager
        self._action_planner = action_planner
        self._action_scheduler = action_scheduler
        self._activity_planning_request_queue = activity_planning_request_queue
        self._activity_planner_thread = activity_planner_thread
        self._activity_executor_thread = activity_executor_thread
        self._event_filter = event_filter or DefaultEventFilter()
        self._event_prioritizer = event_prioritizer or DefaultEventPrioritizer()
        self._event_buffer = event_buffer or EventBuffer()
        self._agent_life_service = agent_life_service or AgentLifeService(activity_manager)
        self._running = False
        self._thread_join_timeout_seconds = 1.0
        self._trace_logger = TraceLogger()

    async def publish_event(self, event: AgentEvent) -> None:
        await self.publish_events([event])

    async def publish_events(self, events: list[AgentEvent]) -> None:
        self._trace_logger.write(
            "runtime_coordinator:publish_events:start",
            event_count=len(events),
        )
        for event in events:
            filtered_event = self._event_filter.filter(event)
            if filtered_event is None:
                continue
            self._trace_logger.write(
                "runtime_coordinator:publish_events:filtered",
                event_type=event.event_type.value,
                event_id=event.event_id,
            )
            prioritized_event = self._event_prioritizer.prioritize(filtered_event)
            self._trace_logger.write(
                "runtime_coordinator:publish_events:prioritized",
                event_type=prioritized_event.event_type.value,
                event_id=prioritized_event.event_id,
                priority=prioritized_event.priority,
                discardable=prioritized_event.discardable,
                replace_key=prioritized_event.replace_key,
            )
            self._event_buffer.put(prioritized_event)

        for buffered_event in self._event_buffer.drain():
            self._trace_logger.write(
                "runtime_coordinator:publish_events:queue_put",
                event_type=buffered_event.event_type.value,
                event_id=buffered_event.event_id,
                priority=buffered_event.priority,
                discardable=buffered_event.discardable,
                replace_key=buffered_event.replace_key,
                queue_empty_before_put=self._event_queue.empty(),
            )
            await self._event_queue.put(buffered_event)

    async def run_once(self) -> ActionPlanGroup | None:
        self._trace_logger.write(
            "runtime_coordinator:run_once:start",
            queue_empty=self._event_queue.empty(),
            drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
            drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
            drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
            drive_energy=self._agent_life_service.agent_state.current_drive.energy,
        )
        if self._event_queue.empty():
            self._activity_planning_request_queue.put(ActivityPlanningRequest())
            self._trace_logger.write(
                "runtime_coordinator:run_once:activity_planning_requested",
                request_queue_size=self._activity_planning_request_queue.qsize(),
            )
            self._trace_logger.write("runtime_coordinator:run_once:no_event")
            return None

        event = await self._event_queue.get()
        self._trace_logger.write(
            "runtime_coordinator:run_once:queue_get",
            event_type=event.event_type.value,
            event_id=event.event_id,
            priority=event.priority,
            discardable=event.discardable,
            replace_key=event.replace_key,
        )
        return await self._handle_event(event)

    async def run(self) -> None:
        self._running = True
        self._trace_logger.write("runtime_coordinator:run:start")

        self._start_threads()

        while self._running:
            action_plan_group = await self.run_once()
            if action_plan_group is None:
                self._trace_logger.write("runtime_coordinator:run:idle_sleep")
                await asyncio.sleep(0.01)

    def stop(self) -> None:
        self._trace_logger.write("runtime_coordinator:stop")
        self._running = False
        self._stop_threads()

    def _start_threads(self) -> None:
        """常駐 Thread を必要に応じて起動する。"""

        if not self._activity_planner_thread.is_alive():
            self._activity_planner_thread.start()

        if not self._activity_executor_thread.is_alive():
            self._activity_executor_thread.start()

        self._trace_logger.write(
            "runtime_coordinator:threads:start",
            activity_planner_thread_alive=self._activity_planner_thread.is_alive(),
            activity_executor_thread_alive=self._activity_executor_thread.is_alive(),
        )

    def _stop_threads(self) -> None:
        """常駐 Thread に停止要求を送り、終了を待つ。"""

        self._activity_planner_thread.stop()
        self._activity_executor_thread.stop()

        if self._activity_planner_thread.is_alive():
            self._activity_planner_thread.join(timeout=self._thread_join_timeout_seconds)

        if self._activity_executor_thread.is_alive():
            self._activity_executor_thread.join(timeout=self._thread_join_timeout_seconds)

        self._trace_logger.write(
            "runtime_coordinator:threads:stopped",
            activity_planner_thread_alive=self._activity_planner_thread.is_alive(),
            activity_executor_thread_alive=self._activity_executor_thread.is_alive(),
        )

    async def _handle_event(self, event: AgentEvent) -> ActionPlanGroup:
        self._trace_logger.write(
            "runtime_coordinator:handle_event:start",
            event_type=event.event_type.value,
            event_id=event.event_id,
            priority=event.priority,
            discardable=event.discardable,
            replace_key=event.replace_key,
        )
        if self._is_agent_state_only_event(event):
            self._agent_life_service.handle_event(event)
            self._trace_logger.write(
                "runtime_coordinator:handle_event:state_only",
                event_type=event.event_type.value,
                drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
                drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
                drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
                drive_energy=self._agent_life_service.agent_state.current_drive.energy,
            )
            return ActionPlanGroup()

        activity = self._activity_manager.handle_event(event)
        self._trace_logger.write(
            "runtime_coordinator:handle_event:activity_created",
            event_type=event.event_type.value,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
        )
        self._agent_life_service.handle_event(event)
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_updated",
            drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
            drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
            drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
            drive_energy=self._agent_life_service.agent_state.current_drive.energy,
        )
        action_plan_group = await self._action_planner.plan(activity)
        self._trace_logger.write(
            "runtime_coordinator:handle_event:actions_planned",
            activity_type=activity.activity_type.value,
            action_types=[
                action_plan.action_type.value
                for action_plan in action_plan_group.action_plans
            ],
        )
        self._trace_logger.write("runtime_coordinator:handle_event:actions_execute_start")
        await self._action_scheduler.execute(action_plan_group)
        self._trace_logger.write("runtime_coordinator:handle_event:actions_execute_finished")
        completed_activity = self._activity_manager.complete_foreground_activity()
        self._trace_logger.write(
            "runtime_coordinator:handle_event:foreground_activity_completed",
            completed=completed_activity is not None,
            activity_id=completed_activity.activity_id if completed_activity is not None else None,
            activity_type=completed_activity.activity_type.value if completed_activity is not None else None,
            activity_status=completed_activity.status.value if completed_activity is not None else None,
        )
        self._agent_life_service.sync_from_activity_manager()
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_synced_after_activity_complete",
            active_activity_exists=self._agent_life_service.agent_state.active_activity is not None,
            pending_activity_count=len(self._agent_life_service.agent_state.pending_activities),
            suspended_activity_count=len(self._agent_life_service.agent_state.suspended_activities),
        )
        return action_plan_group

    def _is_agent_state_only_event(self, event: AgentEvent) -> bool:
        return event.event_type in (
            AgentEventType.SPEECH_STARTED,
            AgentEventType.SPEECH_FINISHED,
        )
