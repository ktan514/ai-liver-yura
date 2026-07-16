from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path("config/config.yaml")


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
class PluginSettings:
    games: GamesPluginSettings = field(default_factory=GamesPluginSettings)


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


@dataclass(frozen=True, slots=True)
class StreamingRunOfShowSettings:
    directory: str = "config/run_of_show"
    default_id: str = "default"


@dataclass(frozen=True, slots=True)
class StreamingFakeSettings:
    broadcast_id: str = "fake-broadcast-1"
    broadcast_title: str = "配信準備テスト枠"


@dataclass(frozen=True, slots=True)
class StreamingSettings:
    readiness: StreamingReadinessSettings = field(default_factory=StreamingReadinessSettings)
    obs: StreamingObsSettings = field(default_factory=StreamingObsSettings)
    run_of_show: StreamingRunOfShowSettings = field(default_factory=StreamingRunOfShowSettings)
    fake: StreamingFakeSettings = field(default_factory=StreamingFakeSettings)
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


def load_app_config(config_path: Path = CONFIG_PATH) -> AppConfig:
    raw_config = load_raw_config(config_path)

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
    if not all(isinstance(item, dict) for item in (readiness, obs, run_of_show, fake)):
        raise RuntimeError("streaming配下はobject形式で指定してください。")
    audio_sources = obs.get("required_audio_sources", ["VOICEVOX"])
    if not isinstance(audio_sources, list) or not all(
        isinstance(item, str) and item for item in audio_sources
    ):
        raise RuntimeError("streaming.obs.required_audio_sourcesは文字列listです。")
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
        ),
        run_of_show=StreamingRunOfShowSettings(
            directory=_optional_string(run_of_show, "directory") or "config/run_of_show",
            default_id=_optional_string(run_of_show, "default_id") or "default",
        ),
        fake=StreamingFakeSettings(
            broadcast_id=_optional_string(fake, "broadcast_id") or "fake-broadcast-1",
            broadcast_title=(_optional_string(fake, "broadcast_title") or "配信準備テスト枠"),
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
        )
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
