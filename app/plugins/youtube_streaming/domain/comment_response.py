from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.plugins.youtube_streaming.domain.health import utc_now


class StreamCommentResponseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_OUTPUT = "waiting_for_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


_TRANSITIONS = {
    StreamCommentResponseStatus.PENDING: {
        StreamCommentResponseStatus.RUNNING,
        StreamCommentResponseStatus.CANCELED,
    },
    StreamCommentResponseStatus.RUNNING: {
        StreamCommentResponseStatus.WAITING_FOR_OUTPUT,
        StreamCommentResponseStatus.FAILED,
        StreamCommentResponseStatus.CANCELED,
    },
    StreamCommentResponseStatus.WAITING_FOR_OUTPUT: {
        StreamCommentResponseStatus.COMPLETED,
        StreamCommentResponseStatus.FAILED,
        StreamCommentResponseStatus.CANCELED,
    },
    StreamCommentResponseStatus.FAILED: {StreamCommentResponseStatus.RUNNING},
    StreamCommentResponseStatus.COMPLETED: set(),
    StreamCommentResponseStatus.CANCELED: set(),
}


@dataclass(frozen=True, slots=True)
class StreamCommentResponseActivity:
    session_id: str
    trace_id: str
    selection_id: str
    candidate_id: str
    activity_id: str = field(default_factory=lambda: str(uuid4()))
    status: StreamCommentResponseStatus = StreamCommentResponseStatus.PENDING
    attempt: int = 0
    version: int = 0
    failure_code: str | None = None
    retryable: bool = False
    result: dict[str, object] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def transition(
        self,
        status: StreamCommentResponseStatus,
        *,
        failure_code: str | None = None,
        retryable: bool = False,
        result: dict[str, object] | None = None,
    ) -> StreamCommentResponseActivity:
        if status not in _TRANSITIONS[self.status]:
            raise ValueError(
                f"invalid comment response transition: {self.status} -> {status}"
            )
        now = utc_now()
        return replace(
            self,
            status=status,
            attempt=self.attempt + (status == StreamCommentResponseStatus.RUNNING),
            version=self.version + 1,
            failure_code=failure_code,
            retryable=retryable,
            result=result if result is not None else self.result,
            started_at=(
                now
                if status == StreamCommentResponseStatus.RUNNING
                else self.started_at
            ),
            completed_at=(
                now
                if status
                in {
                    StreamCommentResponseStatus.COMPLETED,
                    StreamCommentResponseStatus.FAILED,
                    StreamCommentResponseStatus.CANCELED,
                }
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RetryCommentResponseCommand:
    command_id: str
    session_id: str
    activity_id: str
    selection_id: str
    expected_activity_version: int


@dataclass(frozen=True, slots=True)
class CommentResponseHistoryEntry:
    session_id: str
    selection_id: str
    candidate_id: str
    message_id: str
    author_id: str | None
    topic_id: str | None
    response_summary: str
    outcome: str
    response_id: str = field(default_factory=lambda: str(uuid4()))
    completed_at: datetime = field(default_factory=utc_now)


class CommentResponseRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
