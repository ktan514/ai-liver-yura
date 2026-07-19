from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.plugins.youtube_streaming.domain.health import HealthCheckItem, utc_now


class StreamSessionStatus(str, Enum):
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"
    START_APPROVED = "start_approved"
    STARTING = "starting"
    LIVE = "live"
    START_FAILED = "start_failed"
    ABORTED = "aborted"
    CLOSING_REQUESTED = "closing_requested"
    CLOSING = "closing"
    STOPPING = "stopping"
    COMPLETED = "completed"
    EMERGENCY_STOP_REQUESTED = "emergency_stop_requested"
    EMERGENCY_STOPPING = "emergency_stopping"
    EMERGENCY_STOPPED = "emergency_stopped"
    STOP_FAILED = "stop_failed"


class StreamReadiness(str, Enum):
    UNKNOWN = "unknown"
    READY = "ready"
    NOT_READY = "not_ready"


_ALLOWED_TRANSITIONS = {
    StreamSessionStatus.CREATED: {StreamSessionStatus.PREPARING},
    StreamSessionStatus.PREPARING: {
        StreamSessionStatus.READY,
        StreamSessionStatus.FAILED,
    },
    StreamSessionStatus.FAILED: {StreamSessionStatus.PREPARING},
    StreamSessionStatus.READY: {
        StreamSessionStatus.PREPARING,
        StreamSessionStatus.START_APPROVED,
    },
    StreamSessionStatus.START_APPROVED: {StreamSessionStatus.STARTING},
    StreamSessionStatus.STARTING: {
        StreamSessionStatus.LIVE,
        StreamSessionStatus.START_FAILED,
    },
    StreamSessionStatus.START_FAILED: {
        StreamSessionStatus.READY,
        StreamSessionStatus.ABORTED,
    },
    StreamSessionStatus.LIVE: {
        StreamSessionStatus.CLOSING_REQUESTED,
        StreamSessionStatus.EMERGENCY_STOP_REQUESTED,
    },
    StreamSessionStatus.CLOSING_REQUESTED: {
        StreamSessionStatus.CLOSING,
        StreamSessionStatus.EMERGENCY_STOP_REQUESTED,
    },
    StreamSessionStatus.CLOSING: {
        StreamSessionStatus.STOPPING,
        StreamSessionStatus.STOP_FAILED,
        StreamSessionStatus.EMERGENCY_STOP_REQUESTED,
    },
    StreamSessionStatus.STOPPING: {
        StreamSessionStatus.COMPLETED,
        StreamSessionStatus.STOP_FAILED,
        StreamSessionStatus.EMERGENCY_STOP_REQUESTED,
    },
    StreamSessionStatus.EMERGENCY_STOP_REQUESTED: {
        StreamSessionStatus.EMERGENCY_STOPPING
    },
    StreamSessionStatus.EMERGENCY_STOPPING: {
        StreamSessionStatus.EMERGENCY_STOPPED,
        StreamSessionStatus.STOP_FAILED,
    },
    StreamSessionStatus.STOP_FAILED: {
        StreamSessionStatus.STOPPING,
        StreamSessionStatus.EMERGENCY_STOP_REQUESTED,
    },
    StreamSessionStatus.COMPLETED: set(),
    StreamSessionStatus.EMERGENCY_STOPPED: set(),
    StreamSessionStatus.ABORTED: set(),
}


@dataclass(frozen=True, slots=True)
class StreamSession:
    trace_id: str
    selected_broadcast_id: str
    title: str
    session_id: str = field(default_factory=lambda: str(uuid4()))
    selected_stream_id: str | None = None
    live_chat_id: str | None = None
    status: StreamSessionStatus = StreamSessionStatus.CREATED
    health_snapshot: tuple[HealthCheckItem, ...] = ()
    readiness: StreamReadiness = StreamReadiness.UNKNOWN
    failure_reasons: tuple[str, ...] = ()
    run_of_show_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    state_version: int = 0
    start_approved_by: str | None = None
    start_approved_at: datetime | None = None
    opening_activity_id: str | None = None
    current_segment_id: str | None = None
    current_segment_activity_id: str | None = None

    @property
    def can_start(self) -> bool:
        return (
            self.status == StreamSessionStatus.READY
            and self.readiness == StreamReadiness.READY
        )

    def transition(
        self,
        status: StreamSessionStatus,
        *,
        trace_id: str | None = None,
        selected_stream_id: str | None = None,
        live_chat_id: str | None = None,
        health_snapshot: tuple[HealthCheckItem, ...] | None = None,
        failure_reasons: tuple[str, ...] | None = None,
        run_of_show_id: str | None = None,
        start_approved_by: str | None = None,
        start_approved_at: datetime | None = None,
    ) -> StreamSession:
        if status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(
                f"不正なStreamSession遷移です: {self.status.value} -> {status.value}"
            )
        readiness = (
            StreamReadiness.READY
            if status == StreamSessionStatus.READY
            else (
                StreamReadiness.NOT_READY
                if status == StreamSessionStatus.FAILED
                else StreamReadiness.UNKNOWN
            )
        )
        return replace(
            self,
            trace_id=trace_id or self.trace_id,
            selected_stream_id=selected_stream_id or self.selected_stream_id,
            live_chat_id=(
                live_chat_id if live_chat_id is not None else self.live_chat_id
            ),
            status=status,
            health_snapshot=(
                health_snapshot if health_snapshot is not None else self.health_snapshot
            ),
            readiness=readiness,
            failure_reasons=(
                failure_reasons if failure_reasons is not None else self.failure_reasons
            ),
            run_of_show_id=run_of_show_id or self.run_of_show_id,
            updated_at=utc_now(),
            state_version=self.state_version + 1,
            start_approved_by=start_approved_by or self.start_approved_by,
            start_approved_at=start_approved_at or self.start_approved_at,
        )

    def attach_opening(self, activity_id: str) -> StreamSession:
        if self.status != StreamSessionStatus.LIVE:
            raise ValueError("openingはlive Sessionへだけ関連付けできます。")
        if (
            self.opening_activity_id is not None
            and self.opening_activity_id != activity_id
        ):
            raise ValueError("opening Activityは関連付け済みです。")
        return replace(
            self,
            opening_activity_id=activity_id,
            updated_at=utc_now(),
            state_version=self.state_version + 1,
        )

    def attach_main_segment(self, segment_id: str, activity_id: str) -> StreamSession:
        if self.status != StreamSessionStatus.LIVE:
            raise ValueError("main Segmentはlive Sessionへだけ関連付けできます。")
        if (
            self.current_segment_activity_id
            and self.current_segment_activity_id != activity_id
        ):
            raise ValueError("main Segment Activityは関連付け済みです。")
        return replace(
            self,
            current_segment_id=segment_id,
            current_segment_activity_id=activity_id,
            updated_at=utc_now(),
            state_version=self.state_version + 1,
        )
