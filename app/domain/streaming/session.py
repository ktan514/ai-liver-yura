from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.domain.streaming.health import HealthCheckItem, utc_now


class StreamSessionStatus(str, Enum):
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"


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
    StreamSessionStatus.READY: {StreamSessionStatus.PREPARING},
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

    @property
    def can_start(self) -> bool:
        return self.status == StreamSessionStatus.READY and self.readiness == StreamReadiness.READY

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
    ) -> StreamSession:
        if status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"不正なStreamSession遷移です: {self.status.value} -> {status.value}")
        readiness = (
            StreamReadiness.READY
            if status == StreamSessionStatus.READY
            else StreamReadiness.NOT_READY
            if status == StreamSessionStatus.FAILED
            else StreamReadiness.UNKNOWN
        )
        return replace(
            self,
            trace_id=trace_id or self.trace_id,
            selected_stream_id=selected_stream_id or self.selected_stream_id,
            live_chat_id=live_chat_id if live_chat_id is not None else self.live_chat_id,
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
        )
