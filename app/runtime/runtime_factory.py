"""Compatibility imports for the Composition Root moved to ``app.bootstrap.runtime``.

New code must import factory functions from ``app.bootstrap`` or
``app.bootstrap.runtime``.  This module intentionally contains no concrete
Adapter or Plugin composition.
"""

from app.bootstrap.runtime import (
    StreamPreparationRuntime,
    create_audio_player,
    create_character_profile,
    create_embedding_generator,
    create_llm_role_generator,
    create_memory_summary_generator,
    create_response_generator,
    create_runtime_coordinator,
    create_speech_synthesizer,
    create_stream_preparation_runtime,
    create_streaming_demo_config,
    create_topic_classifier,
    create_topic_memory_store,
)

__all__ = [
    "StreamPreparationRuntime",
    "create_audio_player",
    "create_character_profile",
    "create_embedding_generator",
    "create_llm_role_generator",
    "create_memory_summary_generator",
    "create_response_generator",
    "create_runtime_coordinator",
    "create_speech_synthesizer",
    "create_stream_preparation_runtime",
    "create_streaming_demo_config",
    "create_topic_classifier",
    "create_topic_memory_store",
]
