from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObsAudioSourceState:
    source_name: str
    exists: bool
    muted: bool | None = None
    volume_db: float | None = None
    monitoring_type: str | None = None
    active: bool | None = None

    @property
    def usable(self) -> bool:
        return self.exists and self.muted is False and self.active is not False


@dataclass(frozen=True, slots=True)
class ObsSourceVisibility:
    source_name: str
    exists: bool
    visible: bool
    paths: tuple[str, ...] = ()
    ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class ObsInspection:
    obs_version: str
    websocket_version: str
    output_status: str
    scene_collection: str
    current_scene: str
    audio_sources: tuple[ObsAudioSourceState, ...]
    avatar: ObsSourceVisibility
