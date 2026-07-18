from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.obs import (
    ObsAdapterError,
    ObsErrorMapper,
    ObsStatusMapper,
    ObsWebSocketClientConfig,
    ObsWebSocketClientFactory,
    ObsWebSocketPreparationAdapter,
    ObsWebSocketPreparationConfig,
)


class FakeObsClient:
    def __init__(
        self,
        *,
        output_state: str = "OBS_WEBSOCKET_OUTPUT_STOPPED",
        output_active: bool = False,
        output_reconnecting: bool = False,
        scene_collection: str = "AI Liver",
        scene: str = "Starting Soon",
        inputs: tuple[str, ...] = ("VOICEVOX", "BGM"),
        muted: tuple[str, ...] = (),
        volume_db: float = -12.0,
        scene_items: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self.output_state = output_state
        self.output_active = output_active
        self.output_reconnecting = output_reconnecting
        self.scene_collection = scene_collection
        self.scene = scene
        self.inputs = inputs
        self.muted = muted
        self.volume_db = volume_db
        self.scene_items = scene_items or {
            "Starting Soon": [
                {
                    "sourceName": "Character Group",
                    "sceneItemEnabled": True,
                    "isGroup": True,
                }
            ],
            "Character Group": [{"sourceName": "Yura", "sceneItemEnabled": True, "isGroup": False}],
        }
        self.disconnect_calls = 0
        self.calls: list[str] = []

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def get_version(self) -> Any:
        self.calls.append("get_version")
        return SimpleNamespace(
            rpc_version=1,
            obs_version="31.0.0",
            obs_web_socket_version="5.6.2",
        )

    def get_stream_status(self) -> Any:
        self.calls.append("get_stream_status")
        return SimpleNamespace(
            output_state=self.output_state,
            output_active=self.output_active,
            output_reconnecting=self.output_reconnecting,
        )

    def get_scene_collection_list(self) -> Any:
        return SimpleNamespace(current_scene_collection_name=self.scene_collection)

    def get_current_program_scene(self) -> Any:
        return SimpleNamespace(current_program_scene_name=self.scene)

    def get_input_list(self) -> Any:
        return SimpleNamespace(inputs=[{"inputName": name} for name in self.inputs])

    def get_input_mute(self, name: str) -> Any:
        return SimpleNamespace(input_muted=name in self.muted)

    def get_input_volume(self, name: str) -> Any:
        return SimpleNamespace(input_volume_db=self.volume_db)

    def get_input_audio_monitor_type(self, name: str) -> Any:
        return SimpleNamespace(monitor_type="OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT")

    def get_input_active(self, name: str) -> Any:
        return SimpleNamespace(input_active=True)

    def get_scene_item_list(self, name: str) -> Any:
        return SimpleNamespace(scene_items=self.scene_items.get(name, []))

    def get_group_scene_item_list(self, name: str) -> Any:
        return SimpleNamespace(scene_items=self.scene_items.get(name, []))


class FakeFactory:
    def __init__(self, clients: list[FakeObsClient | Exception]) -> None:
        self.clients = clients
        self.calls = 0

    def create(self) -> FakeObsClient:
        value = self.clients[min(self.calls, len(self.clients) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


def adapter(client: FakeObsClient, **updates: object) -> ObsWebSocketPreparationAdapter:
    config = ObsWebSocketPreparationConfig(
        required_audio_sources=("VOICEVOX", "BGM"),
        avatar_source_name="Yura",
        retry_initial_delay_seconds=0.001,
        **updates,
    )
    return ObsWebSocketPreparationAdapter(FakeFactory([client]), config)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_snapshot_inspects_obs_without_write_requests() -> None:
    client = FakeObsClient()
    snapshot = await adapter(client).snapshot()
    assert snapshot.connected is True
    assert snapshot.output_status == "idle"
    assert snapshot.obs_version == "31.0.0"
    assert snapshot.websocket_version == "5.6.2"
    assert snapshot.audio_source_states == {"VOICEVOX": True, "BGM": True}
    assert snapshot.avatar_source_visible is True
    assert snapshot.avatar_source_paths == ("Starting Soon / Character Group / Yura",)
    assert client.disconnect_calls == 1
    assert not any(call.startswith(("start", "stop", "set")) for call in client.calls)


@pytest.mark.parametrize(
    ("state", "active", "reconnecting", "expected"),
    [
        ("OBS_WEBSOCKET_OUTPUT_STOPPED", False, False, "idle"),
        ("OBS_WEBSOCKET_OUTPUT_STARTING", False, False, "starting"),
        ("OBS_WEBSOCKET_OUTPUT_STARTED", True, False, "active"),
        ("OBS_WEBSOCKET_OUTPUT_STOPPING", True, False, "stopping"),
        ("", True, True, "reconnecting"),
        ("SOMETHING_NEW", False, False, "unknown"),
    ],
)
def test_output_status_mapping(state: str, active: bool, reconnecting: bool, expected: str) -> None:
    response = SimpleNamespace(
        output_state=state,
        output_active=active,
        output_reconnecting=reconnecting,
    )
    assert ObsStatusMapper.output_status(response) == expected


@pytest.mark.asyncio
async def test_missing_muted_and_low_volume_audio_are_preserved() -> None:
    client = FakeObsClient(inputs=("VOICEVOX",), muted=("VOICEVOX",), volume_db=-80.0)
    snapshot = await adapter(client).snapshot()
    assert snapshot.audio_source_states == {"VOICEVOX": False, "BGM": False}
    assert snapshot.audio_source_details["VOICEVOX"]["muted"] is True
    assert snapshot.audio_source_details["VOICEVOX"]["low_volume"] is True
    assert snapshot.audio_source_details["BGM"]["exists"] is False


@pytest.mark.asyncio
async def test_nested_cycle_is_bounded_and_duplicate_avatar_is_ambiguous() -> None:
    items = {
        "Starting Soon": [
            {"sourceName": "Loop", "sceneItemEnabled": True, "isGroup": True},
            {"sourceName": "Yura", "sceneItemEnabled": True, "isGroup": False},
        ],
        "Loop": [
            {
                "sourceName": "Starting Soon",
                "sceneItemEnabled": True,
                "isGroup": False,
                "sourceType": "OBS_SOURCE_TYPE_SCENE",
            },
            {"sourceName": "Yura", "sceneItemEnabled": True, "isGroup": False},
        ],
    }
    snapshot = await adapter(FakeObsClient(scene_items=items), max_scene_depth=3).snapshot()
    assert snapshot.avatar_source_visible is False
    assert len(snapshot.avatar_source_paths) == 2


@pytest.mark.asyncio
async def test_retryable_connection_error_retries_and_auth_does_not() -> None:
    client = FakeObsClient()
    factory = FakeFactory([ConnectionRefusedError(), client])
    value = ObsWebSocketPreparationAdapter(
        factory,  # type: ignore[arg-type]
        ObsWebSocketPreparationConfig((), max_retries=1, retry_initial_delay_seconds=0.001),
    )
    await value.connect()
    assert factory.calls == 2
    assert client.disconnect_calls == 1

    auth_factory = FakeFactory([RuntimeError("authentication password rejected")])
    auth_adapter = ObsWebSocketPreparationAdapter(
        auth_factory,  # type: ignore[arg-type]
        ObsWebSocketPreparationConfig((), max_retries=3, retry_initial_delay_seconds=0.001),
    )
    with pytest.raises(ObsAdapterError, match="obs.authentication_failed"):
        await auth_adapter.connect()
    assert auth_factory.calls == 1


def test_configuration_and_error_mapping_never_expose_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OBS_TEST_PASSWORD", raising=False)
    factory = ObsWebSocketClientFactory(
        ObsWebSocketClientConfig("127.0.0.1", 4455, "OBS_TEST_PASSWORD")
    )
    with pytest.raises(ObsAdapterError) as captured:
        factory.create()
    assert captured.value.category == "configuration"
    assert "OBS_TEST_PASSWORD" not in str(captured.value)
    assert ObsErrorMapper.map(TimeoutError()).retryable is True
    assert (
        ObsErrorMapper.map(
            RuntimeError("failed to identify client with the server, check connection settings")
        ).failure_code
        == "obs.authentication_failed"
    )
