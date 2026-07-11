from dataclasses import replace
import pytest

from app.adapters.topic.llm_topic_classifier import LlmTopicClassifier
from app.adapters.embedding.openai_embedding_generator import OpenAIEmbeddingGenerator
from app.adapters.storage.postgres_topic_memory_store import PostgresTopicMemoryStore
from app.config.app_config import load_app_config
from app.runtime import RuntimeCoordinator, create_runtime_coordinator
from app.runtime.runtime_factory import (
    create_embedding_generator,
    create_topic_classifier,
    create_topic_memory_store,
)


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


def test_create_topic_classifier_returns_llm_topic_classifier_when_response_generator_is_ollama() -> None:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="ollama"),
    )

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


def test_create_topic_classifier_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="openai"),
    )
    monkeypatch.delenv(config.response_generator.openai.api_key_env, raising=False)

    topic_classifier = create_topic_classifier(config)

    assert topic_classifier is None


def test_create_topic_classifier_returns_llm_topic_classifier_when_response_generator_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="openai"),
    )
    monkeypatch.setenv(config.response_generator.openai.api_key_env, "test-api-key")

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


# Helper functions for topic memory config manipulation
def _replace_topic_memory_enabled(config, enabled: bool):
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=enabled),
        ),
    )


def _replace_topic_memory_embedding_type(config, embedding_type: str):
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(
                config.memory.topic_memory,
                embedding=replace(
                    config.memory.topic_memory.embedding,
                    type=embedding_type,
                ),
            ),
        ),
    )


def _replace_topic_memory_database_type(config, database_type: str):
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(
                config.memory.topic_memory,
                database=replace(
                    config.memory.topic_memory.database,
                    type=database_type,
                ),
            ),
        ),
    )


def test_create_embedding_generator_returns_none_when_topic_memory_is_disabled() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_embedding_type_is_unsupported() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_embedding_type(config, embedding_type="unsupported")

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.delenv(config.memory.topic_memory.embedding.api_key_env, raising=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_openai_embedding_generator_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(config.memory.topic_memory.embedding.api_key_env, "test-api-key")

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
    monkeypatch.delenv(config.memory.topic_memory.database.dsn_env, raising=False)

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_postgres_topic_memory_store_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(
        config.memory.topic_memory.database.dsn_env,
        "postgresql://user:password@localhost:5432/ai_liver_test",
    )

    topic_memory_store = create_topic_memory_store(config)

    assert isinstance(topic_memory_store, PostgresTopicMemoryStore)