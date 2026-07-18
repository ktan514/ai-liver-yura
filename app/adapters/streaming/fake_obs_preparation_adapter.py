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
    adapter_type = "fake"

    def __init__(self, config: FakeObsPreparationConfig) -> None:
        self._config = config

    async def _wait(self) -> None:
        if self._config.latency_seconds:
            await asyncio.sleep(self._config.latency_seconds)

    async def connect(self) -> None:
        await self._wait()
        if not self._config.connected:
            raise ConnectionError("OBS WebSocketへ接続できません。")

    async def disconnect(self) -> None:
        return None

    async def get_version(self) -> tuple[str, str]:
        return "fake", "5.x-fake"

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

    async def get_source_visibility(self, source_name: str) -> bool:
        del source_name
        return await self.get_avatar_source_visibility()

    async def snapshot(self) -> ObsPreparationSnapshot:
        await self.connect()
        return ObsPreparationSnapshot(
            connected=self._config.connected,
            output_status=self._config.output_status,
            current_scene=self._config.current_scene,
            current_scene_collection=self._config.current_scene_collection,
            audio_source_states=dict(self._config.audio_source_states),
            avatar_source_visible=self._config.avatar_source_visible,
            obs_version="fake",
            websocket_version="5.x-fake",
            adapter_type=self.adapter_type,
        )


class DisabledObsPreparationAdapter(FakeObsPreparationAdapter):
    adapter_type = "disabled"

    def __init__(self) -> None:
        super().__init__(FakeObsPreparationConfig(connected=False, output_status="unknown"))

    async def connect(self) -> None:
        return None

    async def snapshot(self) -> ObsPreparationSnapshot:
        return ObsPreparationSnapshot(
            connected=False,
            output_status="unknown",
            current_scene="",
            current_scene_collection="",
            audio_source_states={},
            avatar_source_visible=False,
            adapter_type=self.adapter_type,
        )
