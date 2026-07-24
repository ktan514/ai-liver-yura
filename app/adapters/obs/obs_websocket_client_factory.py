from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.adapters.obs.obs_error_mapper import ObsAdapterError


class ObsRequestClient(Protocol):
    def disconnect(self) -> None: ...
    def get_version(self) -> Any: ...
    def get_stream_status(self) -> Any: ...
    def get_scene_collection_list(self) -> Any: ...
    def get_current_program_scene(self) -> Any: ...
    def get_input_list(self) -> Any: ...
    def get_input_mute(self, name: str) -> Any: ...
    def get_input_volume(self, name: str) -> Any: ...
    def get_input_audio_monitor_type(self, name: str) -> Any: ...
    def get_input_active(self, name: str) -> Any: ...
    def get_scene_item_list(self, name: str) -> Any: ...
    def get_group_scene_item_list(self, name: str) -> Any: ...
    def start_stream(self) -> Any: ...
    def stop_stream(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class ObsWebSocketClientConfig:
    host: str
    port: int
    password_env: str
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 5.0

    def validate(self) -> None:
        if not self.host.strip():
            raise ObsAdapterError("configuration", "obs.configuration.host_missing")
        if not 1 <= self.port <= 65535:
            raise ObsAdapterError("configuration", "obs.configuration.port_invalid")
        if not self.password_env.strip():
            raise ObsAdapterError(
                "configuration", "obs.configuration.password_env_missing"
            )
        if self.connect_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise ObsAdapterError("configuration", "obs.configuration.timeout_invalid")


class ObsWebSocketClientFactory:
    def __init__(self, config: ObsWebSocketClientConfig) -> None:
        self.config = config

    def create(self) -> ObsRequestClient:
        self.config.validate()
        password = os.getenv(self.config.password_env)
        if not password:
            raise ObsAdapterError("configuration", "obs.configuration.password_missing")
        # obsws-python logs connection kwargs at INFO; suppress that logger so secrets cannot leak.
        logging.getLogger("obsws_python").setLevel(logging.WARNING)
        import obsws_python as obs  # type: ignore[import-untyped]

        return cast(
            ObsRequestClient,
            obs.ReqClient(
                host=self.config.host,
                port=self.config.port,
                password=password,
                timeout=max(
                    self.config.connect_timeout_seconds,
                    self.config.request_timeout_seconds,
                ),
            ),
        )
