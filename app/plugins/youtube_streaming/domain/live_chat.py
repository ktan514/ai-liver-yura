"""YouTube live chat domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class LiveChatPollerState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    BACKING_OFF = "backing_off"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NormalizedLiveChatMessage:
    message_id: str
    session_id: str
    platform: str
    broadcast_id: str
    author_channel_id: str | None
    author_display_name: str
    author_role: str
    text: str | None
    published_at: datetime
    received_at: datetime
    message_type: str
    is_deleted: bool
    is_paid: bool
    amount_display: str | None
    currency: str | None
    raw_kind: str


@dataclass(frozen=True, slots=True)
class LiveChatPollingStatus:
    session_id: str
    status: str
    last_success_at: datetime | None = None
    last_message_at: datetime | None = None
    received_count: int = 0
    emitted_count: int = 0
    duplicate_count: int = 0
    dropped_count: int = 0
    current_interval_ms: int = 0
    attempt: int = 0
    failure_code: str | None = None
    retryable: bool = False
    lifecycle_stop_reason: str | None = None
