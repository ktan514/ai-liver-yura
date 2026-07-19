from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.plugins.youtube_streaming.domain.health import utc_now


class YouTubeAuthenticationStatus(str, Enum):
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_IN_PROGRESS = "authentication_in_progress"
    AUTHENTICATED = "authenticated"
    AUTHENTICATION_FAILED = "authentication_failed"


@dataclass(frozen=True, slots=True)
class YouTubeAuthenticationState:
    status: YouTubeAuthenticationStatus
    failure_reason: str | None = None
    observed_at: datetime = field(default_factory=utc_now)


class YouTubeBroadcastStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    TESTING = "testing"
    LIVE = "live"
    COMPLETE = "complete"
    REVOKED = "revoked"
    FAILED = "failed"
    UNKNOWN = "unknown"


class YouTubeStreamStatus(str, Enum):
    UNKNOWN = "unknown"
    INACTIVE = "inactive"
    READY = "ready"
    ACTIVE = "active"
    ERROR = "error"


class YouTubeLiveChatStatus(str, Enum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class YouTubeLiveChatSnapshot:
    status: YouTubeLiveChatStatus
    live_chat_id: str | None = None
    reason: str | None = None
