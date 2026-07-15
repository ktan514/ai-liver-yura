from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.domain.behavior import ActivityPlan


class ConfirmationStatus(str, Enum):
    PENDING = "pending"
    RESOLVED_POSITIVE = "resolved_positive"
    RESOLVED_NEGATIVE = "resolved_negative"
    EXPIRED = "expired"
    CANCELED = "canceled"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ConfirmationType(str, Enum):
    CONFIRM_START_ACTIVITY = "confirm_start_activity"
    CONFIRM_STOP_ACTIVITY = "confirm_stop_activity"
    CONFIRM_SWITCH_ACTIVITY = "confirm_switch_activity"
    CONFIRM_CONTINUE_ACTIVITY = "confirm_continue_activity"
    CONFIRM_CONSTRAINTS = "confirm_constraints"
    CONFIRM_INTERPRETATION = "confirm_interpretation"


class ConfirmationResolutionKind(str, Enum):
    AFFIRMATIVE = "affirmative"
    NEGATIVE = "negative"
    CLARIFICATION = "clarification"
    NEW_REQUEST = "new_request"
    CANCEL = "cancel"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ConfirmationResolution:
    kind: ConfirmationResolutionKind
    confidence: float
    reason: str
    operation: str | None = None
    constraint_updates: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    confirmation_id: str
    source_event_id: str
    created_at: datetime
    expires_at: datetime
    status: ConfirmationStatus
    confirmation_type: ConfirmationType
    candidate_activity_type: str
    candidate_operation: str | None
    candidate_goal: str
    candidate_constraints: dict[str, object]
    candidate_confidence: float
    candidate_constraints_schema_version: str | None
    current_ongoing_activity_id: str | None
    question: str
    positive_resolution: str
    negative_resolution: str
    attempt_count: int
    max_attempts: int
    context_snapshot: dict[str, object]
    candidate_plan: ActivityPlan
    resolution_event_id: str | None = None
    resolution: ConfirmationResolutionKind | None = None
    activity_turn_id: str | None = None
    final_behavior_plan_id: str | None = None
    original_trace_id: str | None = None
    resolution_trace_id: str | None = None
    parent_trace_id: str | None = None

    @property
    def is_pending(self) -> bool:
        return self.status == ConfirmationStatus.PENDING
