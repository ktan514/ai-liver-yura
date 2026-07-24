from __future__ import annotations

from datetime import datetime
from typing import Any

from app.plugins.youtube_streaming.domain import (
    HealthCheckItem,
    StreamSession,
    YouTubeBroadcastSummary,
)


def timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def health_item(item: HealthCheckItem) -> dict[str, Any]:
    return {
        "check_id": item.check_id,
        "display_key": item.check_id,
        "component": item.component,
        "status": item.status.value,
        "required": item.required,
        "summary_code": item.summary,
        "failure_code": item.failure_reason,
        "observed_at": timestamp(item.observed_at),
        "retryable": item.retryable,
        "metadata": dict(item.metadata),
    }


def broadcast(item: YouTubeBroadcastSummary) -> dict[str, Any]:
    scheduled = timestamp(item.scheduled_start_at)
    return {
        "broadcast_id": item.broadcast_id,
        "title": item.title,
        "scheduled_start_time": scheduled,
        "life_cycle_status": item.lifecycle_status,
        "privacy_status": item.privacy_status,
        "selectable": item.selectable,
        "bound_stream_id_present": item.bound_stream_id is not None,
        "live_chat_available": item.live_chat_id is not None,
        "display_label": f"{item.title} ({scheduled or '日時未設定'})",
    }


def session_snapshot(
    session: StreamSession, youtube_adapter_type: str, obs_adapter_type: str
) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "trace_id": session.trace_id,
        "status": session.status.value,
        "ready": session.can_start,
        "state_version": session.state_version,
        "broadcast_id": session.selected_broadcast_id,
        "run_of_show_id": session.run_of_show_id,
        "checks": [health_item(item) for item in session.health_snapshot],
        "failure_codes": list(session.failure_reasons),
        "observed_at": timestamp(session.updated_at),
        "adapter_modes": {"youtube": youtube_adapter_type, "obs": obs_adapter_type},
    }
