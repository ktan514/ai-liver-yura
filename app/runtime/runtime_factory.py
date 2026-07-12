from __future__ import annotations

import os
from queue import Queue

from app.adapters.embedding.openai_embedding_generator import (
    OpenAIEmbeddingGenerator,
    OpenAIEmbeddingGeneratorConfig,
)
from app.adapters.llm import (
    DummyResponseGenerator,
    OllamaResponseGenerator,
    OpenAIResponseGenerator,
)
from app.adapters.memory.llm_memory_summary_generator import (
    LlmMemorySummaryGenerator,
    LlmMemorySummaryGeneratorConfig,
)
from app.adapters.memory.ollama_memory_summary_model import (
    OllamaMemorySummaryModel,
    OllamaMemorySummaryModelConfig,
)
from app.adapters.memory.openai_memory_summary_model import (
    OpenAIMemorySummaryModel,
    OpenAIMemorySummaryModelConfig,
)
from app.adapters.memory.simple_memory_summary_generator import (
    SimpleMemorySummaryGenerator,
    SimpleMemorySummaryGeneratorConfig,
)
from app.adapters.prompt import SimplePromptBuilder
from app.adapters.storage.postgres_topic_memory_store import (
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.adapters.topic.llm_topic_classifier import LlmTopicClassifier, TopicClassificationModel
from app.adapters.topic.ollama_topic_classification_model import (
    OllamaTopicClassificationConfig,
    OllamaTopicClassificationModel,
)
from app.adapters.topic.openai_topic_classification_model import (
    OpenAITopicClassificationConfig,
    OpenAITopicClassificationModel,
)
from app.config.app_config import AppConfig, ModelSettings, ServiceSettings
from app.domain.character import CharacterProfile
from app.domain.drives import DriveState
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.domain.topic_classifier import TopicClassifier
from app.ports.embedding_generator import EmbeddingGenerator
from app.ports.memory_summary_generator import MemorySummaryGenerator
from app.ports.memory_summary_model import MemorySummaryModel
from app.ports.topic_memory_store import TopicMemoryStore
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
    ActivityPlanningService,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.event_bus import EventBus
from app.runtime.event_queue import EventQueue
from app.runtime.planned_activity_queue import PlannedActivityQueue
from app.runtime.runtime_coordinator import RuntimeCoordinator
from app.usecases import ExecuteActionUsecase
from app.usecases.enrich_activity_with_topic_memory_usecase import (
    EnrichActivityWithTopicMemoryUsecase,
)
from app.utils.trace import TraceLogger


def _resolve_service(config: AppConfig, key: str) -> ServiceSettings:
    try:
        return config.services[key]
    except KeyError as error:
        raise RuntimeError(f"未定義のサービスです: {key}") from error


def _resolve_model(config: AppConfig, key: str) -> tuple[ModelSettings, ServiceSettings]:
    try:
        model = config.models[key]
    except KeyError as error:
        raise RuntimeError(f"未定義のモデルです: {key}") from error
    return model, _resolve_service(config, model.service)


def _require_service_value(value: str | None, field: str, service: str) -> str:
    if value is None:
        raise RuntimeError(f"services.{service}.{field} が必要です。")
    return value


def _service_timeout(service: ServiceSettings) -> float:
    if service.timeout_seconds is None:
        raise RuntimeError("外部AIサービスには timeout_seconds が必要です。")
    return service.timeout_seconds


def _embedding_dimension(config: AppConfig) -> int:
    model, _ = _resolve_model(config, config.memory.topic_memory.embedding_model)
    if model.dimension is None:
        raise RuntimeError(
            f"models.{config.memory.topic_memory.embedding_model}.dimension が必要です。"
        )
    return model.dimension


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
    response_generator: DummyResponseGenerator | OllamaResponseGenerator | OpenAIResponseGenerator
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

    if response_generator_config.type != "llm":
        trace_logger.write(
            "runtime_factory:create_response_generator:error",
            reason="unsupported_response_generator_type",
            response_generator_type=response_generator_config.type,
        )
        raise RuntimeError(
            f"未対応の response_generator.type です: {response_generator_config.type}"
        )

    model_config, service_config = _resolve_model(config, response_generator_config.model)
    if service_config.type == "ollama":
        base_url = _require_service_value(service_config.base_url, "base_url", model_config.service)
        response_generator = OllamaResponseGenerator(
            character_profile=character_profile,
            prompt_builder=prompt_builder,
            model=model_config.name,
            api_url=f"{base_url.rstrip('/')}/api/generate",
            timeout_seconds=_service_timeout(service_config),
            fallback_response=response_generator_config.fallback_response,
        )
        trace_logger.write(
            "runtime_factory:create_response_generator:finished",
            response_generator_type="llm",
            provider=service_config.type,
            response_generator_class=type(response_generator).__name__,
            model=model_config.name,
        )
        return response_generator

    if service_config.type == "openai":
        response_generator = OpenAIResponseGenerator(
            model=model_config.name,
            api_key_env=_require_service_value(
                service_config.api_key_env, "api_key_env", model_config.service
            ),
            base_url=_require_service_value(
                service_config.base_url, "base_url", model_config.service
            ),
            timeout_seconds=_service_timeout(service_config),
            fallback_response=response_generator_config.fallback_response,
            character_profile=character_profile,
            prompt_builder=prompt_builder,
        )
        trace_logger.write(
            "runtime_factory:create_response_generator:finished",
            response_generator_type="llm",
            provider=service_config.type,
            response_generator_class=type(response_generator).__name__,
            model=model_config.name,
            api_key_env=service_config.api_key_env,
        )
        return response_generator

    trace_logger.write(
        "runtime_factory:create_response_generator:error",
        reason="unsupported_model_service_type",
        service_type=service_config.type,
    )
    raise RuntimeError(f"未対応のモデルサービスです: {service_config.type}")


def create_topic_classifier(config: AppConfig) -> TopicClassifier | None:
    model: TopicClassificationModel
    classifier_config = config.topic_classifier
    trace_logger = TraceLogger()
    trace_logger.write(
        "runtime_factory:create_topic_classifier:start",
        model_key=classifier_config.model,
    )

    if config.response_generator.type == "dummy":
        trace_logger.write(
            "runtime_factory:create_topic_classifier:skipped",
            reason="dummy_response_generator",
        )
        return None

    model_config, service_config = _resolve_model(config, classifier_config.model)
    if service_config.type == "ollama":
        model = OllamaTopicClassificationModel(
            OllamaTopicClassificationConfig(
                model=model_config.name,
                base_url=_require_service_value(
                    service_config.base_url, "base_url", model_config.service
                ),
                timeout_seconds=_service_timeout(service_config),
            )
        )
        topic_classifier = LlmTopicClassifier(model=model)
        trace_logger.write(
            "runtime_factory:create_topic_classifier:finished",
            provider=service_config.type,
            topic_classifier_class=type(topic_classifier).__name__,
            topic_classification_model_class=type(model).__name__,
            model=model_config.name,
        )
        return topic_classifier

    if service_config.type == "openai":
        api_key_env = _require_service_value(
            service_config.api_key_env, "api_key_env", model_config.service
        )
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            trace_logger.write(
                "runtime_factory:create_topic_classifier:skipped",
                reason="openai_api_key_not_set",
                api_key_env=api_key_env,
            )
            return None

        model = OpenAITopicClassificationModel(
            OpenAITopicClassificationConfig(
                api_key=api_key,
                model=model_config.name,
                base_url=_require_service_value(
                    service_config.base_url, "base_url", model_config.service
                ),
                timeout_seconds=_service_timeout(service_config),
            )
        )
        topic_classifier = LlmTopicClassifier(model=model)
        trace_logger.write(
            "runtime_factory:create_topic_classifier:finished",
            provider=service_config.type,
            topic_classifier_class=type(topic_classifier).__name__,
            topic_classification_model_class=type(model).__name__,
            model=model_config.name,
            api_key_env=api_key_env,
        )
        return topic_classifier

    trace_logger.write(
        "runtime_factory:create_topic_classifier:skipped",
        reason="unsupported_response_generator_type",
        service_type=service_config.type,
    )
    return None


# --- embedding generator factory ---
def create_embedding_generator(config: AppConfig) -> EmbeddingGenerator | None:
    topic_memory_config = config.memory.topic_memory
    trace_logger = TraceLogger()
    trace_logger.write(
        "runtime_factory:create_embedding_generator:start",
        enabled=topic_memory_config.enabled,
        embedding_model=topic_memory_config.embedding_model,
    )

    if not topic_memory_config.enabled:
        trace_logger.write(
            "runtime_factory:create_embedding_generator:skipped",
            reason="topic_memory_disabled",
        )
        return None

    model_config, service_config = _resolve_model(config, topic_memory_config.embedding_model)
    if service_config.type != "openai":
        trace_logger.write(
            "runtime_factory:create_embedding_generator:skipped",
            reason="unsupported_embedding_type",
            service_type=service_config.type,
        )
        return None

    api_key_env = _require_service_value(
        service_config.api_key_env, "api_key_env", model_config.service
    )
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        trace_logger.write(
            "runtime_factory:create_embedding_generator:skipped",
            reason="openai_api_key_not_set",
            api_key_env=api_key_env,
        )
        return None

    embedding_generator = OpenAIEmbeddingGenerator(
        OpenAIEmbeddingGeneratorConfig(
            api_key=api_key,
            model=model_config.name,
            base_url=_require_service_value(
                service_config.base_url, "base_url", model_config.service
            ),
            timeout_seconds=_service_timeout(service_config),
        )
    )
    trace_logger.write(
        "runtime_factory:create_embedding_generator:finished",
        embedding_generator_class=type(embedding_generator).__name__,
        model=model_config.name,
        dimension=model_config.dimension,
        api_key_env=api_key_env,
    )
    return embedding_generator


def create_topic_memory_store(config: AppConfig) -> TopicMemoryStore | None:
    topic_memory_config = config.memory.topic_memory
    trace_logger = TraceLogger()
    trace_logger.write(
        "runtime_factory:create_topic_memory_store:start",
        enabled=topic_memory_config.enabled,
        database_service=topic_memory_config.database_service,
    )

    if not topic_memory_config.enabled:
        trace_logger.write(
            "runtime_factory:create_topic_memory_store:skipped",
            reason="topic_memory_disabled",
        )
        return None

    database_config = _resolve_service(config, topic_memory_config.database_service)
    if database_config.type != "postgres":
        trace_logger.write(
            "runtime_factory:create_topic_memory_store:skipped",
            reason="unsupported_database_type",
            database_type=database_config.type,
        )
        return None

    dsn_env = _require_service_value(
        database_config.dsn_env, "dsn_env", topic_memory_config.database_service
    )
    dsn = os.environ.get(dsn_env, "")
    if not dsn:
        trace_logger.write(
            "runtime_factory:create_topic_memory_store:skipped",
            reason="database_dsn_not_set",
            dsn_env=dsn_env,
        )
        return None

    topic_memory_store = PostgresTopicMemoryStore(
        PostgresTopicMemoryStoreConfig(
            dsn=dsn,
            embedding_dimension=_embedding_dimension(config),
        )
    )
    trace_logger.write(
        "runtime_factory:create_topic_memory_store:finished",
        topic_memory_store_class=type(topic_memory_store).__name__,
        database_type=database_config.type,
        dsn_env=dsn_env,
        embedding_dimension=_embedding_dimension(config),
    )
    return topic_memory_store


# --- memory summary generator factory ---
def create_memory_summary_generator(config: AppConfig) -> MemorySummaryGenerator | None:
    memory_summary_generator: MemorySummaryGenerator
    topic_memory_config = config.memory.topic_memory
    trace_logger = TraceLogger()
    trace_logger.write(
        "runtime_factory:create_memory_summary_generator:start",
        enabled=topic_memory_config.enabled,
        summary_type=topic_memory_config.summary.type,
    )

    if not topic_memory_config.enabled:
        trace_logger.write(
            "runtime_factory:create_memory_summary_generator:skipped",
            reason="topic_memory_disabled",
        )
        return None

    summary_config = topic_memory_config.summary
    if summary_config.type == "simple":
        memory_summary_generator = SimpleMemorySummaryGenerator(
            SimpleMemorySummaryGeneratorConfig(max_length=summary_config.fallback_max_length)
        )
        trace_logger.write(
            "runtime_factory:create_memory_summary_generator:finished",
            memory_summary_generator_class=type(memory_summary_generator).__name__,
            summary_type=summary_config.type,
            fallback_max_length=summary_config.fallback_max_length,
        )
        return memory_summary_generator

    if summary_config.type == "llm":
        model: MemorySummaryModel
        model_config, service_config = _resolve_model(config, summary_config.model)
        model_name: str

        if service_config.type == "ollama":
            model = OllamaMemorySummaryModel(
                OllamaMemorySummaryModelConfig(
                    base_url=_require_service_value(
                        service_config.base_url, "base_url", model_config.service
                    ),
                    model=model_config.name,
                    timeout_seconds=_service_timeout(service_config),
                )
            )
            model_name = model_config.name
        elif service_config.type == "openai":
            api_key_env = _require_service_value(
                service_config.api_key_env, "api_key_env", model_config.service
            )
            api_key = os.environ.get(api_key_env, "")
            if not api_key:
                trace_logger.write(
                    "runtime_factory:create_memory_summary_generator:skipped",
                    reason="openai_api_key_not_set",
                    api_key_env=api_key_env,
                )
                return None

            model = OpenAIMemorySummaryModel(
                OpenAIMemorySummaryModelConfig(
                    api_key=api_key,
                    model=model_config.name,
                    base_url=_require_service_value(
                        service_config.base_url, "base_url", model_config.service
                    ),
                    timeout_seconds=_service_timeout(service_config),
                )
            )
            model_name = model_config.name
        else:
            trace_logger.write(
                "runtime_factory:create_memory_summary_generator:skipped",
                reason="unsupported_memory_summary_llm_provider",
                summary_type=summary_config.type,
                service_type=service_config.type,
            )
            return None

        memory_summary_generator = LlmMemorySummaryGenerator(
            model=model,
            config=LlmMemorySummaryGeneratorConfig(
                fallback_max_length=summary_config.fallback_max_length,
            ),
        )
        trace_logger.write(
            "runtime_factory:create_memory_summary_generator:finished",
            memory_summary_generator_class=type(memory_summary_generator).__name__,
            memory_summary_model_class=type(model).__name__,
            summary_type=summary_config.type,
            model=model_name,
            fallback_max_length=summary_config.fallback_max_length,
        )
        return memory_summary_generator

    trace_logger.write(
        "runtime_factory:create_memory_summary_generator:skipped",
        reason="unsupported_memory_summary_type",
        summary_type=summary_config.type,
    )
    return None


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
    topic_history = TopicHistory()
    prompt_builder = SimplePromptBuilder(
        short_term_memory=short_term_memory,
        topic_history=topic_history,
    )
    response_generator = create_response_generator(
        config=config,
        character_profile=character_profile,
        prompt_builder=prompt_builder,
    )
    topic_classifier = create_topic_classifier(config)
    embedding_generator = create_embedding_generator(config)
    topic_memory_store = create_topic_memory_store(config)
    memory_summary_generator = create_memory_summary_generator(config)
    enrich_activity_with_topic_memory_usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )
    action_planner = ActionPlanner(response_generator=response_generator)
    execute_action_usecase = ExecuteActionUsecase(
        event_publisher=event_bus,
        short_term_memory=short_term_memory,
        topic_history=topic_history,
        topic_classifier=topic_classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
        memory_summary_generator=memory_summary_generator,
    )

    planned_activity_queue = PlannedActivityQueue()
    activity_planning_request_queue: Queue[ActivityPlanningRequest] = Queue()
    activity_planning_service = ActivityPlanningService(
        agent_life_service=agent_life_service,
        activity_manager=activity_manager,
        enrich_activity_with_topic_memory_usecase=enrich_activity_with_topic_memory_usecase,
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
        topic_history_class=type(topic_history).__name__,
        topic_classifier_class=type(topic_classifier).__name__
        if topic_classifier is not None
        else None,
        embedding_generator_class=type(embedding_generator).__name__
        if embedding_generator is not None
        else None,
        topic_memory_store_class=type(topic_memory_store).__name__
        if topic_memory_store is not None
        else None,
        memory_summary_generator_class=type(memory_summary_generator).__name__
        if memory_summary_generator is not None
        else None,
        enrich_activity_with_topic_memory_usecase_class=type(
            enrich_activity_with_topic_memory_usecase
        ).__name__,
        activity_planner_thread_class=type(activity_planner_thread).__name__,
        activity_executor_thread_class=type(activity_executor_thread).__name__,
    )
    return runtime_coordinator
