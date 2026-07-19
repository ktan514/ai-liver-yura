from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class SituationState:
    """本文を保持せず、現在観測している状況を継続するCore状態。"""

    last_event_id: str | None = None
    last_event_type: str | None = None
    last_event_at: datetime | None = None
    input_source: str | None = None
    input_authority_role: str | None = None
    attention_target: str | None = None
    active_activity_id: str | None = None
    active_activity_type: str | None = None
    pending_activity_count: int = 0
    suspended_activity_count: int = 0
    ongoing_activity_id: str | None = None
    ongoing_activity_type: str | None = None
    ongoing_activity_status: str | None = None
    updated_at: datetime = datetime.min.replace(tzinfo=timezone.utc)

    def __post_init__(self) -> None:
        if self.pending_activity_count < 0 or self.suspended_activity_count < 0:
            raise ValueError("Activity countは0以上にしてください。")

    def observe_event(
        self,
        *,
        event_id: str,
        event_type: str,
        occurred_at: datetime,
        input_source: str | None,
        input_authority_role: str | None = None,
        attention_target: str | None,
    ) -> SituationState:
        return replace(
            self,
            last_event_id=event_id,
            last_event_type=event_type,
            last_event_at=occurred_at,
            input_source=input_source,
            input_authority_role=input_authority_role,
            attention_target=attention_target or self.attention_target,
            updated_at=max(self.updated_at, occurred_at),
        )

    def with_activity_snapshot(
        self,
        *,
        active_activity_id: str | None,
        active_activity_type: str | None,
        pending_activity_count: int,
        suspended_activity_count: int,
        ongoing_activity_id: str | None,
        ongoing_activity_type: str | None,
        ongoing_activity_status: str | None,
    ) -> SituationState:
        now = datetime.now(timezone.utc)
        return replace(
            self,
            active_activity_id=active_activity_id,
            active_activity_type=active_activity_type,
            pending_activity_count=pending_activity_count,
            suspended_activity_count=suspended_activity_count,
            ongoing_activity_id=ongoing_activity_id,
            ongoing_activity_type=ongoing_activity_type,
            ongoing_activity_status=ongoing_activity_status,
            updated_at=max(self.updated_at, now),
        )

    def as_context(self) -> dict[str, object]:
        return {
            "last_event_id": self.last_event_id,
            "last_event_type": self.last_event_type,
            "last_event_at": (
                self.last_event_at.isoformat()
                if self.last_event_at is not None
                else None
            ),
            "input_source": self.input_source,
            "input_authority_role": self.input_authority_role,
            "attention_target": self.attention_target,
            "active_activity_id": self.active_activity_id,
            "active_activity_type": self.active_activity_type,
            "pending_activity_count": self.pending_activity_count,
            "suspended_activity_count": self.suspended_activity_count,
            "ongoing_activity_id": self.ongoing_activity_id,
            "ongoing_activity_type": self.ongoing_activity_type,
            "ongoing_activity_status": self.ongoing_activity_status,
        }
