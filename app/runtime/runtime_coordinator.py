from __future__ import annotations

import asyncio

from app.domain.actions import ActionPlanGroup
from app.domain.events import AgentEvent
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_filter import DefaultEventFilter, EventFilter
from app.runtime.event_prioritizer import DefaultEventPrioritizer, EventPrioritizer
from app.runtime.event_queue import EventQueue
from app.usecases.execute_action_usecase import ExecuteActionUsecase


class RuntimeCoordinator:
    """EventQueue → ActivityManager → ActionPlanner → Executor をつなぐ中核。"""

    def __init__(
        self,
        event_queue: EventQueue,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_executor: ExecuteActionUsecase,
        event_filter: EventFilter | None = None,
        event_prioritizer: EventPrioritizer | None = None,
        event_buffer: EventBuffer | None = None,
    ) -> None:
        self._event_queue = event_queue
        self._activity_manager = activity_manager
        self._action_planner = action_planner
        self._action_executor = action_executor
        self._action_scheduler = ActionScheduler(action_executor.execute)
        self._event_filter = event_filter or DefaultEventFilter()
        self._event_prioritizer = event_prioritizer or DefaultEventPrioritizer()
        self._event_buffer = event_buffer or EventBuffer()
        self._running = False

    async def publish_event(self, event: AgentEvent) -> None:
        await self.publish_events([event])

    async def publish_events(self, events: list[AgentEvent]) -> None:
        for event in events:
            filtered_event = self._event_filter.filter(event)
            if filtered_event is None:
                continue

            prioritized_event = self._event_prioritizer.prioritize(filtered_event)
            self._event_buffer.put(prioritized_event)

        for buffered_event in self._event_buffer.drain():
            await self._event_queue.put(buffered_event)

    async def run_once(self) -> ActionPlanGroup | None:
        if self._event_queue.empty():
            return None

        event = await self._event_queue.get()
        return await self._handle_event(event)

    async def run(self) -> None:
        self._running = True

        while self._running:
            action_plan_group = await self.run_once()
            if action_plan_group is None:
                await asyncio.sleep(0.01)

    def stop(self) -> None:
        self._running = False

    async def _handle_event(self, event: AgentEvent) -> ActionPlanGroup:
        activity = self._activity_manager.handle_event(event)
        action_plan_group = await self._action_planner.plan(activity)
        await self._action_scheduler.execute(action_plan_group)
        return action_plan_group
