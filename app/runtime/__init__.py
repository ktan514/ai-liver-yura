from typing import TYPE_CHECKING

from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_bus import EventBus
from app.runtime.event_filter import DefaultEventFilter, EventFilter
from app.runtime.event_prioritizer import DefaultEventPrioritizer, EventPrioritizer
from app.runtime.event_queue import EventQueue
from app.runtime.input_receiver import EventPublisher, InputReceiver
from app.runtime.runtime_coordinator import RuntimeCoordinator

if TYPE_CHECKING:
    from app.config.app_config import AppConfig


def create_runtime_coordinator(config: "AppConfig") -> RuntimeCoordinator:
    """Factoryを遅延importし、Plugin内部実装との循環importを避ける。"""

    from app.runtime.runtime_factory import create_runtime_coordinator as create

    return create(config)


__all__ = [
    "ActionPlanner",
    "ActionScheduler",
    "ActivityManager",
    "DefaultEventFilter",
    "DefaultEventPrioritizer",
    "EventBuffer",
    "EventBus",
    "EventFilter",
    "EventPrioritizer",
    "EventPublisher",
    "EventQueue",
    "InputReceiver",
    "RuntimeCoordinator",
    "create_runtime_coordinator",
    "AgentState",
    "AgentLifeService",
]
