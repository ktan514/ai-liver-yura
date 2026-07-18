from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


@dataclass(frozen=True, slots=True)
class AppSettings:
    name: str
    mode: str


@dataclass(frozen=True, slots=True)
class TraceSettings:
    level: str
    format: str
    file_path: str
    max_bytes: int
    backup_count: int
    timezone: str = "local"
    debug_file_enabled: bool = False
    debug_file_path: str = "logs/runtime_debug.log"
    log_llm_prompts: bool = False
    log_llm_responses: bool = False
    log_user_input: bool = False


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    type: str
    base_url: str | None = None
    api_key_env: str | None = None
    dsn_env: str | None = None
    timeout_seconds: float | None = None
    client_secret_path_env: str | None = None
    token_path_env: str | None = None
    websocket_url: str | None = None
    password_env: str | None = None
    request_timeout_seconds: float | None = None
    max_retries: int | None = None
    retry_initial_delay_seconds: float | None = None
    oauth_open_browser: bool | None = None
    allow_live_broadcast: bool | None = None
    oauth_timeout_seconds: float | None = None
    allowed_privacy_statuses: tuple[str, ...] | None = None
    host: str | None = None
    port: int | None = None
    connect_timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ModelSettings:
    service: str
    name: str
    dimension: int | None = None


@dataclass(frozen=True, slots=True)
class ResponseGeneratorSettings:
    type: str
    model: str
    fallback_response: str


@dataclass(frozen=True, slots=True)
class LlmRoleSettings:
    model: str
    temperature: float
    timeout_seconds: float
    fallback_response: str


@dataclass(frozen=True, slots=True)
class LlmRolesSettings:
    situation_evaluator: LlmRoleSettings
    character: LlmRoleSettings
    response_validator: LlmRoleSettings


@dataclass(frozen=True, slots=True)
class SpeechPlayerSettings:
    type: str
    command: str | None


@dataclass(frozen=True, slots=True)
class SpeechVoiceProfileSettings:
    speed_scale: float
    pitch_scale: float
    intonation_scale: float
    volume_scale: float


@dataclass(frozen=True, slots=True)
class SpeechSettings:
    enabled: bool
    service: str
    pronunciation_dictionary_path: str
    speaker_id: int
    default_profile: str
    emotion_profiles: dict[str, SpeechVoiceProfileSettings]
    player: SpeechPlayerSettings


@dataclass(frozen=True, slots=True)
class TopicClassifierSettings:
    model: str


# TopicMemory/Memory settings dataclasses
@dataclass(frozen=True, slots=True)
class TopicMemorySummarySettings:
    type: str
    model: str
    fallback_max_length: int


@dataclass(frozen=True, slots=True)
class TopicMemorySettings:
    enabled: bool
    database_service: str
    embedding_model: str
    summary: TopicMemorySummarySettings


@dataclass(frozen=True, slots=True)
class MemorySettings:
    topic_memory: TopicMemorySettings


@dataclass(frozen=True, slots=True)
class CharacterSettings:
    name: str
    name_reading: str
    personality: str
    speaking_style: str
    streaming_style: str
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    behavior_policy: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConsoleInputReceiverSettings:
    enabled: bool


@dataclass(frozen=True, slots=True)
class TimerInputReceiverSettings:
    enabled: bool
    interval_seconds: float
    max_events: int | None


@dataclass(frozen=True, slots=True)
class InputReceiverSettings:
    console: ConsoleInputReceiverSettings
    timer: TimerInputReceiverSettings


@dataclass(frozen=True, slots=True)
class ConfirmationSettings:
    timeout_seconds: float
    max_attempts: int


@dataclass(frozen=True, slots=True)
class GameIntentInterpreterSettings:
    enabled: bool = True
    model: str | None = None
    confidence_threshold: float = 0.85
    max_attempts: int = 2


@dataclass(frozen=True, slots=True)
class ShiritoriPluginSettings:
    enabled: bool = True
    max_generation_retries: int = 3


@dataclass(frozen=True, slots=True)
class GamesPluginSettings:
    enabled: bool = True
    intent_interpreter: GameIntentInterpreterSettings = field(
        default_factory=GameIntentInterpreterSettings
    )
    shiritori: ShiritoriPluginSettings = field(default_factory=ShiritoriPluginSettings)


@dataclass(frozen=True, slots=True)
class PluginRegistrationSettings:
    enabled: bool = True
    config_reference: str | None = None


@dataclass(frozen=True, slots=True)
class PluginSettings:
    games: GamesPluginSettings = field(default_factory=GamesPluginSettings)
    registrations: dict[str, PluginRegistrationSettings] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StreamingReadinessSettings:
    require_youtube: bool = True
    require_obs: bool = True
    require_tts: bool = True
    require_avatar: bool = False
    require_run_of_show: bool = True
    require_emergency_stop: bool = False
    allow_required_degraded: bool = False
    require_live_chat: bool = False


@dataclass(frozen=True, slots=True)
class StreamingObsSettings:
    expected_scene_collection: str = "AI Liver"
    expected_start_scene: str = "Starting Soon"
    required_audio_sources: tuple[str, ...] = ("VOICEVOX",)
    optional_audio_sources: tuple[str, ...] = ()
    avatar_source_name: str | None = None
    require_avatar_source_visible: bool = False
    low_volume_threshold_db: float = -60.0
    max_scene_depth: int = 8


@dataclass(frozen=True, slots=True)
class StreamingRunOfShowSettings:
    directory: str = "config/run_of_show"
    default_id: str = "default"


@dataclass(frozen=True, slots=True)
class StreamingFakeSettings:
    broadcast_id: str = "fake-broadcast-1"
    broadcast_title: str = "配信準備テスト枠"


@dataclass(frozen=True, slots=True)
class CommentModerationSettings:
    blocked_terms: tuple[str, ...] = ()
    allowed_terms: tuple[str, ...] = ()
    max_comment_length: int = 300
    repeated_message_window_seconds: int = 30
    repeated_message_limit: int = 3
    url_policy: str = "review"
    unknown_message_type_policy: str = "ignore"
    max_concurrent_evaluations: int = 4
    evaluation_queue_capacity: int = 128
    timeout_seconds: float = 3.0


@dataclass(frozen=True, slots=True)
class CommentRankingSettings:
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "recency": 0.15,
            "relevance": 0.25,
            "novelty": 0.15,
            "conversation_fit": 0.20,
            "engagement": 0.15,
            "fairness": 0.10,
        }
    )
    selection_threshold: float = 0.55
    minimum_conversation_fit: float = 0.5
    candidate_ttl_seconds: int = 90
    reservation_ttl_seconds: int = 30
    max_pool_size: int = 200
    max_rank_batch_size: int = 50
    history_size: int = 100
    author_cooldown_count: int = 2
    semantic_timeout_seconds: float = 2.0
    max_concurrent_rankings: int = 1
    queue_capacity: int = 16

    def __post_init__(self) -> None:
        expected = {
            "recency",
            "relevance",
            "novelty",
            "conversation_fit",
            "engagement",
            "fairness",
        }
        if set(self.weights) != expected or abs(sum(self.weights.values()) - 1.0) > 0.000001:
            raise ValueError("comment_ranking.weights_invalid")
        if any(not 0 <= value <= 1 for value in self.weights.values()):
            raise ValueError("comment_ranking.weights_invalid")
        if not 0 <= self.selection_threshold <= 1 or not 0 <= self.minimum_conversation_fit <= 1:
            raise ValueError("comment_ranking.threshold_invalid")
        positive = (
            self.candidate_ttl_seconds,
            self.reservation_ttl_seconds,
            self.max_pool_size,
            self.max_rank_batch_size,
            self.history_size,
            self.author_cooldown_count,
            self.semantic_timeout_seconds,
            self.max_concurrent_rankings,
            self.queue_capacity,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("comment_ranking.capacity_invalid")


@dataclass(frozen=True, slots=True)
class CommentResponseSettings:
    max_characters: int = 140
    max_sentences: int = 3
    allow_follow_up_question: bool = True
    mention_author_name: str = "optional"
    repeat_comment_text: bool = False
    response_cooldown_seconds: int = 5
    max_retries: int = 2

    def __post_init__(self) -> None:
        if self.max_characters <= 0 or self.max_sentences <= 0:
            raise ValueError("comment_response.length_invalid")
        if self.mention_author_name not in {"never", "optional"}:
            raise ValueError("comment_response.author_policy_invalid")
        if self.response_cooldown_seconds < 0 or self.max_retries < 0:
            raise ValueError("comment_response.retry_invalid")


@dataclass(frozen=True, slots=True)
class StreamingSettings:
    readiness: StreamingReadinessSettings = field(default_factory=StreamingReadinessSettings)
    obs: StreamingObsSettings = field(default_factory=StreamingObsSettings)
    run_of_show: StreamingRunOfShowSettings = field(default_factory=StreamingRunOfShowSettings)
    fake: StreamingFakeSettings = field(default_factory=StreamingFakeSettings)
    moderation: CommentModerationSettings = field(default_factory=CommentModerationSettings)
    comment_ranking: CommentRankingSettings = field(default_factory=CommentRankingSettings)
    comment_response: CommentResponseSettings = field(default_factory=CommentResponseSettings)
    health_timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class AppConfig:
    app: AppSettings
    trace: TraceSettings
    services: dict[str, ServiceSettings]
    models: dict[str, ModelSettings]
    response_generator: ResponseGeneratorSettings
    llm_roles: LlmRolesSettings
    speech: SpeechSettings
    topic_classifier: TopicClassifierSettings
    memory: MemorySettings
    character: CharacterSettings
    input_receivers: InputReceiverSettings
    confirmation: ConfirmationSettings
    plugins: PluginSettings = field(default_factory=PluginSettings)
    streaming: StreamingSettings = field(default_factory=StreamingSettings)
    config_path: str = ""


def load_app_config(config_path: Path = CONFIG_PATH) -> AppConfig:
    resolved_path = config_path.resolve()
    raw_config = load_raw_config(resolved_path)

    return AppConfig(
        app=_load_app_settings(_require_dict(raw_config, "app")),
        trace=_load_trace_settings(_require_dict(raw_config, "trace")),
        services=_load_services(_require_dict(raw_config, "services")),
        models=_load_models(_require_dict(raw_config, "models")),
        response_generator=_load_response_generator_settings(
            _require_dict(raw_config, "response_generator")
        ),
        llm_roles=_load_llm_roles_settings(_require_dict(raw_config, "llm_roles")),
        speech=_load_speech_settings(_require_dict(raw_config, "speech")),
        topic_classifier=_load_topic_classifier_settings(
            _require_dict(raw_config, "topic_classifier")
        ),
        memory=_load_memory_settings(_require_dict(raw_config, "memory")),
        character=_load_character_settings(_require_dict(raw_config, "character")),
        input_receivers=_load_input_receiver_settings(_require_dict(raw_config, "input_receivers")),
        confirmation=_load_confirmation_settings(_require_dict(raw_config, "confirmation")),
        plugins=_load_plugin_settings(raw_config.get("plugins")),
        streaming=_load_streaming_settings(raw_config.get("streaming")),
        config_path=str(resolved_path),
    )


def _load_streaming_settings(value: object) -> StreamingSettings:
    if value is None:
        return StreamingSettings()
    if not isinstance(value, dict):
        raise RuntimeError("streaming はobject形式で指定してください。")
    readiness = value.get("readiness", {})
    obs = value.get("obs", {})
    run_of_show = value.get("run_of_show", {})
    fake = value.get("fake", {})
    moderation = value.get("moderation", {})
    ranking = value.get("comment_ranking", {})
    response = value.get("comment_response", {})
    if not all(
        isinstance(item, dict)
        for item in (readiness, obs, run_of_show, fake, moderation, ranking, response)
    ):
        raise RuntimeError("streaming配下はobject形式で指定してください。")
    default_weights = CommentRankingSettings().weights
    weights = ranking.get("weights", default_weights)
    if not isinstance(weights, dict) or set(weights) != set(default_weights):
        raise RuntimeError("streaming.comment_ranking.weightsのFeatureが不正です。")
    parsed_weights = {key: float(value) for key, value in weights.items()}
    if (
        any(value < 0 or value > 1 for value in parsed_weights.values())
        or abs(sum(parsed_weights.values()) - 1.0) > 0.000001
    ):
        raise RuntimeError("streaming.comment_ranking.weightsの合計は1.0で指定してください。")
    audio_sources = obs.get("required_audio_sources", ["VOICEVOX"])
    if not isinstance(audio_sources, list) or not all(
        isinstance(item, str) and item for item in audio_sources
    ):
        raise RuntimeError("streaming.obs.required_audio_sourcesは文字列listです。")
    optional_audio_sources = obs.get("optional_audio_sources", [])
    if not isinstance(optional_audio_sources, list) or not all(
        isinstance(item, str) and item for item in optional_audio_sources
    ):
        raise RuntimeError("streaming.obs.optional_audio_sourcesは文字列listです。")
    timeout = value.get("health_timeout_seconds", 5.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise RuntimeError("streaming.health_timeout_secondsは正数です。")
    return StreamingSettings(
        readiness=StreamingReadinessSettings(
            require_youtube=_optional_bool(readiness, "require_youtube", True),
            require_obs=_optional_bool(readiness, "require_obs", True),
            require_tts=_optional_bool(readiness, "require_tts", True),
            require_avatar=_optional_bool(readiness, "require_avatar", False),
            require_run_of_show=_optional_bool(readiness, "require_run_of_show", True),
            require_emergency_stop=_optional_bool(readiness, "require_emergency_stop", False),
            allow_required_degraded=_optional_bool(readiness, "allow_required_degraded", False),
            require_live_chat=_optional_bool(readiness, "require_live_chat", False),
        ),
        obs=StreamingObsSettings(
            expected_scene_collection=(
                _optional_string(obs, "expected_scene_collection") or "AI Liver"
            ),
            expected_start_scene=(_optional_string(obs, "expected_start_scene") or "Starting Soon"),
            required_audio_sources=tuple(audio_sources),
            optional_audio_sources=tuple(optional_audio_sources),
            avatar_source_name=_optional_string(obs, "avatar_source_name"),
            require_avatar_source_visible=_optional_bool(
                obs, "require_avatar_source_visible", False
            ),
            low_volume_threshold_db=float(obs.get("low_volume_threshold_db", -60.0)),
            max_scene_depth=int(obs.get("max_scene_depth", 8)),
        ),
        run_of_show=StreamingRunOfShowSettings(
            directory=_optional_string(run_of_show, "directory") or "config/run_of_show",
            default_id=_optional_string(run_of_show, "default_id") or "default",
        ),
        fake=StreamingFakeSettings(
            broadcast_id=_optional_string(fake, "broadcast_id") or "fake-broadcast-1",
            broadcast_title=(_optional_string(fake, "broadcast_title") or "配信準備テスト枠"),
        ),
        moderation=CommentModerationSettings(
            blocked_terms=tuple(str(item) for item in moderation.get("blocked_terms", [])),
            allowed_terms=tuple(str(item) for item in moderation.get("allowed_terms", [])),
            max_comment_length=int(moderation.get("max_comment_length", 300)),
            repeated_message_window_seconds=int(
                moderation.get("repeated_message_window_seconds", 30)
            ),
            repeated_message_limit=int(moderation.get("repeated_message_limit", 3)),
            url_policy=str(moderation.get("url_policy", "review")),
            unknown_message_type_policy=str(
                moderation.get("unknown_message_type_policy", "ignore")
            ),
            max_concurrent_evaluations=int(moderation.get("max_concurrent_evaluations", 4)),
            evaluation_queue_capacity=int(moderation.get("evaluation_queue_capacity", 128)),
            timeout_seconds=float(moderation.get("timeout_seconds", 3.0)),
        ),
        comment_ranking=CommentRankingSettings(
            weights=parsed_weights,
            selection_threshold=float(ranking.get("selection_threshold", 0.55)),
            minimum_conversation_fit=float(ranking.get("minimum_conversation_fit", 0.5)),
            candidate_ttl_seconds=int(ranking.get("candidate_ttl_seconds", 90)),
            reservation_ttl_seconds=int(ranking.get("reservation_ttl_seconds", 30)),
            max_pool_size=int(ranking.get("max_pool_size", 200)),
            max_rank_batch_size=int(ranking.get("max_rank_batch_size", 50)),
            history_size=int(ranking.get("history_size", 100)),
            author_cooldown_count=int(ranking.get("author_cooldown_count", 2)),
            semantic_timeout_seconds=float(ranking.get("semantic_timeout_seconds", 2.0)),
            max_concurrent_rankings=int(ranking.get("max_concurrent_rankings", 1)),
            queue_capacity=int(ranking.get("queue_capacity", 16)),
        ),
        comment_response=CommentResponseSettings(
            max_characters=int(response.get("max_characters", 140)),
            max_sentences=int(response.get("max_sentences", 3)),
            allow_follow_up_question=bool(response.get("allow_follow_up_question", True)),
            mention_author_name=str(response.get("mention_author_name", "optional")),
            repeat_comment_text=bool(response.get("repeat_comment_text", False)),
            response_cooldown_seconds=int(response.get("response_cooldown_seconds", 5)),
            max_retries=int(response.get("max_retries", 2)),
        ),
        health_timeout_seconds=float(timeout),
    )


def _load_plugin_settings(value: object) -> PluginSettings:
    if value is None:
        return PluginSettings()
    if not isinstance(value, dict):
        raise RuntimeError("plugins はobject形式で指定してください。")
    games = value.get("games", {})
    if not isinstance(games, dict):
        raise RuntimeError("plugins.games はobject形式で指定してください。")
    registrations = value.get("registry", {})
    if not isinstance(registrations, dict):
        raise RuntimeError("plugins.registry はobject形式で指定してください。")
    parsed_registrations: dict[str, PluginRegistrationSettings] = {}
    for plugin_id, raw in registrations.items():
        if not isinstance(plugin_id, str) or not isinstance(raw, dict):
            raise RuntimeError("plugins.registry配下はobject形式で指定してください。")
        config_reference = raw.get("config_reference")
        if config_reference is not None and not isinstance(config_reference, str):
            raise RuntimeError("plugin config_reference は文字列で指定してください。")
        parsed_registrations[plugin_id] = PluginRegistrationSettings(
            enabled=bool(raw.get("enabled", True)),
            config_reference=config_reference,
        )
    interpreter = games.get("intent_interpreter", {})
    shiritori = games.get("shiritori", {})
    if not isinstance(interpreter, dict) or not isinstance(shiritori, dict):
        raise RuntimeError("plugins.games配下はobject形式で指定してください。")
    threshold = interpreter.get("confidence_threshold", 0.85)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise RuntimeError("confidence_threshold は数値で指定してください。")
    return PluginSettings(
        games=GamesPluginSettings(
            enabled=bool(games.get("enabled", True)),
            intent_interpreter=GameIntentInterpreterSettings(
                enabled=bool(interpreter.get("enabled", True)),
                model=interpreter.get("model")
                if isinstance(interpreter.get("model"), str)
                else None,
                confidence_threshold=float(threshold),
                max_attempts=int(interpreter.get("max_attempts", 2)),
            ),
            shiritori=ShiritoriPluginSettings(
                enabled=bool(shiritori.get("enabled", True)),
                max_generation_retries=int(shiritori.get("max_generation_retries", 3)),
            ),
        ),
        registrations=parsed_registrations,
    )


def _load_confirmation_settings(config: dict[str, Any]) -> ConfirmationSettings:
    return ConfirmationSettings(
        timeout_seconds=_require_positive_float(config, "timeout_seconds"),
        max_attempts=_require_positive_int(config, "max_attempts"),
    )


def load_raw_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not config_path.exists():
        raise RuntimeError(f"設定ファイルが見つかりません: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file)

    if raw_config is None:
        raise RuntimeError(f"設定ファイルが空です: {config_path}")

    if not isinstance(raw_config, dict):
        raise RuntimeError("設定ファイルの形式が不正です。YAML の最上位は object にしてください。")

    return raw_config


def _load_app_settings(config: dict[str, Any]) -> AppSettings:
    return AppSettings(
        name=_require_string(config, "name"),
        mode=_require_string(config, "mode"),
    )


def _load_trace_settings(config: dict[str, Any]) -> TraceSettings:
    level = _require_string(config, "level").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "OFF"}:
        raise RuntimeError("trace.level は DEBUG, INFO, WARNING, ERROR, OFF から選択してください。")
    output_format = _require_string(config, "format").lower()
    if output_format not in {"text", "jsonl"}:
        raise RuntimeError("trace.format は text または jsonl を指定してください。")
    timezone_name = str(config.get("timezone", "local")).lower()
    if timezone_name != "local":
        raise RuntimeError("trace.timezone は local を指定してください。")
    debug_file_path = _optional_string(config, "debug_file_path")
    return TraceSettings(
        level=level,
        format=output_format,
        file_path=_require_string(config, "file_path"),
        max_bytes=_require_positive_int(config, "max_bytes"),
        backup_count=_require_non_negative_int(config, "backup_count"),
        timezone=timezone_name,
        debug_file_enabled=_optional_bool(config, "debug_file_enabled", False),
        debug_file_path=debug_file_path or "logs/runtime_debug.log",
        log_llm_prompts=_optional_bool(config, "log_llm_prompts", False),
        log_llm_responses=_optional_bool(config, "log_llm_responses", False),
        log_user_input=_optional_bool(config, "log_user_input", False),
    )


def _load_response_generator_settings(config: dict[str, Any]) -> ResponseGeneratorSettings:
    return ResponseGeneratorSettings(
        type=_require_string(config, "type"),
        model=_require_string(config, "model"),
        fallback_response=_require_string(config, "fallback_response"),
    )


def _load_llm_roles_settings(config: dict[str, Any]) -> LlmRolesSettings:
    return LlmRolesSettings(
        situation_evaluator=_load_llm_role_settings(
            _require_dict(config, "situation_evaluator"), "situation_evaluator"
        ),
        character=_load_llm_role_settings(_require_dict(config, "character"), "character"),
        response_validator=_load_llm_role_settings(
            _require_dict(config, "response_validator"), "response_validator"
        ),
    )


def _load_llm_role_settings(config: dict[str, Any], role: str) -> LlmRoleSettings:
    temperature = _require_float(config, "temperature")
    if not 0.0 <= temperature <= 2.0:
        raise RuntimeError(f"llm_roles.{role}.temperature は0.0以上2.0以下にしてください。")
    timeout = _require_positive_float(config, "timeout_seconds")
    return LlmRoleSettings(
        model=_require_string(config, "model"),
        temperature=temperature,
        timeout_seconds=timeout,
        fallback_response=_require_string(config, "fallback_response"),
    )


def _load_speech_settings(config: dict[str, Any]) -> SpeechSettings:
    player = _require_dict(config, "player")
    emotion_profiles_config = _require_dict(config, "emotion_profiles")
    emotion_profiles = {
        name: _load_speech_voice_profile(profile, name)
        for name, profile in emotion_profiles_config.items()
        if isinstance(profile, dict)
    }
    if len(emotion_profiles) != len(emotion_profiles_config):
        raise RuntimeError("speech.emotion_profilesの各値はobject形式で指定してください。")
    default_profile = _require_string(config, "default_profile")
    if default_profile not in emotion_profiles:
        raise RuntimeError("speech.default_profileがemotion_profilesに定義されていません。")
    return SpeechSettings(
        enabled=_require_bool(config, "enabled"),
        service=_require_string(config, "service"),
        pronunciation_dictionary_path=_require_string(config, "pronunciation_dictionary_path"),
        speaker_id=_require_non_negative_int(config, "speaker_id"),
        default_profile=default_profile,
        emotion_profiles=emotion_profiles,
        player=SpeechPlayerSettings(
            type=_require_string(player, "type"),
            command=_optional_string(player, "command"),
        ),
    )


def _load_speech_voice_profile(config: dict[str, Any], name: str) -> SpeechVoiceProfileSettings:
    try:
        speed_scale = _require_positive_float(config, "speed_scale")
        pitch_scale = _require_float(config, "pitch_scale")
        intonation_scale = _require_positive_float(config, "intonation_scale")
        volume_scale = _require_positive_float(config, "volume_scale")
    except RuntimeError as error:
        raise RuntimeError(f"speech.emotion_profiles.{name}: {error}") from error
    return SpeechVoiceProfileSettings(
        speed_scale=speed_scale,
        pitch_scale=pitch_scale,
        intonation_scale=intonation_scale,
        volume_scale=volume_scale,
    )


def _load_services(config: dict[str, Any]) -> dict[str, ServiceSettings]:
    services: dict[str, ServiceSettings] = {}
    for key, value in config.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"services.{key} は object 形式で指定してください。")
        request_timeout = _optional_float(value, "request_timeout_seconds")
        if request_timeout is not None and request_timeout <= 0:
            raise RuntimeError(f"services.{key}.request_timeout_secondsは正数です。")
        max_retries = _optional_int(value, "max_retries")
        if max_retries is not None and max_retries < 0:
            raise RuntimeError(f"services.{key}.max_retriesは0以上です。")
        port = _optional_int(value, "port")
        if port is not None and not 1 <= port <= 65535:
            raise RuntimeError(f"services.{key}.portは1以上65535以下です。")
        connect_timeout = _optional_float(value, "connect_timeout_seconds")
        if connect_timeout is not None and connect_timeout <= 0:
            raise RuntimeError(f"services.{key}.connect_timeout_secondsは正数です。")
        retry_delay = _optional_float(value, "retry_initial_delay_seconds")
        if retry_delay is not None and retry_delay <= 0:
            raise RuntimeError(f"services.{key}.retry_initial_delay_secondsは正数です。")
        oauth_timeout = _optional_float(value, "oauth_timeout_seconds")
        if oauth_timeout is not None and oauth_timeout <= 0:
            raise RuntimeError(f"services.{key}.oauth_timeout_secondsは正数です。")
        privacy_statuses = value.get("allowed_privacy_statuses")
        if privacy_statuses is not None and (
            not isinstance(privacy_statuses, list)
            or not privacy_statuses
            or not all(
                isinstance(item, str) and item in {"private", "unlisted", "public"}
                for item in privacy_statuses
            )
        ):
            raise RuntimeError(
                f"services.{key}.allowed_privacy_statusesはprivate/unlisted/publicのlistです。"
            )
        services[key] = ServiceSettings(
            type=_require_string(value, "type"),
            base_url=_optional_string(value, "base_url"),
            api_key_env=_optional_string(value, "api_key_env"),
            dsn_env=_optional_string(value, "dsn_env"),
            timeout_seconds=_optional_float(value, "timeout_seconds"),
            client_secret_path_env=_optional_string(value, "client_secret_path_env"),
            token_path_env=_optional_string(value, "token_path_env"),
            websocket_url=_optional_string(value, "websocket_url"),
            password_env=_optional_string(value, "password_env"),
            request_timeout_seconds=request_timeout,
            max_retries=max_retries,
            retry_initial_delay_seconds=retry_delay,
            oauth_open_browser=(
                _optional_bool(value, "oauth_open_browser", True)
                if "oauth_open_browser" in value
                else None
            ),
            allow_live_broadcast=(
                _optional_bool(value, "allow_live_broadcast", False)
                if "allow_live_broadcast" in value
                else None
            ),
            oauth_timeout_seconds=oauth_timeout,
            allowed_privacy_statuses=(
                tuple(privacy_statuses) if isinstance(privacy_statuses, list) else None
            ),
            host=_optional_string(value, "host"),
            port=port,
            connect_timeout_seconds=connect_timeout,
        )
    return services


def _load_models(config: dict[str, Any]) -> dict[str, ModelSettings]:
    models: dict[str, ModelSettings] = {}
    for key, value in config.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"models.{key} は object 形式で指定してください。")
        models[key] = ModelSettings(
            service=_require_string(value, "service"),
            name=_require_string(value, "name"),
            dimension=_optional_int(value, "dimension"),
        )
    return models


def _load_topic_classifier_settings(config: dict[str, Any]) -> TopicClassifierSettings:
    return TopicClassifierSettings(model=_require_string(config, "model"))


# Memory settings loader functions
def _load_memory_settings(config: dict[str, Any]) -> MemorySettings:
    return MemorySettings(
        topic_memory=_load_topic_memory_settings(_require_dict(config, "topic_memory")),
    )


def _load_topic_memory_settings(config: dict[str, Any]) -> TopicMemorySettings:
    return TopicMemorySettings(
        enabled=_require_bool(config, "enabled"),
        database_service=_require_string(config, "database_service"),
        embedding_model=_require_string(config, "embedding_model"),
        summary=_load_topic_memory_summary_settings(_require_dict(config, "summary")),
    )


def _load_topic_memory_summary_settings(
    config: dict[str, Any],
) -> TopicMemorySummarySettings:
    return TopicMemorySummarySettings(
        type=_require_string(config, "type"),
        model=_require_string(config, "model"),
        fallback_max_length=_require_int(config, "fallback_max_length"),
    )


def _load_character_settings(config: dict[str, Any]) -> CharacterSettings:
    return CharacterSettings(
        name=_require_string(config, "name"),
        name_reading=_require_string(config, "name_reading"),
        personality=_require_string(config, "personality"),
        speaking_style=_require_string(config, "speaking_style"),
        streaming_style=_require_string(config, "streaming_style"),
        likes=_require_string_list(config, "likes"),
        dislikes=_require_string_list(config, "dislikes"),
        behavior_policy=_require_string_list(config, "behavior_policy"),
    )


def _load_input_receiver_settings(config: dict[str, Any]) -> InputReceiverSettings:
    console_config = _require_dict(config, "console")
    timer_config = _require_dict(config, "timer")

    return InputReceiverSettings(
        console=ConsoleInputReceiverSettings(
            enabled=_require_bool(console_config, "enabled"),
        ),
        timer=TimerInputReceiverSettings(
            enabled=_require_bool(timer_config, "enabled"),
            interval_seconds=_require_float(timer_config, "interval_seconds"),
            max_events=_require_optional_int(timer_config, "max_events"),
        ),
    )


def _require_dict(config: dict[str, Any], setting_path: str) -> dict[str, Any]:
    value = _get_required_value(config, setting_path)

    if not isinstance(value, dict):
        raise RuntimeError(f"{setting_path} は object 形式で指定してください。")

    return value


def _require_string(config: dict[str, Any], setting_path: str) -> str:
    value = _get_required_value(config, setting_path)

    if not isinstance(value, str):
        raise RuntimeError(f"{setting_path} は文字列で指定してください。")

    if not value:
        raise RuntimeError(f"{setting_path} は空文字にできません。")

    return value


def _require_string_list(config: dict[str, Any], setting_path: str) -> list[str]:
    value = _get_required_value(config, setting_path)

    if not isinstance(value, list):
        raise RuntimeError(f"{setting_path} は list 形式で指定してください。")

    return [str(item) for item in value]


def _require_bool(config: dict[str, Any], setting_path: str) -> bool:
    value = _get_required_value(config, setting_path)

    if not isinstance(value, bool):
        raise RuntimeError(f"{setting_path} は true または false で指定してください。")

    return value


def _require_float(config: dict[str, Any], setting_path: str) -> float:
    value = _get_required_value(config, setting_path)

    if not isinstance(value, int | float):
        raise RuntimeError(f"{setting_path} は数値で指定してください。")

    return float(value)


def _require_positive_float(config: dict[str, Any], setting_path: str) -> float:
    value = _require_float(config, setting_path)
    if value <= 0:
        raise RuntimeError(f"{setting_path} は0より大きい値で指定してください。")
    return value


def _require_int(config: dict[str, Any], setting_path: str) -> int:
    value = _get_required_value(config, setting_path)

    if not isinstance(value, int):
        raise RuntimeError(f"{setting_path} は整数で指定してください。")

    return value


def _require_positive_int(config: dict[str, Any], setting_path: str) -> int:
    value = _require_int(config, setting_path)
    if value <= 0:
        raise RuntimeError(f"{setting_path} は1以上で指定してください。")
    return value


def _require_non_negative_int(config: dict[str, Any], setting_path: str) -> int:
    value = _require_int(config, setting_path)
    if value < 0:
        raise RuntimeError(f"{setting_path} は0以上で指定してください。")
    return value


def _require_optional_int(config: dict[str, Any], setting_path: str) -> int | None:
    value = _get_required_value(config, setting_path)

    if value is None:
        return None

    if not isinstance(value, int):
        raise RuntimeError(f"{setting_path} は整数または null で指定してください。")

    return value


def _optional_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{key} は空でない文字列で指定してください。")
    return value


def _optional_float(config: dict[str, Any], key: str) -> float | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise RuntimeError(f"{key} は数値で指定してください。")
    return float(value)


def _optional_int(config: dict[str, Any], key: str) -> int | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise RuntimeError(f"{key} は整数で指定してください。")
    return value


def _optional_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"{key} は true または false で指定してください。")
    return value


def _get_required_value(config: dict[str, Any], setting_path: str) -> Any:
    current: Any = config

    for key in setting_path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise RuntimeError(f"必須設定が不足しています: {setting_path}")
        current = current[key]

    return current
