from __future__ import annotations

from dataclasses import replace

import pytest

from app.config.app_config import load_app_config
from app.runtime.runtime_factory import create_stream_preparation_runtime


@pytest.mark.asyncio
async def test_factory_uses_fake_services_without_real_connection() -> None:
    config = load_app_config()
    runtime = create_stream_preparation_runtime(config)
    broadcasts = await runtime.usecase.list_broadcasts()
    assert broadcasts[0].broadcast_id == config.streaming.fake.broadcast_id
    assert runtime.capability_registry.is_available("stream.session.prepare")


def test_streaming_config_keeps_secret_references_only() -> None:
    config = load_app_config()
    youtube = config.services["youtube"]
    obs = config.services["obs"]
    assert youtube.client_secret_path_env == "YOUTUBE_CLIENT_SECRET_PATH"
    assert youtube.token_path_env == "YOUTUBE_TOKEN_PATH"
    assert obs.password_env == "OBS_WEBSOCKET_PASSWORD"
    assert config.streaming.readiness.require_avatar is False


@pytest.mark.asyncio
async def test_google_factory_keeps_runtime_alive_when_env_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRET_PATH", raising=False)
    monkeypatch.delenv("YOUTUBE_TOKEN_PATH", raising=False)
    config = load_app_config()
    services = dict(config.services)
    services["youtube"] = replace(services["youtube"], type="google")
    runtime = create_stream_preparation_runtime(replace(config, services=services))
    state = await runtime.usecase.get_youtube_authentication_state()
    assert state.status.value == "authentication_failed"
    assert runtime.capability_registry.is_available("youtube.authentication") is False
