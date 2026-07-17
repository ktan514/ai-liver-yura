from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from app.domain.streaming.health import utc_now


class StreamMainSegmentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_OUTPUT = "waiting_for_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


_TRANSITIONS = {
    StreamMainSegmentStatus.PENDING: {
        StreamMainSegmentStatus.RUNNING,
        StreamMainSegmentStatus.CANCELED,
    },
    StreamMainSegmentStatus.RUNNING: {
        StreamMainSegmentStatus.WAITING_FOR_OUTPUT,
        StreamMainSegmentStatus.FAILED,
        StreamMainSegmentStatus.CANCELED,
    },
    StreamMainSegmentStatus.WAITING_FOR_OUTPUT: {
        StreamMainSegmentStatus.COMPLETED,
        StreamMainSegmentStatus.FAILED,
        StreamMainSegmentStatus.CANCELED,
    },
    StreamMainSegmentStatus.FAILED: {StreamMainSegmentStatus.RUNNING},
    StreamMainSegmentStatus.COMPLETED: set(),
    StreamMainSegmentStatus.CANCELED: set(),
}


@dataclass(frozen=True, slots=True)
class StreamMainSegmentActivity:
    session_id: str
    trace_id: str
    segment_id: str | None
    segment_index: int | None
    segment_title: str | None = None
    topic: str | None = None
    activity_id: str = field(default_factory=lambda: str(uuid4()))
    status: StreamMainSegmentStatus = StreamMainSegmentStatus.PENDING
    attempt: int = 0
    result: dict[str, Any] | None = None
    failure_code: str | None = None
    retryable: bool = False
    manual_intervention_required: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    version: int = 0

    def transition(
        self,
        status: StreamMainSegmentStatus,
        *,
        failure_code: str | None = None,
        result: dict[str, Any] | None = None,
        topic: str | None = None,
        retryable: bool = False,
    ) -> StreamMainSegmentActivity:
        if status not in _TRANSITIONS[self.status]:
            raise ValueError(
                f"invalid main segment transition: {self.status.value} -> {status.value}"
            )
        now = utc_now()
        terminal = status in {
            StreamMainSegmentStatus.COMPLETED,
            StreamMainSegmentStatus.FAILED,
            StreamMainSegmentStatus.CANCELED,
        }
        return replace(
            self,
            status=status,
            attempt=self.attempt + 1 if status == StreamMainSegmentStatus.RUNNING else self.attempt,
            failure_code=failure_code,
            retryable=retryable,
            manual_intervention_required=status == StreamMainSegmentStatus.FAILED,
            started_at=now if status == StreamMainSegmentStatus.RUNNING else self.started_at,
            completed_at=now if terminal else None,
            result=result if result is not None else self.result,
            topic=topic or self.topic,
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class RetryMainSegmentCommand:
    command_id: str
    session_id: str
    activity_id: str
    expected_activity_version: int


class StreamMainSegmentRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
