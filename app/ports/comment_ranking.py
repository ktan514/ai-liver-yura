from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.plugins.youtube_streaming.domain import CommentCandidate
from app.plugins.youtube_streaming.domain.comment_ranking import (
    CommentResponseTarget,
    RankedCommentCandidate,
)


@dataclass(frozen=True, slots=True)
class SemanticRankingScores:
    relevance: float
    conversation_fit: float
    novelty: float


class CommentSemanticRankingPort(Protocol):
    async def score(
        self, sanitized_text: str, topic: str, recent_utterance: str
    ) -> SemanticRankingScores: ...


class CommentCandidateRepository(Protocol):
    @property
    def dropped_count(self) -> int: ...

    @property
    def expired_count(self) -> int: ...

    def add(self, candidate: CommentCandidate) -> None: ...
    def valid(
        self, session_id: str, expires_before: datetime
    ) -> tuple[CommentCandidate, ...]: ...
    def mark(self, session_id: str, candidate_id: str, status: str) -> None: ...


class CommentRankingRepository(Protocol):
    def save(
        self, session_id: str, values: tuple[RankedCommentCandidate, ...]
    ) -> None: ...
    def latest(self, session_id: str) -> tuple[RankedCommentCandidate, ...]: ...


class CommentSelectionRepository(Protocol):
    def reserve(self, target: CommentResponseTarget) -> bool: ...
    def current(self, session_id: str) -> CommentResponseTarget | None: ...
    def get(self, selection_id: str) -> CommentResponseTarget | None: ...
    def reserve_released(
        self, selection_id: str, expires_at: datetime
    ) -> CommentResponseTarget | None: ...
    def transition(
        self, selection_id: str, status: str
    ) -> CommentResponseTarget | None: ...
    def invalidate_session(self, session_id: str) -> None: ...


class CommentResponseHistoryRepository(Protocol):
    def record(
        self, session_id: str, author_id: str | None, text: str, message_type: str
    ) -> None: ...
    def recent(self, session_id: str) -> tuple[tuple[str | None, str, str], ...]: ...
