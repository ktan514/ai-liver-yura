from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.streaming.health import utc_now


@dataclass(frozen=True, slots=True)
class StreamPreparationCommand:
    command_id: str
    trace_id: str
    session_id: str
    selected_broadcast_id: str
    requested_at: datetime = field(default_factory=utc_now)
    requested_by: str = "pyqt_management_ui"
    expected_state_version: int = 0
    run_of_show_id: str = "default"


@dataclass(frozen=True, slots=True)
class YouTubeBroadcastSummary:
    broadcast_id: str
    title: str
    scheduled_start_at: datetime | None = None
    privacy_status: str = "private"
    lifecycle_status: str = "ready"
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    live_chat_id: str | None = None
    bound_stream_id: str | None = None
    selectable: bool = True


@dataclass(frozen=True, slots=True)
class YouTubeStreamSnapshot:
    stream_id: str
    status: str
    bound: bool
    live_chat_id: str | None = None
    ingestion_type: str | None = None
    health_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class ObsPreparationSnapshot:
    connected: bool
    output_status: str
    current_scene: str
    current_scene_collection: str
    audio_source_states: dict[str, bool]
    avatar_source_visible: bool
