from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.domain.streaming import ObsPreparationSnapshot


@dataclass(frozen=True, slots=True)
class FakeObsPreparationConfig:
    connected: bool = True
    output_status: str = "idle"
    current_scene: str = "Starting Soon"
    current_scene_collection: str = "AI Liver"
    audio_source_states: dict[str, bool] = field(default_factory=lambda: {"VOICEVOX": True})
    avatar_source_visible: bool = True
    latency_seconds: float = 0.0


class FakeObsPreparationAdapter:
    def __init__(self, config: FakeObsPreparationConfig) -> None:
        self._config = config

    async def _wait(self) -> None:
        if self._config.latency_seconds:
            await asyncio.sleep(self._config.latency_seconds)

    async def connect(self) -> None:
        await self._wait()
        if not self._config.connected:
            raise ConnectionError("OBS WebSocketへ接続できません。")

    async def health_check(self) -> bool:
        await self._wait()
        return self._config.connected

    async def get_output_status(self) -> str:
        await self._wait()
        return self._config.output_status

    async def get_current_scene(self) -> str:
        await self._wait()
        return self._config.current_scene

    async def get_current_scene_collection(self) -> str:
        await self._wait()
        return self._config.current_scene_collection

    async def get_audio_source_states(self) -> dict[str, bool]:
        await self._wait()
        return dict(self._config.audio_source_states)

    async def get_avatar_source_visibility(self) -> bool:
        await self._wait()
        return self._config.avatar_source_visible

    async def snapshot(self) -> ObsPreparationSnapshot:
        await self.connect()
        return ObsPreparationSnapshot(
            connected=self._config.connected,
            output_status=self._config.output_status,
            current_scene=self._config.current_scene,
            current_scene_collection=self._config.current_scene_collection,
            audio_source_states=dict(self._config.audio_source_states),
            avatar_source_visible=self._config.avatar_source_visible,
        )


class ObsWebSocketPreparationAdapter:
    """後続のobs-websocket実装用stub。開始・停止操作を契約に持たない。"""

    def __init__(self, *, websocket_url: str, password_env: str) -> None:
        self.websocket_url = websocket_url
        self.password_env = password_env

    async def _unavailable(self) -> None:
        raise RuntimeError("実OBS WebSocket Adapterは未実装です。")

    async def connect(self) -> None:
        await self._unavailable()

    async def health_check(self) -> bool:
        await self._unavailable()
        return False

    async def get_output_status(self) -> str:
        await self._unavailable()
        return "unknown"

    async def get_current_scene(self) -> str:
        await self._unavailable()
        return ""

    async def get_current_scene_collection(self) -> str:
        await self._unavailable()
        return ""

    async def get_audio_source_states(self) -> dict[str, bool]:
        await self._unavailable()
        return {}

    async def get_avatar_source_visibility(self) -> bool:
        await self._unavailable()
        return False

    async def snapshot(self) -> ObsPreparationSnapshot:
        await self._unavailable()
        raise AssertionError
