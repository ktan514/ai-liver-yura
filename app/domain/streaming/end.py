from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.domain.streaming.health import utc_now


@dataclass(frozen=True, slots=True)
class ApproveNormalStreamEndCommand:
    command_id: str
    trace_id: str
    session_id: str
    expected_state_version: int
    approved_by: str
    approved_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class EmergencyStopStreamCommand:
    command_id: str
    trace_id: str
    session_id: str
    expected_state_version: int
    requested_by: str
    reason_code: str
    operator_note: str | None = None
    requested_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class StreamEndResult:
    session_id: str
    trace_id: str
    command_id: str
    end_mode: str
    successful: bool
    failed_step: str | None
    closing_status: str
    youtube_broadcast_status: str
    youtube_stream_status: str
    obs_output_status: str
    failure_code: str | None
    retryable: bool
    manual_intervention_required: bool
    started_at: datetime
    completed_at: datetime


class StreamEndRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class StreamClosingStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_OUTPUT = "waiting_for_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class StreamClosingActivity:
    session_id: str
    trace_id: str
    segment_id: str
    activity_id: str = field(default_factory=lambda: str(uuid4()))
    status: StreamClosingStatus = StreamClosingStatus.PENDING
    failure_code: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def with_status(
        self, status: StreamClosingStatus, failure_code: str | None = None
    ) -> StreamClosingActivity:
        now = utc_now()
        return replace(
            self,
            status=status,
            failure_code=failure_code,
            started_at=now if status == StreamClosingStatus.RUNNING else self.started_at,
            completed_at=now
            if status
            in {
                StreamClosingStatus.COMPLETED,
                StreamClosingStatus.FAILED,
                StreamClosingStatus.CANCELED,
            }
            else None,
        )
