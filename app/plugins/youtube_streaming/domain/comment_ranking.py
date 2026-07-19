from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.plugins.youtube_streaming.domain.health import utc_now


@dataclass(frozen=True, slots=True)
class CommentRankingContext:
    current_segment: str = "main"
    current_topic: str = ""
    recent_agent_utterance: str = ""
    speech_idle: bool = True
    activity_interruptible: bool = True


@dataclass(frozen=True, slots=True)
class CommentRankingFeature:
    candidate_id: str
    recency_score: float
    relevance_score: float
    novelty_score: float
    conversation_fit_score: float
    engagement_score: float
    author_fairness_score: float
    diversity_score: float
    priority_adjustment: float
    safety_adjustment: float = 0.0
    repetition_penalty: float = 0.0
    interruption_penalty: float = 0.0


@dataclass(frozen=True, slots=True)
class RankedCommentCandidate:
    candidate_id: str
    total_score: float
    feature_scores: CommentRankingFeature
    rank: int
    eligible: bool
    exclusion_reasons: tuple[str, ...]
    fallback_used: bool = False
    policy_version: str = "1"
    ranked_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class CommentResponseTarget:
    session_id: str
    candidate_id: str
    message_id: str
    author_id: str | None
    sanitized_text: str
    selected_score: float
    selected_rank: int
    selection_reason: str
    selection_id: str = field(default_factory=lambda: str(uuid4()))
    selected_at: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=utc_now)
    reservation_status: str = "reserved"


@dataclass(frozen=True, slots=True)
class CommentRankingStats:
    session_id: str
    pool_size: int = 0
    ranked_count: int = 0
    selected_count: int = 0
    expired_count: int = 0
    dropped_count: int = 0
    last_ranking_at: datetime | None = None
    failure_code: str | None = None
    lifecycle_stop_reason: str | None = None
