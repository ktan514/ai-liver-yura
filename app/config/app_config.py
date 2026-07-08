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
class OllamaSettings:
    model: str
    api_url: str
    timeout_seconds: float
    fallback_response: str


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    model: str
    api_key_env: str
    timeout_seconds: float
    fallback_response: str


@dataclass(frozen=True, slots=True)
class DummyResponseGeneratorSettings:
    enabled: bool


@dataclass(frozen=True, slots=True)
class ResponseGeneratorSettings:
    type: str
    ollama: OllamaSettings
    openai: OpenAISettings
    dummy: DummyResponseGeneratorSettings


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
class AppConfig:
    app: AppSettings
    response_generator: ResponseGeneratorSettings
    character: CharacterSettings
    input_receivers: InputReceiverSettings


def load_app_config(config_path: Path = CONFIG_PATH) -> AppConfig:
    raw_config = load_raw_config(config_path)

    return AppConfig(
        app=_load_app_settings(_require_dict(raw_config, "app")),
        response_generator=_load_response_generator_settings(
            _require_dict(raw_config, "response_generator")
        ),
        character=_load_character_settings(_require_dict(raw_config, "character")),
        input_receivers=_load_input_receiver_settings(
            _require_dict(raw_config, "input_receivers")
        ),
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


def _load_response_generator_settings(config: dict[str, Any]) -> ResponseGeneratorSettings:
    return ResponseGeneratorSettings(
        type=_require_string(config, "type"),
        ollama=_load_ollama_settings(_require_dict(config, "ollama")),
        openai=_load_openai_settings(_require_dict(config, "openai")),
        dummy=DummyResponseGeneratorSettings(
            enabled=_require_bool(_require_dict(config, "dummy"), "enabled"),
        ),
    )


def _load_ollama_settings(config: dict[str, Any]) -> OllamaSettings:
    return OllamaSettings(
        model=_require_string(config, "model"),
        api_url=_require_string(config, "api_url"),
        timeout_seconds=_require_float(config, "timeout_seconds"),
        fallback_response=_require_string(config, "fallback_response"),
    )


def _load_openai_settings(config: dict[str, Any]) -> OpenAISettings:
    return OpenAISettings(
        model=_require_string(config, "model"),
        api_key_env=_require_string(config, "api_key_env"),
        timeout_seconds=_require_float(config, "timeout_seconds"),
        fallback_response=_require_string(config, "fallback_response"),
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


def _require_optional_int(config: dict[str, Any], setting_path: str) -> int | None:
    value = _get_required_value(config, setting_path)

    if value is None:
        return None

    if not isinstance(value, int):
        raise RuntimeError(f"{setting_path} は整数または null で指定してください。")

    return value


def _get_required_value(config: dict[str, Any], setting_path: str) -> Any:
    current: Any = config

    for key in setting_path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise RuntimeError(f"必須設定が不足しています: {setting_path}")
        current = current[key]

    return current