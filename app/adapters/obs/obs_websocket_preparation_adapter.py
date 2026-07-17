from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from app.adapters.obs.models import (
    ObsAudioSourceState,
    ObsInspection,
    ObsSourceVisibility,
)
from app.adapters.obs.obs_error_mapper import ObsAdapterError, ObsErrorMapper
from app.adapters.obs.obs_status_mapper import ObsStatusMapper
from app.adapters.obs.obs_websocket_client_factory import (
    ObsRequestClient,
    ObsWebSocketClientFactory,
)
from app.domain.streaming import ObsPreparationSnapshot


@dataclass(frozen=True, slots=True)
class ObsWebSocketPreparationConfig:
    required_audio_sources: tuple[str, ...]
    optional_audio_sources: tuple[str, ...] = ()
    avatar_source_name: str | None = None
    low_volume_threshold_db: float = -60.0
    request_timeout_seconds: float = 5.0
    max_retries: int = 2
    retry_initial_delay_seconds: float = 0.5
    max_scene_depth: int = 8


class ObsWebSocketPreparationAdapter:
    """Read-only OBS WebSocket 5.x inspection adapter.

    obsws-python is synchronous. Each public operation runs one isolated client in
    asyncio.to_thread and disconnects it in finally; no client crosses thread boundaries.
    """

    adapter_type = "obs_websocket"

    def __init__(
        self,
        factory: ObsWebSocketClientFactory,
        config: ObsWebSocketPreparationConfig,
    ) -> None:
        self._factory = factory
        self._config = config

    async def connect(self) -> None:
        await self._run(lambda client: None)

    async def disconnect(self) -> None:
        # Clients are scoped to individual calls and disconnected in _inspect_once.
        return None

    async def health_check(self) -> bool:
        try:
            await self.connect()
            return True
        except ObsAdapterError:
            return False

    async def get_version(self) -> tuple[str, str]:
        value = await self._run(self._version)
        return value.obs_version, value.websocket_version

    async def get_output_status(self) -> str:
        return cast(ObsInspection, await self._run(self._output)).output_status

    async def get_current_scene(self) -> str:
        return cast(ObsInspection, await self._run(self._scenes)).current_scene

    async def get_current_scene_collection(self) -> str:
        return cast(ObsInspection, await self._run(self._scenes)).scene_collection

    async def get_audio_source_states(self) -> dict[str, bool]:
        inspection = await self._run(self._audio)
        return {item.source_name: item.usable for item in inspection.audio_sources}

    async def get_source_visibility(self, source_name: str) -> bool:
        inspection = await self._run(lambda client: self._visibility(client, source_name))
        return inspection.avatar.visible and not inspection.avatar.ambiguous

    async def get_avatar_source_visibility(self) -> bool:
        if self._config.avatar_source_name is None:
            return True
        return await self.get_source_visibility(self._config.avatar_source_name)

    async def snapshot(self) -> ObsPreparationSnapshot:
        inspection = await self._run(self._inspect)
        details = {
            item.source_name: {
                "exists": item.exists,
                "muted": item.muted,
                "volume_db": item.volume_db,
                "monitoring_type": item.monitoring_type,
                "active": item.active,
                "low_volume": (
                    item.volume_db is not None
                    and item.volume_db <= self._config.low_volume_threshold_db
                ),
            }
            for item in inspection.audio_sources
        }
        return ObsPreparationSnapshot(
            connected=True,
            output_status=inspection.output_status,
            current_scene=inspection.current_scene,
            current_scene_collection=inspection.scene_collection,
            audio_source_states={
                item.source_name: item.usable for item in inspection.audio_sources
            },
            avatar_source_visible=(inspection.avatar.visible and not inspection.avatar.ambiguous),
            obs_version=inspection.obs_version,
            websocket_version=inspection.websocket_version,
            audio_source_details=details,
            avatar_source_exists=inspection.avatar.exists,
            avatar_source_paths=inspection.avatar.paths,
            adapter_type=self.adapter_type,
        )

    async def _run(self, operation: Any) -> Any:
        attempts = self._config.max_retries + 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._with_client, operation),
                    timeout=self._config.request_timeout_seconds,
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as error:
                mapped = ObsAdapterError("timeout", "obs.request_timeout", True)
                if attempt + 1 >= attempts:
                    raise mapped from error
            except Exception as error:
                mapped = ObsErrorMapper.map(error)
                if not mapped.retryable or attempt + 1 >= attempts:
                    raise mapped from error
            await asyncio.sleep(self._config.retry_initial_delay_seconds * (2**attempt))
        raise AssertionError("unreachable")

    def _with_client(self, operation: Any) -> Any:
        client: ObsRequestClient | None = None
        try:
            client = self._factory.create()
            return operation(client)
        finally:
            if client is not None:
                client.disconnect()

    def _inspect(self, client: ObsRequestClient) -> ObsInspection:
        version = self._version(client)
        output = self._output(client)
        scenes = self._scenes(client)
        audio = self._audio(client)
        avatar = (
            self._visibility(client, self._config.avatar_source_name)
            if self._config.avatar_source_name
            else ObsInspection("", "", "", "", "", (), ObsSourceVisibility("", True, True))
        )
        return ObsInspection(
            version.obs_version,
            version.websocket_version,
            output.output_status,
            scenes.scene_collection,
            scenes.current_scene,
            audio.audio_sources,
            avatar.avatar,
        )

    def _version(self, client: ObsRequestClient) -> ObsInspection:
        response = client.get_version()
        rpc = int(getattr(response, "rpc_version", 0))
        if rpc < 1:
            raise ObsAdapterError("protocol_version", "obs.protocol_version_unsupported")
        return ObsInspection(
            str(getattr(response, "obs_version", "unknown")),
            str(getattr(response, "obs_web_socket_version", "unknown")),
            "",
            "",
            "",
            (),
            ObsSourceVisibility("", True, True),
        )

    def _output(self, client: ObsRequestClient) -> ObsInspection:
        status = ObsStatusMapper.output_status(client.get_stream_status())
        return ObsInspection("", "", status, "", "", (), ObsSourceVisibility("", True, True))

    def _scenes(self, client: ObsRequestClient) -> ObsInspection:
        collections = client.get_scene_collection_list()
        scene = client.get_current_program_scene()
        return ObsInspection(
            "",
            "",
            "",
            str(getattr(collections, "current_scene_collection_name", "")),
            str(getattr(scene, "current_program_scene_name", "")),
            (),
            ObsSourceVisibility("", True, True),
        )

    def _audio(self, client: ObsRequestClient) -> ObsInspection:
        inputs = getattr(client.get_input_list(), "inputs", [])
        names = {str(item.get("inputName", "")) for item in inputs}
        states: list[ObsAudioSourceState] = []
        names_to_check = dict.fromkeys(
            (*self._config.required_audio_sources, *self._config.optional_audio_sources)
        )
        for name in names_to_check:
            if name not in names:
                states.append(ObsAudioSourceState(name, False))
                continue
            mute = client.get_input_mute(name)
            volume = client.get_input_volume(name)
            monitor = client.get_input_audio_monitor_type(name)
            active = client.get_input_active(name)
            states.append(
                ObsAudioSourceState(
                    name,
                    True,
                    bool(getattr(mute, "input_muted", True)),
                    float(getattr(volume, "input_volume_db", -100.0)),
                    str(getattr(monitor, "monitor_type", "unknown")),
                    bool(getattr(active, "input_active", False)),
                )
            )
        return ObsInspection("", "", "", "", "", tuple(states), ObsSourceVisibility("", True, True))

    def _visibility(self, client: ObsRequestClient, source_name: str) -> ObsInspection:
        current = str(getattr(client.get_current_program_scene(), "current_program_scene_name", ""))
        matches: list[tuple[str, bool]] = []
        visited: set[str] = set()

        def walk(
            container: str,
            path: tuple[str, ...],
            depth: int,
            group: bool = False,
            parent_enabled: bool = True,
        ) -> None:
            if depth > self._config.max_scene_depth or container in visited:
                return
            visited.add(container)
            response = (
                client.get_group_scene_item_list(container)
                if group
                else client.get_scene_item_list(container)
            )
            for item in getattr(response, "scene_items", []):
                name = str(item.get("sourceName", ""))
                enabled = bool(item.get("sceneItemEnabled", False))
                item_path = (*path, name)
                effective_enabled = parent_enabled and enabled
                if name == source_name:
                    matches.append((" / ".join(item_path), effective_enabled))
                is_group = bool(item.get("isGroup", False))
                source_type = str(item.get("sourceType", ""))
                if is_group or source_type == "OBS_SOURCE_TYPE_SCENE":
                    walk(name, item_path, depth + 1, is_group, effective_enabled)

        walk(current, (current,), 0)
        visibility = ObsSourceVisibility(
            source_name,
            bool(matches),
            any(enabled for _, enabled in matches),
            tuple(path for path, _ in matches),
            len(matches) > 1,
        )
        return ObsInspection("", "", "", "", current, (), visibility)
