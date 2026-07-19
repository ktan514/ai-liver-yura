from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, cast

from app.adapters.embedding.openai_embedding_generator import (
    OpenAIEmbeddingGenerator,
    OpenAIEmbeddingGeneratorConfig,
)
from app.adapters.llm import (
    DummyResponseGenerator,
    LegacyCharacterModelAdapter,
    OllamaResponseGenerator,
    OpenAIResponseGenerator,
    StreamingDemoResponseGenerator,
)
from app.adapters.memory import (
    LlmMemorySummaryGenerator,
    LlmMemorySummaryGeneratorConfig,
    OllamaMemorySummaryModel,
    OllamaMemorySummaryModelConfig,
    OpenAIMemorySummaryModel,
    OpenAIMemorySummaryModelConfig,
    SimpleMemorySummaryGenerator,
    SimpleMemorySummaryGeneratorConfig,
)
from app.adapters.prompt import (
    CharacterPromptBuilder,
    ResponseValidatorPromptBuilder,
    SimplePromptBuilder,
    SituationEvaluatorPromptBuilder,
)
from app.adapters.storage.json_agent_memory_store import JsonAgentMemoryStore
from app.adapters.storage.json_relationship_memory_store import (
    JsonRelationshipMemoryStore,
)
from app.adapters.storage.postgres_topic_memory_store import (
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.adapters.topic import (
    LlmTopicClassifier,
    OllamaTopicClassificationConfig,
    OllamaTopicClassificationModel,
    OpenAITopicClassificationConfig,
    OpenAITopicClassificationModel,
    TopicClassificationModel,
)
from app.adapters.tts import (
    NoOpAudioQueryCorrector,
    PronunciationCorrector,
    PronunciationDictionary,
    SystemAudioPlayer,
    VoiceVoxSpeechProfile,
    VoiceVoxSpeechSynthesizer,
    VoiceVoxSpeechSynthesizerConfig,
)
from app.config.app_config import (
    AppConfig,
    LlmRoleSettings,
    ModelSettings,
    ResponseGeneratorSettings,
    ServiceSettings,
)
from app.core.plugins import PluginManager
from app.domain.activities import Activity, ActivityStatus, ActivityType
from app.domain.character import CharacterProfile
from app.domain.drives import DriveState
from app.domain.memory import AgentMemoryState
from app.domain.relationships import RelationshipMemory
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.domain.topic_classifier import TopicClassifier
from app.plugins.agent_memory import AgentMemoryPlugin
from app.plugins.games import GamesPlugin
from app.plugins.llm_provider import LlmProviderPlugin
from app.plugins.relationship_memory import RelationshipMemoryPlugin
from app.plugins.voice_output import VoiceOutputPlugin
from app.ports.audio_player import AudioPlayer
from app.ports.embedding_generator import EmbeddingGenerator
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.ports.memory_summary_generator import MemorySummaryGenerator
from app.ports.memory_summary_model import MemorySummaryModel
from app.ports.relationship_memory_store import RelationshipMemoryStore
from app.ports.response_generator import ResponseGenerator
from app.ports.speech_synthesizer import SpeechSynthesizer
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
from app.runtime.activity_registry import ActivityRegistry
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner
from app.runtime.character_response_pipeline import (
    CharacterLlmService,
    CharacterResponsePipeline,
    ResponseContextBuilder,
    ResponseValidator,
)
from app.runtime.event_bus import EventBus
from app.runtime.event_queue import EventQueue
from app.runtime.pending_confirmation import (
    ConfirmationResolver,
    PendingConfirmationManager,
)
from app.runtime.planned_activity_queue import PlannedActivityQueue
from app.runtime.runtime_coordinator import RuntimeCoordinator
from app.runtime.situation_evaluator import SituationEvaluator
from app.shared.contracts.memory import AgentMemoryStore
from app.shared.contracts.plugins.runtime import (
    PluginActivityWorkItem,
    PluginContext,
    PluginLlmRequest,
    SystemClock,
)
from app.usecases import ExecuteActionUsecase
from app.usecases.enrich_activity_with_topic_memory_usecase import (
    EnrichActivityWithTopicMemoryUsecase,
)
from app.utils.trace import TraceLogger

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.adapters.streaming import (
        InMemoryStreamMainSegmentRepository,
        InMemoryStreamOpeningRepository,
        InMemoryStreamPreparationPublisher,
        InMemoryStreamSessionRepository,
    )
    from app.core.plugins import CapabilityRegistry
    from app.plugins.youtube_streaming.application import (
        PrepareStreamSessionUsecase,
        StartStreamSessionUsecase,
    )
    from app.ports.streaming_control import (
        ObsStreamingControlPort,
        YouTubeStreamingControlPort,
    )
    from app.ports.streaming_preparation import RunOfShowRepository
    from app.ports.youtube_live_chat import YouTubeLiveChatReadPort


@dataclass(frozen=True, slots=True)
class StreamPreparationRuntime:
    config: AppConfig
    usecase: PrepareStreamSessionUsecase
    sessions: InMemoryStreamSessionRepository
    publisher: InMemoryStreamPreparationPublisher
    capability_registry: CapabilityRegistry
    start_usecase: StartStreamSessionUsecase
    openings: InMemoryStreamOpeningRepository
    main_segments: InMemoryStreamMainSegmentRepository
    run_of_show: RunOfShowRepository
    obs_control: ObsStreamingControlPort
    youtube_control: YouTubeStreamingControlPort
    live_chat: YouTubeLiveChatReadPort


def _resolve_service(config: AppConfig, key: str) -> ServiceSettings:
    try:
        return config.services[key]
    except KeyError as error:
        raise RuntimeError(f"未定義のサービスです: {key}") from error


def _resolve_model(
    config: AppConfig, key: str
) -> tuple[ModelSettings, ServiceSettings]:
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


def create_streaming_demo_config(config: AppConfig) -> AppConfig:
    """Return an explicit, external-I/O-free composition preset."""
    services = dict(config.services)
    services["youtube"] = replace(services["youtube"], type="fake")
    services["obs"] = replace(services["obs"], type="fake")
    return replace(
        config,
        app=replace(config.app, mode="streaming_demo"),
        services=services,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
        streaming=replace(
            config.streaming,
            fake=replace(
                config.streaming.fake,
                broadcast_id="demo-broadcast",
                broadcast_title="ゆら ローカル配信テスト",
            ),
        ),
    )


def _embedding_dimension(config: AppConfig) -> int:
    model, _ = _resolve_model(config, config.memory.topic_memory.embedding_model)
    if model.dimension is None:
        raise RuntimeError(
            f"models.{config.memory.topic_memory.embedding_model}.dimension が必要です。"
        )
    return model.dimension


def create_speech_synthesizer(config: AppConfig) -> SpeechSynthesizer | None:
    if not config.speech.enabled:
        return None
    service = _resolve_service(config, config.speech.service)
    if service.type != "voicevox":
        raise RuntimeError(f"未対応の音声合成サービスです: {service.type}")
    pronunciation_dictionary = PronunciationDictionary.load(
        config.speech.pronunciation_dictionary_path
    )
    return VoiceVoxSpeechSynthesizer(
        VoiceVoxSpeechSynthesizerConfig(
            base_url=_require_service_value(
                service.base_url, "base_url", config.speech.service
            ),
            speaker_id=config.speech.speaker_id,
            timeout_seconds=_service_timeout(service),
            default_profile=config.speech.default_profile,
            voice_intent_profiles={
                name: VoiceVoxSpeechProfile(
                    speed_scale=profile.speed_scale,
                    pitch_scale=profile.pitch_scale,
                    intonation_scale=profile.intonation_scale,
                    volume_scale=profile.volume_scale,
                )
                for name, profile in config.speech.voice_intent_profiles.items()
            },
        ),
        pronunciation_corrector=PronunciationCorrector(pronunciation_dictionary),
        audio_query_corrector=NoOpAudioQueryCorrector(),
    )


def create_audio_player(config: AppConfig) -> AudioPlayer | None:
    if not config.speech.enabled:
        return None
    if config.speech.player.type != "system":
        raise RuntimeError(f"未対応の音声再生方式です: {config.speech.player.type}")
    return SystemAudioPlayer(command=config.speech.player.command)


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
    *,
    temperature: float | None = None,
) -> (
    DummyResponseGenerator
    | StreamingDemoResponseGenerator
    | OllamaResponseGenerator
    | OpenAIResponseGenerator
):
    response_generator: (
        DummyResponseGenerator
        | StreamingDemoResponseGenerator
        | OllamaResponseGenerator
        | OpenAIResponseGenerator
    )
    response_generator_config = config.response_generator
    trace_logger = TraceLogger()
    trace_logger.write(
        "runtime_factory:create_response_generator:start",
        response_generator_type=response_generator_config.type,
    )

    if config.app.mode == "streaming_demo":
        return StreamingDemoResponseGenerator()

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

    model_config, service_config = _resolve_model(
        config, response_generator_config.model
    )
    if service_config.type == "ollama":
        base_url = _require_service_value(
            service_config.base_url, "base_url", model_config.service
        )
        response_generator = OllamaResponseGenerator(
            character_profile=character_profile,
            prompt_builder=prompt_builder,
            model=model_config.name,
            api_url=f"{base_url.rstrip('/')}/api/generate",
            timeout_seconds=_service_timeout(service_config),
            fallback_response=response_generator_config.fallback_response,
            temperature=temperature,
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
            temperature=temperature,
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


def create_llm_role_generator(
    config: AppConfig,
    settings: LlmRoleSettings,
    character_profile: CharacterProfile,
    prompt_builder: SimplePromptBuilder,
) -> (
    DummyResponseGenerator
    | StreamingDemoResponseGenerator
    | OllamaResponseGenerator
    | OpenAIResponseGenerator
):
    """役割ごとに独立したAdapterを生成する。旧設定への暗黙フォールバックはしない。"""

    model, service = _resolve_model(config, settings.model)
    services = dict(config.services)
    services[model.service] = replace(service, timeout_seconds=settings.timeout_seconds)
    role_config = replace(
        config,
        services=services,
        response_generator=ResponseGeneratorSettings(
            type=config.response_generator.type,
            model=settings.model,
            fallback_response=settings.fallback_response,
        ),
    )
    return create_response_generator(
        config=role_config,
        character_profile=character_profile,
        prompt_builder=prompt_builder,
        temperature=settings.temperature,
    )


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

    model_config, service_config = _resolve_model(
        config, topic_memory_config.embedding_model
    )
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


def create_relationship_memory_store(
    config: AppConfig,
) -> RelationshipMemoryStore | None:
    settings = config.memory.relationship_memory
    trace_logger = TraceLogger()
    if not settings.enabled:
        trace_logger.write(
            "runtime_factory:create_relationship_memory_store:skipped",
            reason="relationship_memory_disabled",
        )
        return None
    path = Path(settings.path)
    if not path.is_absolute():
        config_path = Path(config.config_path)
        project_root = (
            config_path.parent.parent
            if config_path.parent.name == "config"
            else config_path.parent
        )
        path = project_root / path
    store = JsonRelationshipMemoryStore(path, max_entries=settings.max_entries)
    trace_logger.write(
        "runtime_factory:create_relationship_memory_store:finished",
        store_class=type(store).__name__,
        max_entries=settings.max_entries,
    )
    return store


def load_relationship_memory(
    store: RelationshipMemoryStore | None,
    *,
    max_entries: int,
) -> RelationshipMemory:
    if store is None:
        return RelationshipMemory(max_entries=max_entries)
    try:
        return store.load()
    except Exception as error:
        TraceLogger().error(
            "runtime_factory:load_relationship_memory:failed",
            error_type=type(error).__name__,
        )
        return RelationshipMemory(max_entries=max_entries)


def create_agent_memory_store(config: AppConfig) -> AgentMemoryStore | None:
    settings = config.memory.agent_memory
    if not settings.enabled:
        return None
    path = Path(settings.path)
    if not path.is_absolute():
        config_path = Path(config.config_path)
        project_root = (
            config_path.parent.parent
            if config_path.parent.name == "config"
            else config_path.parent
        )
        path = project_root / path
    return JsonAgentMemoryStore(path)


def load_agent_memory(
    store: AgentMemoryStore | None,
    *,
    max_history_entries: int,
) -> AgentMemoryState:
    if store is None:
        return AgentMemoryState(max_history_entries=max_history_entries)
    try:
        return AgentMemoryState.from_snapshot(
            store.load(), max_history_entries=max_history_entries
        )
    except Exception as error:
        TraceLogger().error(
            "runtime_factory:load_agent_memory:failed",
            error_type=type(error).__name__,
        )
        return AgentMemoryState(max_history_entries=max_history_entries)


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
            SimpleMemorySummaryGeneratorConfig(
                max_length=summary_config.fallback_max_length
            )
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
    pending_confirmation_manager = PendingConfirmationManager(
        timeout_seconds=config.confirmation.timeout_seconds,
        max_attempts=config.confirmation.max_attempts,
    )
    short_term_memory = ShortTermMemory()
    topic_history = TopicHistory()
    raw_relationship_memory_store = create_relationship_memory_store(config)
    raw_agent_memory_store = create_agent_memory_store(config)
    character_profile = create_character_profile(config)
    prompt_builder = SimplePromptBuilder(
        short_term_memory=short_term_memory,
        topic_history=topic_history,
    )
    raw_response_generator = create_response_generator(
        config=config,
        character_profile=character_profile,
        prompt_builder=prompt_builder,
    )
    raw_situation_generator: ResponseGenerator = raw_response_generator
    raw_character_generator: ResponseGenerator | None = None
    raw_validator_generator: ResponseGenerator | None = None
    if config.response_generator.type != "dummy":
        raw_situation_generator = create_llm_role_generator(
            config,
            config.llm_roles.situation_evaluator,
            character_profile,
            prompt_builder,
        )
        raw_character_generator = create_llm_role_generator(
            config,
            config.llm_roles.character,
            character_profile,
            prompt_builder,
        )
        raw_validator_generator = create_llm_role_generator(
            config,
            config.llm_roles.response_validator,
            character_profile,
            prompt_builder,
        )
    speech_synthesizer: SpeechSynthesizer | None
    audio_player: AudioPlayer | None
    if config.app.mode == "streaming_demo":
        from app.adapters.streaming.fake_output_adapters import (
            FakeAudioPlayer,
            FakeSpeechSynthesizer,
        )

        speech_synthesizer = FakeSpeechSynthesizer()
        audio_player = FakeAudioPlayer()
    else:
        speech_synthesizer = create_speech_synthesizer(config)
        audio_player = create_audio_player(config)

    default_llm_available = config.response_generator.type == "dummy" or (
        _is_model_provider_available(config, config.response_generator.model)
    )
    default_llm_plugin = LlmProviderPlugin(
        "default",
        raw_response_generator,
        configured_available=default_llm_available,
    )
    situation_llm_plugin = LlmProviderPlugin(
        "situation_evaluator",
        raw_situation_generator,
        configured_available=(
            config.response_generator.type == "dummy"
            or _is_model_provider_available(
                config, config.llm_roles.situation_evaluator.model
            )
        ),
    )
    character_llm_plugin: LlmProviderPlugin | None = None
    validator_llm_plugin: LlmProviderPlugin | None = None
    if raw_character_generator is not None and raw_validator_generator is not None:
        character_llm_plugin = LlmProviderPlugin(
            "character",
            raw_character_generator,
            configured_available=_is_model_provider_available(
                config, config.llm_roles.character.model
            ),
        )
        validator_llm_plugin = LlmProviderPlugin(
            "response_validator",
            raw_validator_generator,
            configured_available=_is_model_provider_available(
                config, config.llm_roles.response_validator.model
            ),
        )

    plugin_manager = PluginManager()
    plugin_manager.register(default_llm_plugin)
    plugin_manager.register(situation_llm_plugin)
    if character_llm_plugin is not None and validator_llm_plugin is not None:
        plugin_manager.register(character_llm_plugin)
        plugin_manager.register(validator_llm_plugin)
    plugin_manager.register(GamesPlugin())
    relationship_memory_plugin = RelationshipMemoryPlugin(raw_relationship_memory_store)
    plugin_manager.register(relationship_memory_plugin)
    agent_memory_plugin = AgentMemoryPlugin(raw_agent_memory_store)
    plugin_manager.register(agent_memory_plugin)
    plugin_manager.register(VoiceOutputPlugin(speech_synthesizer, audio_player))
    game_model = (
        config.plugins.games.intent_interpreter.model or config.response_generator.model
    )
    plugin_manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=_PluginLlmGateway(default_llm_plugin),
            activity_gateway=_ActivityManagerPluginGateway(activity_manager),
            clock=SystemClock(),
            configuration={
                "intent_interpreter": {
                    "enabled": config.plugins.games.intent_interpreter.enabled,
                    "model": game_model,
                    "confidence_threshold": (
                        config.plugins.games.intent_interpreter.confidence_threshold
                    ),
                    "max_attempts": config.plugins.games.intent_interpreter.max_attempts,
                },
                "shiritori": {
                    "enabled": config.plugins.games.shiritori.enabled,
                    "max_generation_retries": config.plugins.games.shiritori.max_generation_retries,
                },
                "llm_available": _is_model_provider_available(config, game_model),
            },
            capability_reporter=plugin_manager,
        ),
        {
            "llm_provider.default": True,
            "llm_provider.situation_evaluator": True,
            "llm_provider.character": character_llm_plugin is not None,
            "llm_provider.response_validator": validator_llm_plugin is not None,
            "games": config.plugins.games.enabled,
            "relationship_memory": raw_relationship_memory_store is not None,
            "agent_memory": raw_agent_memory_store is not None,
            "voice_output": speech_synthesizer is not None and audio_player is not None,
        },
    )
    relationship_memory_store: RelationshipMemoryStore | None = None
    initialized_memory_plugin = plugin_manager.get_plugin("relationship_memory")
    if isinstance(initialized_memory_plugin, RelationshipMemoryPlugin):
        relationship_memory_store = initialized_memory_plugin
    initial_relationship_memory = load_relationship_memory(
        relationship_memory_store,
        max_entries=config.memory.relationship_memory.max_entries,
    )
    if not plugin_manager.is_capability_available(
        RelationshipMemoryPlugin.MEMORY_CAPABILITY,
        RelationshipMemoryPlugin.plugin_id,
    ):
        relationship_memory_store = None
    agent_memory_store: AgentMemoryStore | None = None
    initialized_agent_memory_plugin = plugin_manager.get_plugin("agent_memory")
    if isinstance(initialized_agent_memory_plugin, AgentMemoryPlugin):
        agent_memory_store = initialized_agent_memory_plugin
    initial_agent_memory = load_agent_memory(
        agent_memory_store,
        max_history_entries=config.memory.agent_memory.max_history_entries,
    )
    if not plugin_manager.is_capability_available(
        AgentMemoryPlugin.MEMORY_CAPABILITY,
        AgentMemoryPlugin.plugin_id,
    ):
        agent_memory_store = None
    agent_life_service = AgentLifeService(
        activity_manager,
        initial_state=AgentState(
            relationship_memory=initial_relationship_memory,
            memory=initial_agent_memory,
        ),
        pending_confirmation_provider=pending_confirmation_manager.has_pending,
        short_term_memory=short_term_memory,
        relationship_memory_store=relationship_memory_store,
        agent_memory_store=agent_memory_store,
    )
    agent_life_service.update_drive(
        DriveState(
            curiosity=0.72,
            engagement=0.6,
            boredom=0.2,
            energy=0.8,
        )
    )
    response_generator: ResponseGenerator = default_llm_plugin
    situation_generator: ResponseGenerator = situation_llm_plugin
    if character_llm_plugin is None or validator_llm_plugin is None:
        character_response_pipeline = CharacterResponsePipeline(
            ResponseContextBuilder(short_term_memory, topic_history),
            CharacterLlmService(
                LegacyCharacterModelAdapter(response_generator),
                CharacterPromptBuilder(),
                character_profile,
            ),
            ResponseValidator(prompt_builder=ResponseValidatorPromptBuilder()),
        )
    else:
        character_response_pipeline = CharacterResponsePipeline(
            ResponseContextBuilder(short_term_memory, topic_history),
            CharacterLlmService(
                ResponseGeneratorRoleAdapter(character_llm_plugin),
                CharacterPromptBuilder(),
                character_profile,
            ),
            ResponseValidator(
                ResponseGeneratorRoleAdapter(validator_llm_plugin),
                ResponseValidatorPromptBuilder(),
            ),
        )
    voice_output = plugin_manager.get_plugin("voice_output")
    if isinstance(voice_output, VoiceOutputPlugin):
        speech_synthesizer = voice_output
        audio_player = voice_output
    topic_classifier = create_topic_classifier(config)
    embedding_generator = create_embedding_generator(config)
    topic_memory_store = create_topic_memory_store(config)
    memory_summary_generator = create_memory_summary_generator(config)
    enrich_activity_with_topic_memory_usecase = EnrichActivityWithTopicMemoryUsecase(
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )

    def activity_is_active(activity_id: str) -> bool:
        current = activity_manager.get_activity(activity_id)
        return current is not None and current.status == ActivityStatus.ACTIVE

    action_planner = ActionPlanner(
        response_generator=response_generator,
        character_response_pipeline=character_response_pipeline,
        activity_is_active=activity_is_active,
    )
    behavior_planner = BehaviorPlanner(
        situation_evaluator=SituationEvaluator(
            ResponseGeneratorRoleAdapter(situation_generator),
            prompt_builder=SituationEvaluatorPromptBuilder(),
        )
    )
    activity_registry = ActivityRegistry(plugin_manager.list_activity_definitions)
    activity_plan_validator = ActivityPlanValidator(
        plugin_manager.is_capability_available,
        activity_registry.list_definitions,
    )
    execute_action_usecase = ExecuteActionUsecase(
        event_publisher=event_bus,
        short_term_memory=short_term_memory,
        topic_history=topic_history,
        topic_classifier=topic_classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
        memory_summary_generator=memory_summary_generator,
        speech_synthesizer=speech_synthesizer,
        audio_player=audio_player,
    )

    planned_activity_queue = PlannedActivityQueue()
    activity_planning_request_queue: Queue[ActivityPlanningRequest] = Queue()
    activity_planning_service = ActivityPlanningService(
        agent_life_service=agent_life_service,
        activity_manager=activity_manager,
        enrich_activity_with_topic_memory_usecase=enrich_activity_with_topic_memory_usecase,
        behavior_planner=behavior_planner,
        short_term_memory=short_term_memory,
        topic_history=topic_history,
        available_activity_definitions=activity_registry.list_definitions,
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
        plugin_manager=plugin_manager,
        behavior_planner=behavior_planner,
        activity_plan_validator=activity_plan_validator,
        activity_registry=activity_registry,
        pending_confirmation_manager=pending_confirmation_manager,
        confirmation_resolver=ConfirmationResolver(),
        autonomous_planning_enabled=config.app.mode != "streaming_demo",
    )
    trace_logger.write(
        "runtime_factory:create_runtime_coordinator:finished",
        runtime_coordinator_class=type(runtime_coordinator).__name__,
        response_generator_type=config.response_generator.type,
        response_generator_class=type(response_generator).__name__,
        topic_history_class=type(topic_history).__name__,
        topic_classifier_class=(
            type(topic_classifier).__name__ if topic_classifier is not None else None
        ),
        embedding_generator_class=(
            type(embedding_generator).__name__
            if embedding_generator is not None
            else None
        ),
        topic_memory_store_class=(
            type(topic_memory_store).__name__
            if topic_memory_store is not None
            else None
        ),
        memory_summary_generator_class=(
            type(memory_summary_generator).__name__
            if memory_summary_generator is not None
            else None
        ),
        enrich_activity_with_topic_memory_usecase_class=type(
            enrich_activity_with_topic_memory_usecase
        ).__name__,
        activity_planner_thread_class=type(activity_planner_thread).__name__,
        activity_executor_thread_class=type(activity_executor_thread).__name__,
    )
    return runtime_coordinator


class _ActivityManagerPluginGateway:
    def __init__(self, activity_manager: ActivityManager) -> None:
        self._activity_manager = activity_manager

    def register(self, activity: Activity) -> Activity:
        return self._activity_manager.register_plugin_activity(activity)


class _PluginLlmGateway:
    """Shared Plugin要求をCore Activityへ変換するcomposition-root Adapter。"""

    def __init__(self, generator: ResponseGenerator) -> None:
        self._generator = generator

    async def generate_response(self, request: object) -> str:
        if isinstance(request, PluginActivityWorkItem):
            activity = Activity(
                activity_type=ActivityType.PLUGIN_ACTIVITY,
                goal=request.goal,
                priority=request.priority,
                context=dict(request.context),
                interruptible=request.interruptible,
                activity_id=request.work_item_id,
            )
            return await self._generator.generate_response(activity)
        if not isinstance(request, PluginLlmRequest):
            return await self._generator.generate_response(cast(Activity, request))
        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal=request.purpose,
            context={
                **request.context,
                "plugin_prompt_override": request.prompt,
                "llm_role": request.purpose,
                "request_id": request.request_id,
            },
        )
        return await self._generator.generate_response(activity)


def _is_model_provider_available(config: AppConfig, model_key: str) -> bool:
    if config.response_generator.type == "dummy":
        return True
    model = config.models.get(model_key)
    if model is None:
        return False
    service = config.services.get(model.service)
    if service is None:
        return False
    if service.type == "openai":
        return bool(service.api_key_env and os.getenv(service.api_key_env))
    return True


def create_stream_preparation_runtime(config: AppConfig) -> StreamPreparationRuntime:
    """状態確認専用Runtimeを組み立てる。配信開始・停止の依存は含めない。"""
    from app.adapters.streaming import (
        FakeLiveChatAdapter,
        FakeObsPreparationAdapter,
        FakeObsPreparationConfig,
        FakeTtsHealthAdapter,
        FakeYouTubePreparationAdapter,
        FakeYouTubePreparationConfig,
        InMemoryStreamMainSegmentRepository,
        InMemoryStreamOpeningRepository,
        InMemoryStreamPreparationPublisher,
        InMemoryStreamSessionRepository,
        UnavailableAvatarHealthAdapter,
        UnavailableYouTubePreparationAdapter,
        VoiceVoxHealthAdapter,
        VoiceVoxHealthConfig,
        YamlRunOfShowRepository,
    )
    from app.adapters.streaming.fake_streaming_control import (
        FakeObsStreamingControlAdapter,
        FakeYouTubeStreamingControlAdapter,
    )
    from app.core.plugins import (
        CapabilityAvailability,
        CapabilityRegistry,
        StaticCapabilityProvider,
    )
    from app.plugins.youtube_streaming.application import (
        PrepareStreamSessionUsecase,
        StartStreamSessionUsecase,
        StreamPreparationRequirements,
    )
    from app.plugins.youtube_streaming.domain import (
        HealthStatus,
        ReadinessPolicy,
        YouTubeBroadcastSummary,
    )
    from app.ports.streaming_preparation import (
        ObsPreparationPort,
        TtsHealthPort,
        YouTubePreparationPort,
    )

    youtube_service = _resolve_service(config, "youtube")
    youtube: YouTubePreparationPort
    youtube_control: YouTubeStreamingControlPort
    live_chat: YouTubeLiveChatReadPort
    if youtube_service.type == "fake":
        youtube = FakeYouTubePreparationAdapter(
            FakeYouTubePreparationConfig(
                broadcasts=(
                    YouTubeBroadcastSummary(
                        broadcast_id=config.streaming.fake.broadcast_id,
                        title=config.streaming.fake.broadcast_title,
                        live_chat_id=(
                            "demo-live-chat"
                            if config.app.mode == "streaming_demo"
                            else None
                        ),
                    ),
                )
            )
        )
        youtube_control = FakeYouTubeStreamingControlAdapter()
        live_chat = FakeLiveChatAdapter(keep_alive=config.app.mode == "streaming_demo")
        if config.app.mode == "streaming_demo":
            youtube_control.adapter_type = "demo_fake"
            youtube_control.stream_statuses = ["active", "active", "inactive"]
            youtube_control.broadcast_statuses = [
                "ready",
                "live",
                "live",
                "live",
                "complete",
            ]
    elif youtube_service.type in {"google", "google_youtube"}:
        from app.adapters.youtube import (
            GoogleYouTubeAuthConfig,
            GoogleYouTubeAuthService,
            GoogleYouTubeClientConfig,
            GoogleYouTubeClientFactory,
            GoogleYouTubePreparationAdapter,
            GoogleYouTubePreparationConfig,
        )

        required_settings = {
            "client_secret_path_env": youtube_service.client_secret_path_env,
            "token_path_env": youtube_service.token_path_env,
            "request_timeout_seconds": youtube_service.request_timeout_seconds,
            "max_retries": youtube_service.max_retries,
            "retry_initial_delay_seconds": youtube_service.retry_initial_delay_seconds,
            "oauth_open_browser": youtube_service.oauth_open_browser,
            "allow_live_broadcast": youtube_service.allow_live_broadcast,
            "oauth_timeout_seconds": youtube_service.oauth_timeout_seconds,
            "allowed_privacy_statuses": youtube_service.allowed_privacy_statuses,
        }
        missing = [name for name, value in required_settings.items() if value is None]
        if missing:
            youtube = UnavailableYouTubePreparationAdapter(
                "YouTube Google Adapterの設定が不足しています: " + ", ".join(missing)
            )
            youtube_control = FakeYouTubeStreamingControlAdapter()
            live_chat = FakeLiveChatAdapter()
        else:
            assert youtube_service.request_timeout_seconds is not None
            assert youtube_service.max_retries is not None
            assert youtube_service.retry_initial_delay_seconds is not None
            assert youtube_service.oauth_timeout_seconds is not None
            assert youtube_service.allowed_privacy_statuses is not None
            client_secret_path_env = str(youtube_service.client_secret_path_env)
            token_path_env = str(youtube_service.token_path_env)
            request_timeout = float(youtube_service.request_timeout_seconds)
            auth_service = GoogleYouTubeAuthService(
                GoogleYouTubeAuthConfig(
                    client_secret_path_env=client_secret_path_env,
                    token_path_env=token_path_env,
                    request_timeout_seconds=request_timeout,
                    open_browser=bool(youtube_service.oauth_open_browser),
                    oauth_timeout_seconds=youtube_service.oauth_timeout_seconds,
                )
            )
            client_factory = GoogleYouTubeClientFactory(
                auth_service,
                GoogleYouTubeClientConfig(request_timeout_seconds=request_timeout),
            )
            youtube = GoogleYouTubePreparationAdapter(
                auth_service=auth_service,
                client_factory=client_factory,
                config=GoogleYouTubePreparationConfig(
                    max_retries=int(youtube_service.max_retries),
                    retry_initial_delay_seconds=float(
                        youtube_service.retry_initial_delay_seconds
                    ),
                    allow_live_broadcast=bool(youtube_service.allow_live_broadcast),
                    allowed_privacy_statuses=youtube_service.allowed_privacy_statuses,
                ),
            )
            from app.adapters.youtube.google_youtube_streaming_control_adapter import (
                GoogleYouTubeStreamingControlAdapter,
            )

            youtube_control = GoogleYouTubeStreamingControlAdapter(
                client_factory, youtube
            )
            from app.adapters.youtube import GoogleYouTubeLiveChatAdapter

            live_chat = GoogleYouTubeLiveChatAdapter(client_factory)
    else:
        raise RuntimeError(f"未対応のYouTubeサービスです: {youtube_service.type}")

    obs_service = _resolve_service(config, "obs")
    obs: ObsPreparationPort
    obs_control: ObsStreamingControlPort
    if obs_service.type == "fake":
        obs = FakeObsPreparationAdapter(
            FakeObsPreparationConfig(
                current_scene=config.streaming.obs.expected_start_scene,
                current_scene_collection=config.streaming.obs.expected_scene_collection,
                audio_source_states={
                    name: True for name in config.streaming.obs.required_audio_sources
                },
            )
        )
        obs_control = FakeObsStreamingControlAdapter()
        if config.app.mode == "streaming_demo":
            obs_control.adapter_type = "demo_fake"
            obs_control.statuses = ["idle", "active", "active", "active", "idle"]
    elif obs_service.type == "disabled":
        from app.adapters.streaming import DisabledObsPreparationAdapter
        from app.adapters.streaming.fake_streaming_control import (
            DisabledObsStreamingControlAdapter,
        )

        obs = DisabledObsPreparationAdapter()
        obs_control = DisabledObsStreamingControlAdapter()
    elif obs_service.type == "obs_websocket":
        from urllib.parse import urlparse

        from app.adapters.obs import (
            ObsWebSocketClientConfig,
            ObsWebSocketClientFactory,
            ObsWebSocketPreparationAdapter,
            ObsWebSocketPreparationConfig,
            ObsWebSocketStreamingControlAdapter,
        )

        parsed = urlparse(obs_service.websocket_url or "")
        host = obs_service.host or parsed.hostname or ""
        port = obs_service.port or parsed.port or 4455
        password_env = obs_service.password_env or ""
        obs_client_factory = ObsWebSocketClientFactory(
            ObsWebSocketClientConfig(
                host=host,
                port=port,
                password_env=password_env,
                connect_timeout_seconds=obs_service.connect_timeout_seconds
                or obs_service.timeout_seconds
                or 5.0,
                request_timeout_seconds=obs_service.request_timeout_seconds
                or obs_service.timeout_seconds
                or 5.0,
            )
        )
        obs = ObsWebSocketPreparationAdapter(
            obs_client_factory,
            ObsWebSocketPreparationConfig(
                required_audio_sources=config.streaming.obs.required_audio_sources,
                optional_audio_sources=config.streaming.obs.optional_audio_sources,
                avatar_source_name=config.streaming.obs.avatar_source_name,
                low_volume_threshold_db=config.streaming.obs.low_volume_threshold_db,
                request_timeout_seconds=obs_service.request_timeout_seconds
                or obs_service.timeout_seconds
                or 5.0,
                max_retries=obs_service.max_retries or 0,
                retry_initial_delay_seconds=obs_service.retry_initial_delay_seconds
                or 0.5,
                max_scene_depth=config.streaming.obs.max_scene_depth,
            ),
        )
        obs_control = ObsWebSocketStreamingControlAdapter(
            obs_client_factory,
            request_timeout_seconds=obs_service.request_timeout_seconds
            or obs_service.timeout_seconds
            or 5.0,
        )
    else:
        raise RuntimeError(f"未対応のOBSサービスです: {obs_service.type}")

    if (
        isinstance(youtube_control, FakeYouTubeStreamingControlAdapter)
        and obs_control.adapter_type == "obs_websocket"
    ):
        youtube_control.stream_statuses = ["active", "active", "inactive"]
        youtube_control.broadcast_statuses = [
            "ready",
            "live",
            "live",
            "live",
            "complete",
        ]

    tts: TtsHealthPort
    if config.app.mode == "streaming_demo":
        tts = FakeTtsHealthAdapter()
    else:
        voicevox_service = _resolve_service(config, config.speech.service)
        player_command = config.speech.player.command or (
            "afplay" if sys.platform == "darwin" else "aplay"
        )
        tts = VoiceVoxHealthAdapter(
            VoiceVoxHealthConfig(
                base_url=_require_service_value(
                    voicevox_service.base_url, "base_url", config.speech.service
                ),
                timeout_seconds=_service_timeout(voicevox_service),
                speaker_id=config.speech.speaker_id,
                player_command=player_command,
            )
        )
    sessions = InMemoryStreamSessionRepository()
    publisher = InMemoryStreamPreparationPublisher()
    capability_registry = CapabilityRegistry()
    provider = StaticCapabilityProvider(
        "youtube_streaming",
        frozenset(
            {
                "stream.session.prepare",
                "stream.session.end.normal",
                "stream.session.stop.emergency",
                "youtube.broadcast.transition_complete",
                "obs.stream.stop",
                "output.cancel",
            }
        ),
        "YouTube Streaming Capability Health",
    )
    capability_registry.register(provider, "stream.session.prepare")
    for capability in (
        "stream.session.end.normal",
        "stream.session.stop.emergency",
        "youtube.broadcast.transition_complete",
        "obs.stream.stop",
        "output.cancel",
    ):
        capability_registry.register(provider, capability)

    status_mapping = {
        HealthStatus.HEALTHY: CapabilityAvailability.AVAILABLE,
        HealthStatus.DEGRADED: CapabilityAvailability.DEGRADED,
        HealthStatus.UNAVAILABLE: CapabilityAvailability.UNAVAILABLE,
        HealthStatus.UNKNOWN: CapabilityAvailability.UNKNOWN,
    }

    def report_capability(
        capability: str,
        status: HealthStatus,
        failure_reason: str | None,
        observed_at: datetime,
    ) -> None:
        availability = status_mapping[status]
        if availability in {
            CapabilityAvailability.AVAILABLE,
            CapabilityAvailability.DEGRADED,
        }:
            capability_registry.register(provider, capability)
        else:
            capability_registry.unregister(provider.plugin_id, capability)
        capability_registry.update_health(
            provider.plugin_id,
            capability,
            status=availability,
            failure_reason=failure_reason,
            observed_at=observed_at,
        )

    readiness = config.streaming.readiness
    run_of_show = YamlRunOfShowRepository(config.streaming.run_of_show.directory)
    usecase = PrepareStreamSessionUsecase(
        youtube=youtube,
        obs=obs,
        tts=tts,
        avatar=UnavailableAvatarHealthAdapter(),
        run_of_show=run_of_show,
        sessions=sessions,
        publisher=publisher,
        requirements=StreamPreparationRequirements(
            require_youtube=readiness.require_youtube,
            require_obs=readiness.require_obs,
            require_tts=readiness.require_tts,
            require_avatar=readiness.require_avatar,
            require_run_of_show=readiness.require_run_of_show,
            require_emergency_stop=readiness.require_emergency_stop,
            require_live_chat=readiness.require_live_chat,
            expected_scene_collection=config.streaming.obs.expected_scene_collection,
            expected_start_scene=config.streaming.obs.expected_start_scene,
            required_audio_sources=config.streaming.obs.required_audio_sources,
            require_obs_avatar_visible=config.streaming.obs.require_avatar_source_visible,
            timeout_seconds=config.streaming.health_timeout_seconds,
        ),
        readiness_policy=ReadinessPolicy(
            allow_required_degraded=readiness.allow_required_degraded
        ),
        capability_reporter=report_capability,
    )
    start_usecase = StartStreamSessionUsecase(
        sessions=sessions,
        obs=obs_control,
        youtube=youtube_control,
        poll_interval_seconds=0 if config.app.mode == "streaming_demo" else 1,
        allow_fake_youtube=(
            youtube_control.adapter_type == "fake"
            and obs_control.adapter_type == "obs_websocket"
        ),
    )
    logger.info(
        "Streaming adapters configured: config_path=%s youtube_adapter=%s "
        "obs_adapter=%s obs_host=%s obs_port=%s obs_password_env_set=%s",
        config.config_path,
        youtube_control.adapter_type,
        obs_control.adapter_type,
        obs_service.host,
        obs_service.port,
        bool(obs_service.password_env and os.getenv(obs_service.password_env)),
    )
    return StreamPreparationRuntime(
        config,
        usecase,
        sessions,
        publisher,
        capability_registry,
        start_usecase,
        InMemoryStreamOpeningRepository(),
        InMemoryStreamMainSegmentRepository(),
        run_of_show,
        obs_control,
        youtube_control,
        live_chat,
    )
