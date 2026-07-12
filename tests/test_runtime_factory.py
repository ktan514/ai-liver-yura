from dataclasses import replace

import pytest

from app.adapters.embedding.openai_embedding_generator import OpenAIEmbeddingGenerator
from app.adapters.storage.postgres_topic_memory_store import PostgresTopicMemoryStore
from app.adapters.topic.llm_topic_classifier import LlmTopicClassifier
from app.adapters.tts import SystemAudioPlayer, VoiceVoxSpeechSynthesizer
from app.config.app_config import AppConfig, load_app_config
from app.runtime import RuntimeCoordinator, create_runtime_coordinator
from app.runtime.runtime_factory import (
    create_audio_player,
    create_embedding_generator,
    create_speech_synthesizer,
    create_topic_classifier,
    create_topic_memory_store,
)


def _required_env_name(value: str | None) -> str:
    assert value is not None
    return value


def _openai_api_key_env(config: AppConfig) -> str:
    return _required_env_name(config.services["openai"].api_key_env)


def _database_dsn_env(config: AppConfig) -> str:
    service = config.services[config.memory.topic_memory.database_service]
    return _required_env_name(service.dsn_env)


def test_create_voicevox_speech_components() -> None:
    config = load_app_config()

    synthesizer = create_speech_synthesizer(config)
    player = create_audio_player(config)

    assert isinstance(synthesizer, VoiceVoxSpeechSynthesizer)
    assert isinstance(player, SystemAudioPlayer)


def test_create_speech_components_returns_none_when_disabled() -> None:
    config = load_app_config()
    config = replace(config, speech=replace(config.speech, enabled=False))

    assert create_speech_synthesizer(config) is None
    assert create_audio_player(config) is None


def test_create_runtime_coordinator_returns_runtime_coordinator() -> None:
    config = load_app_config()

    runtime = create_runtime_coordinator(config)

    assert isinstance(runtime, RuntimeCoordinator)


def test_create_topic_classifier_returns_none_when_response_generator_is_dummy() -> None:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
    )

    topic_classifier = create_topic_classifier(config)

    assert topic_classifier is None


def test_create_topic_classifier_uses_ollama_model() -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="ollama_chat"),
    )

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


def test_create_topic_classifier_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="openai_chat"),
    )
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    topic_classifier = create_topic_classifier(config)

    assert topic_classifier is None


def test_create_topic_classifier_returns_llm_topic_classifier_when_response_generator_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="openai_chat"),
    )
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


# Helper functions for topic memory config manipulation
def _replace_topic_memory_enabled(config: AppConfig, enabled: bool) -> AppConfig:
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=enabled),
        ),
    )


def _replace_topic_memory_embedding_service(config: AppConfig, service: str) -> AppConfig:
    model_key = config.memory.topic_memory.embedding_model
    return replace(
        config,
        models={**config.models, model_key: replace(config.models[model_key], service=service)},
    )


def _replace_topic_memory_database_type(config: AppConfig, database_type: str) -> AppConfig:
    service_key = config.memory.topic_memory.database_service
    return replace(
        config,
        services={
            **config.services,
            service_key: replace(config.services[service_key], type=database_type),
        },
    )


def test_create_embedding_generator_returns_none_when_topic_memory_is_disabled() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_embedding_type_is_unsupported() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_embedding_service(config, service="topic_memory_database")

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_openai_embedding_generator_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    embedding_generator = create_embedding_generator(config)

    assert isinstance(embedding_generator, OpenAIEmbeddingGenerator)


def test_create_topic_memory_store_returns_none_when_topic_memory_is_disabled() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=False)

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_none_when_database_type_is_unsupported() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_database_type(config, database_type="unsupported")

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_none_when_database_dsn_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.delenv(_database_dsn_env(config), raising=False)

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_postgres_topic_memory_store_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(
        _database_dsn_env(config),
        "postgresql://user:password@localhost:5432/ai_liver_test",
    )

    topic_memory_store = create_topic_memory_store(config)

    assert isinstance(topic_memory_store, PostgresTopicMemoryStore)


def _replace_topic_memory_summary_type(config: AppConfig, summary_type: str) -> AppConfig:
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(
                config.memory.topic_memory,
                summary=replace(
                    config.memory.topic_memory.summary,
                    type=summary_type,
                ),
            ),
        ),
    )


def test_create_memory_summary_generator_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.runtime.runtime_factory import create_memory_summary_generator

    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_summary_type(config, summary_type="llm")
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    memory_summary_generator = create_memory_summary_generator(config)

    assert memory_summary_generator is None


def test_create_memory_summary_generator_returns_llm_generator_when_response_generator_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.memory.llm_memory_summary_generator import LlmMemorySummaryGenerator
    from app.runtime.runtime_factory import create_memory_summary_generator

    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_summary_type(config, summary_type="llm")
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    memory_summary_generator = create_memory_summary_generator(config)

    assert isinstance(memory_summary_generator, LlmMemorySummaryGenerator)
