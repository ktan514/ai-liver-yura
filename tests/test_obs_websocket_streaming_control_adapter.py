from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.obs import ObsAdapterError, ObsWebSocketStreamingControlAdapter
from app.core.contracts.plugins import CommandRejected
from app.plugins.youtube_streaming.public.registration import MethodHandler


class ControlClient:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.start_calls = 0
        self.stop_calls = 0
        self.disconnect_calls = 0

    def get_stream_status(self) -> Any:
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return SimpleNamespace(
            output_state={
                "idle": "OBS_WEBSOCKET_OUTPUT_STOPPED",
                "starting": "OBS_WEBSOCKET_OUTPUT_STARTING",
                "active": "OBS_WEBSOCKET_OUTPUT_STARTED",
                "stopping": "OBS_WEBSOCKET_OUTPUT_STOPPING",
            }.get(status, status),
            output_active=status in {"active", "stopping"},
            output_reconnecting=False,
        )

    def start_stream(self) -> None:
        self.start_calls += 1

    def stop_stream(self) -> None:
        self.stop_calls += 1

    def disconnect(self) -> None:
        self.disconnect_calls += 1


class ControlFactory:
    def __init__(self, value: ControlClient | Exception) -> None:
        self.value = value
        self.calls = 0

    def create(self) -> ControlClient:
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def control(
    client: ControlClient,
    *,
    state_timeout_seconds: float = 0.02,
) -> tuple[ObsWebSocketStreamingControlAdapter, ControlFactory]:
    factory = ControlFactory(client)
    return (
        ObsWebSocketStreamingControlAdapter(
            factory,  # type: ignore[arg-type]
            request_timeout_seconds=0.1,
            state_timeout_seconds=state_timeout_seconds,
            poll_interval_seconds=0,
        ),
        factory,
    )


@pytest.mark.asyncio
async def test_connect_is_reused_and_disconnect_is_idempotent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = ControlClient(["idle"])
    adapter, factory = control(client)
    with caplog.at_level(logging.INFO):
        await adapter.connect()
        await adapter.connect()
        assert await adapter.get_connection_status() == "connected"
        await adapter.disconnect()
        await adapter.disconnect()

    assert factory.calls == 1
    assert client.disconnect_calls == 1
    assert "connection established" in caplog.text
    assert "password" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_authentication_and_connection_failures_are_mapped() -> None:
    for error, code in (
        (RuntimeError("authentication password rejected"), "obs.authentication_failed"),
        (ConnectionRefusedError("refused"), "obs.connection_refused"),
    ):
        adapter = ObsWebSocketStreamingControlAdapter(
            ControlFactory(error),  # type: ignore[arg-type]
            request_timeout_seconds=0.1,
        )
        with pytest.raises(ObsAdapterError, match=code):
            await adapter.connect()
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_plugin_boundary_converts_obs_error_to_common_rejection() -> None:
    def fail(_: object) -> None:
        raise ObsAdapterError("authentication", "obs.authentication_failed")

    with pytest.raises(CommandRejected) as captured:
        await MethodHandler(fail).handle(None)

    assert captured.value.reason_code == "obs.authentication_failed"


@pytest.mark.asyncio
async def test_start_waits_for_active_and_is_idempotent() -> None:
    client = ControlClient(["idle", "starting", "active", "active"])
    adapter, factory = control(client)
    try:
        await adapter.start_stream()
        await adapter.start_stream()
        assert client.start_calls == 1
        assert factory.calls == 1
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_stop_waits_for_idle_and_is_idempotent() -> None:
    client = ControlClient(["active", "stopping", "idle", "idle"])
    adapter, _ = control(client)
    try:
        await adapter.stop_stream()
        await adapter.stop_stream()
        assert client.stop_calls == 1
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "statuses", "code"),
    [
        ("start", ["idle", "starting"], "obs.stream_start_timeout"),
        ("stop", ["active", "stopping"], "obs.stream_stop_timeout"),
    ],
)
async def test_state_transition_timeout_is_explicit(
    operation: str, statuses: list[str], code: str
) -> None:
    adapter, _ = control(ControlClient(statuses), state_timeout_seconds=0.001)
    try:
        with pytest.raises(ObsAdapterError, match=code):
            await getattr(adapter, f"{operation}_stream")()
    finally:
        await adapter.disconnect()
