from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.streaming.health import utc_now


@dataclass(frozen=True, slots=True)
class ApproveStreamStartCommand:
    command_id: str
    trace_id: str
    session_id: str
    expected_state_version: int
    approved_by: str
    approved_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class StreamStartResult:
    session_id: str
    trace_id: str
    command_id: str
    status: str
    successful: bool
    failed_step: str | None
    obs_status: str
    youtube_stream_status: str
    youtube_broadcast_status: str
    failure_code: str | None
    manual_intervention_required: bool
    started_at: datetime
    completed_at: datetime
    duplicate: bool = False


class StreamStartRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
