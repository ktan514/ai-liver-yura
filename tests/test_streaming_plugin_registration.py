from __future__ import annotations

import pytest

from app.bootstrap import compose_streaming
from app.config.app_config import load_app_config
from app.runtime.runtime_factory import (
    create_stream_preparation_runtime,
    create_streaming_demo_config,
)


def test_streaming_plugin_exposes_commands_queries_and_demo_capability_conditionally() -> None:
    config = load_app_config()
    plugin_config = config.plugins.registrations["youtube_streaming"]
    assert plugin_config.enabled is True
    assert plugin_config.config_reference == "streaming"
    standard_runtime = create_stream_preparation_runtime(config)
    standard = compose_streaming(standard_runtime)
    registration = standard.registry.registration("youtube_streaming")
    assert registration is not None
    assert "stream.session.prepare" in registration.commands
    assert "stream.session.approve_start" in registration.commands
    assert "stream.end.normal" in registration.commands
    assert "stream.end.emergency" in registration.commands
    assert "stream.broadcast.list" in registration.queries
    assert "stream.run_of_show.list" in registration.queries
    assert "stream.session.status.get" in registration.queries
    assert "stream.comment_pipeline.status.get" in registration.queries
    assert "stream.activity.opening" in registration.activity_providers
    assert "demo.live_chat.submit" not in registration.commands

    demo_config = create_streaming_demo_config(load_app_config())
    demo = compose_streaming(
        create_stream_preparation_runtime(demo_config), demo_mode=True
    )
    demo_registration = demo.registry.registration("youtube_streaming")
    assert demo_registration is not None
    assert "demo.live_chat.submit" in demo_registration.commands


@pytest.mark.asyncio
async def test_streaming_lifecycle_is_managed_only_by_generic_registry() -> None:
    runtime = create_stream_preparation_runtime(load_app_config())
    composition = compose_streaming(runtime)
    await composition.registry.start_all()
    health = await composition.registry.health()
    assert health["youtube_streaming"].status.value == "healthy"
    await composition.registry.stop_all()
    await composition.registry.stop_all()
    assert (await composition.registry.health())["youtube_streaming"].status.value == "stopped"
