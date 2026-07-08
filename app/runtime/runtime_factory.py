from __future__ import annotations
from queue import Queue

from app.adapters.llm import (
    DummyResponseGenerator,
    OllamaResponseGenerator,
    OpenAIResponseGenerator,
)
from app.adapters.prompt import SimplePromptBuilder
from app.config.app_config import AppConfig
from app.common.trace import TraceLogger
from app.domain.character import CharacterProfile
from app.domain.drives import DriveState
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
    ActivityPlanningService,
)
from app.runtime.action_planner import ActionPlanner
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.event_bus import EventBus
from app.runtime.event_queue import EventQueue
from app.runtime.planned_activity_queue import PlannedActivityQueue
from app.runtime.runtime_coordinator import RuntimeCoordinator
from app.runtime.short_term_memory import ShortTermMemory
from app.usecases import ExecuteActionUsecase


def create_character_profile(config: AppConfig) -> CharacterProfile:
    character_config = config.character
    character_profile = CharacterProfile(
        name=character_config.name,
        personality=character_config.personality,
        speaking_style=character_config.speaking_style,
        streaming_style=character_config.streaming_style,
        likes=character_config.likes,
        dislikes=character_config.dislikes,
        behavior_policy=character_config.behavior_policy,
    )
    return character_profile


def create_response_generator(
    config: AppConfig,
    character_profile: CharacterProfile,
    prompt_builder: SimplePromptBuilder,
) -> DummyResponseGenerator | OllamaResponseGenerator | OpenAIResponseGenerator:
    response_generator_config = config.response_generator
    trace_logger = TraceLogger()
    trace_logger.write(
        "runtime_factory:create_response_generator:start",
        response_generator_type=response_generator_config.type,
    )

    if response_generator_config.type == "dummy":
        response_generator = DummyResponseGenerator(
            character_profile=character_profile,
            prompt_builder=prompt_builder,
        )
        trace_logger.write(
            "runtime_factory:create_response_generator:finished",
            response_generator_type="dummy",
            response_generator_class=type(response_generator).__name__,
        )
        return response_generator

    if response_generator_config.type == "ollama":
        ollama_config = response_generator_config.ollama
        response_generator = OllamaResponseGenerator(
            character_profile=character_profile,
            prompt_builder=prompt_builder,
            model=ollama_config.model,
            api_url=ollama_config.api_url,
            timeout_seconds=ollama_config.timeout_seconds,
            fallback_response=ollama_config.fallback_response,
        )
        trace_logger.write(
            "runtime_factory:create_response_generator:finished",
            response_generator_type="ollama",
            response_generator_class=type(response_generator).__name__,
            model=ollama_config.model,
        )
        return response_generator

    if response_generator_config.type == "openai":
        openai_config = response_generator_config.openai
        response_generator = OpenAIResponseGenerator(
            model=openai_config.model,
            api_key_env=openai_config.api_key_env,
            timeout_seconds=openai_config.timeout_seconds,
            fallback_response=openai_config.fallback_response,
            character_profile=character_profile,
            prompt_builder=prompt_builder,
        )
        trace_logger.write(
            "runtime_factory:create_response_generator:finished",
            response_generator_type="openai",
            response_generator_class=type(response_generator).__name__,
            model=openai_config.model,
            api_key_env=openai_config.api_key_env,
        )
        return response_generator

    trace_logger.write(
        "runtime_factory:create_response_generator:error",
        reason="unsupported_response_generator_type",
        response_generator_type=response_generator_config.type,
    )
    raise RuntimeError(f"未対応の response_generator.type です: {response_generator_config.type}")


def create_runtime_coordinator(config: AppConfig) -> RuntimeCoordinator:
    trace_logger = TraceLogger()
    trace_logger.write(
        "runtime_factory:create_runtime_coordinator:start",
        app_name=config.app.name,
        app_mode=config.app.mode,
        response_generator_type=config.response_generator.type,
    )
    event_queue = EventQueue()
    event_bus = EventBus(event_queue)
    activity_manager = ActivityManager()
    agent_life_service = AgentLifeService(activity_manager)
    agent_life_service.update_drive(
        DriveState(
            curiosity=0.72,
            engagement=0.6,
            boredom=0.2,
            energy=0.8,
        )
    )
    character_profile = create_character_profile(config)
    short_term_memory = ShortTermMemory()
    prompt_builder = SimplePromptBuilder(short_term_memory=short_term_memory)
    response_generator = create_response_generator(
        config=config,
        character_profile=character_profile,
        prompt_builder=prompt_builder,
    )
    action_planner = ActionPlanner(response_generator=response_generator)
    execute_action_usecase = ExecuteActionUsecase(
        event_publisher=event_bus,
        short_term_memory=short_term_memory,
    )

    planned_activity_queue = PlannedActivityQueue()
    activity_planning_request_queue: Queue[ActivityPlanningRequest] = Queue()
    activity_planning_service = ActivityPlanningService(
        agent_life_service=agent_life_service,
        activity_manager=activity_manager,
    )
    activity_planner_thread = ActivityPlannerThread(
        request_queue=activity_planning_request_queue,
        planned_activity_queue=planned_activity_queue,
        planning_service=activity_planning_service,
    )
    action_scheduler = ActionScheduler(action_executor=execute_action_usecase)
    activity_executor_thread = ActivityExecutorThread(
        planned_activity_queue=planned_activity_queue,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
    )

    runtime_coordinator = RuntimeCoordinator(
        event_queue=event_queue,
        activity_manager=activity_manager,
        agent_life_service=agent_life_service,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        activity_planning_request_queue=activity_planning_request_queue,
        activity_planner_thread=activity_planner_thread,
        activity_executor_thread=activity_executor_thread,
    )
    trace_logger.write(
        "runtime_factory:create_runtime_coordinator:finished",
        runtime_coordinator_class=type(runtime_coordinator).__name__,
        response_generator_type=config.response_generator.type,
        response_generator_class=type(response_generator).__name__,
        activity_planner_thread_class=type(activity_planner_thread).__name__,
        activity_executor_thread_class=type(activity_executor_thread).__name__,
    )
    return runtime_coordinator