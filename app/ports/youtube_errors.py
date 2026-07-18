from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class YouTubeApiErrorKind(str, Enum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMIT = "rate_limit"
    DAILY_LIMIT = "daily_limit"
    UNKNOWN_QUOTA = "unknown_quota"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True, slots=True)
class YouTubeApiError(RuntimeError):
    kind: YouTubeApiErrorKind
    safe_message: str
    retryable: bool = False
    http_status: int | None = None
    api_reason: str | None = None

    def __str__(self) -> str:
        return self.safe_message

