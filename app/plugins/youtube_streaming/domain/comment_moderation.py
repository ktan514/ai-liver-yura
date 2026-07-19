from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.plugins.youtube_streaming.domain.health import utc_now


@dataclass(frozen=True, slots=True)
class CommentModerationDecision:
    session_id: str
    message_id: str
    status: str
    response_eligible: bool
    ranking_eligible: bool
    safety_category: str
    reason_codes: tuple[str, ...]
    severity: str
    confidence: float
    priority_hint: int
    requires_human_review: bool
    sanitized_text: str | None
    retryable: bool = False
    policy_version: str = "1"
    decision_id: str = field(default_factory=lambda: str(uuid4()))
    evaluated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class CommentCandidate:
    session_id: str
    message_id: str
    author_id: str | None
    sanitized_text: str
    message_type: str
    author_role: str
    is_paid: bool
    priority_hint: int
    moderation_decision_id: str
    published_at: str
    candidate_id: str = field(default_factory=lambda: str(uuid4()))
    eligible_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class CommentModerationStats:
    session_id: str
    evaluated_count: int = 0
    allowed: int = 0
    blocked: int = 0
    review: int = 0
    ignored: int = 0
    spam_count: int = 0
    unsafe_count: int = 0
    personal_data_count: int = 0
    queue_depth: int = 0
    last_evaluated_at: datetime | None = None
    failure_code: str | None = None
    lifecycle_stop_reason: str | None = None
