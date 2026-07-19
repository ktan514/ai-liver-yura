from __future__ import annotations

from datetime import datetime
from typing import Any

from app.plugins.youtube_streaming.domain import (
    YouTubeBroadcastStatus,
    YouTubeBroadcastSummary,
    YouTubeStreamStatus,
)

_BROADCAST_STATUS = {
    "created": YouTubeBroadcastStatus.CREATED,
    "ready": YouTubeBroadcastStatus.READY,
    "testing": YouTubeBroadcastStatus.TESTING,
    "live": YouTubeBroadcastStatus.LIVE,
    "complete": YouTubeBroadcastStatus.COMPLETE,
    "revoked": YouTubeBroadcastStatus.REVOKED,
    "testStarting": YouTubeBroadcastStatus.TESTING,
    "liveStarting": YouTubeBroadcastStatus.TESTING,
    "completeStarting": YouTubeBroadcastStatus.LIVE,
}

_STREAM_STATUS = {
    "inactive": YouTubeStreamStatus.INACTIVE,
    "ready": YouTubeStreamStatus.READY,
    "active": YouTubeStreamStatus.ACTIVE,
    "error": YouTubeStreamStatus.ERROR,
    "created": YouTubeStreamStatus.INACTIVE,
}

_STREAM_HEALTH = {
    "good": "healthy",
    "ok": "healthy",
    "bad": "unavailable",
    "noData": "degraded",
}


def map_broadcast_status(value: object) -> YouTubeBroadcastStatus:
    return _BROADCAST_STATUS.get(str(value), YouTubeBroadcastStatus.UNKNOWN)


def map_stream_status(value: object) -> YouTubeStreamStatus:
    return _STREAM_STATUS.get(str(value), YouTubeStreamStatus.UNKNOWN)


def map_stream_health(value: object) -> str:
    return _STREAM_HEALTH.get(str(value), "unknown")


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def map_broadcast(
    item: dict[str, Any], *, allow_live_broadcast: bool
) -> YouTubeBroadcastSummary:
    broadcast_id = item.get("id")
    snippet = item.get("snippet")
    status_data = item.get("status")
    content_details = item.get("contentDetails")
    if not isinstance(broadcast_id, str) or not isinstance(snippet, dict):
        raise ValueError("Broadcast responseにidまたはsnippetがありません。")
    if not isinstance(status_data, dict):
        status_data = {}
    if not isinstance(content_details, dict):
        content_details = {}
    lifecycle = map_broadcast_status(status_data.get("lifeCycleStatus"))
    selectable_states = {
        YouTubeBroadcastStatus.CREATED,
        YouTubeBroadcastStatus.READY,
        YouTubeBroadcastStatus.TESTING,
    }
    if allow_live_broadcast:
        selectable_states.add(YouTubeBroadcastStatus.LIVE)
    return YouTubeBroadcastSummary(
        broadcast_id=broadcast_id,
        title=str(snippet.get("title") or "(無題)"),
        scheduled_start_at=parse_datetime(snippet.get("scheduledStartTime")),
        privacy_status=str(status_data.get("privacyStatus") or "unknown"),
        lifecycle_status=lifecycle.value,
        actual_start_at=parse_datetime(snippet.get("actualStartTime")),
        actual_end_at=parse_datetime(snippet.get("actualEndTime")),
        live_chat_id=(
            snippet.get("liveChatId")
            if isinstance(snippet.get("liveChatId"), str)
            else None
        ),
        bound_stream_id=(
            content_details.get("boundStreamId")
            if isinstance(content_details.get("boundStreamId"), str)
            else None
        ),
        selectable=lifecycle in selectable_states,
    )
