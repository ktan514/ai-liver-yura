from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from app.plugins.youtube_streaming.domain.health import utc_now


class StreamOpeningStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_OUTPUT = "waiting_for_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


_OPENING_TRANSITIONS = {
    StreamOpeningStatus.PENDING: {
        StreamOpeningStatus.RUNNING,
        StreamOpeningStatus.CANCELED,
    },
    StreamOpeningStatus.RUNNING: {
        StreamOpeningStatus.WAITING_FOR_OUTPUT,
        StreamOpeningStatus.FAILED,
        StreamOpeningStatus.CANCELED,
    },
    StreamOpeningStatus.WAITING_FOR_OUTPUT: {
        StreamOpeningStatus.COMPLETED,
        StreamOpeningStatus.FAILED,
        StreamOpeningStatus.CANCELED,
    },
    StreamOpeningStatus.FAILED: {StreamOpeningStatus.RUNNING},
    StreamOpeningStatus.COMPLETED: set(),
    StreamOpeningStatus.CANCELED: set(),
}


@dataclass(frozen=True, slots=True)
class StreamOpeningActivity:
    session_id: str
    trace_id: str
    segment_id: str | None
    activity_id: str = field(default_factory=lambda: str(uuid4()))
    status: StreamOpeningStatus = StreamOpeningStatus.PENDING
    attempt: int = 0
    failure_code: str | None = None
    manual_intervention_required: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    activity_turn_id: str | None = None
    result: dict[str, Any] | None = None
    version: int = 0

    def transition(
        self,
        status: StreamOpeningStatus,
        *,
        failure_code: str | None = None,
        activity_turn_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> StreamOpeningActivity:
        if status not in _OPENING_TRANSITIONS[self.status]:
            raise ValueError(
                f"invalid opening transition: {self.status.value} -> {status.value}"
            )
        now = utc_now()
        return replace(
            self,
            status=status,
            attempt=(
                self.attempt + 1
                if status == StreamOpeningStatus.RUNNING
                else self.attempt
            ),
            failure_code=failure_code,
            manual_intervention_required=status == StreamOpeningStatus.FAILED,
            started_at=(
                now if status == StreamOpeningStatus.RUNNING else self.started_at
            ),
            completed_at=(
                now
                if status
                in {
                    StreamOpeningStatus.COMPLETED,
                    StreamOpeningStatus.FAILED,
                    StreamOpeningStatus.CANCELED,
                }
                else None
            ),
            activity_turn_id=activity_turn_id or self.activity_turn_id,
            result=result if result is not None else self.result,
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class RetryOpeningCommand:
    command_id: str
    session_id: str
    expected_activity_version: int


class StreamOpeningRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
