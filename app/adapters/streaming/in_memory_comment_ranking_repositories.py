from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import replace
from datetime import datetime, timezone

from app.plugins.youtube_streaming.domain import CommentCandidate
from app.plugins.youtube_streaming.domain.comment_ranking import (
    CommentResponseTarget,
    RankedCommentCandidate,
)


class InMemoryCommentCandidateRepository:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._items: OrderedDict[tuple[str, str], tuple[CommentCandidate, str]] = (
            OrderedDict()
        )
        self.dropped_count = 0
        self.expired_count = 0

    def add(self, candidate: CommentCandidate) -> None:
        key = (candidate.session_id, candidate.candidate_id)
        if key in self._items:
            return
        self._items[key] = (candidate, "pending")
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)
            self.dropped_count += 1

    def valid(
        self, session_id: str, expires_before: datetime
    ) -> tuple[CommentCandidate, ...]:
        result = []
        for key, (candidate, status) in tuple(self._items.items()):
            if candidate.session_id != session_id or status not in {
                "pending",
                "ranked",
            }:
                continue
            if candidate.eligible_at < expires_before:
                self._items[key] = (candidate, "expired")
                self.expired_count += 1
            else:
                result.append(candidate)
        return tuple(result)

    def mark(self, session_id: str, candidate_id: str, status: str) -> None:
        key = (session_id, candidate_id)
        value = self._items.get(key)
        if value is not None:
            self._items[key] = (value[0], status)


class InMemoryCommentRankingRepository:
    def __init__(self, capacity: int = 500) -> None:
        self._runs: deque[tuple[str, tuple[RankedCommentCandidate, ...]]] = deque(
            maxlen=capacity
        )

    def save(self, session_id: str, values: tuple[RankedCommentCandidate, ...]) -> None:
        self._runs.append((session_id, values))

    def latest(self, session_id: str) -> tuple[RankedCommentCandidate, ...]:
        return next(
            (values for key, values in reversed(self._runs) if key == session_id), ()
        )


class InMemoryCommentSelectionRepository:
    def __init__(self, capacity: int = 500) -> None:
        self._items: OrderedDict[str, CommentResponseTarget] = OrderedDict()
        self._candidate_index: set[tuple[str, str]] = set()
        self._capacity = capacity

    def reserve(self, target: CommentResponseTarget) -> bool:
        key = (target.session_id, target.candidate_id)
        if key in self._candidate_index:
            return False
        self._items[target.selection_id] = target
        self._candidate_index.add(key)
        while len(self._items) > self._capacity:
            _, old = self._items.popitem(last=False)
            self._candidate_index.discard((old.session_id, old.candidate_id))
        return True

    def current(self, session_id: str) -> CommentResponseTarget | None:
        now = datetime.now(timezone.utc)
        for selection_id, item in reversed(self._items.items()):
            if item.session_id != session_id or item.reservation_status != "reserved":
                continue
            if item.expires_at <= now:
                self._items[selection_id] = replace(item, reservation_status="expired")
                continue
            return item
        return None

    def get(self, selection_id: str) -> CommentResponseTarget | None:
        item = self._items.get(selection_id)
        if item is not None and item.reservation_status == "reserved":
            self.current(item.session_id)
        return self._items.get(selection_id)

    def reserve_released(
        self, selection_id: str, expires_at: datetime
    ) -> CommentResponseTarget | None:
        item = self._items.get(selection_id)
        if item is None or item.reservation_status != "released":
            return None
        updated = replace(item, reservation_status="reserved", expires_at=expires_at)
        self._items[selection_id] = updated
        self._candidate_index.add((item.session_id, item.candidate_id))
        return updated

    def transition(
        self, selection_id: str, status: str
    ) -> CommentResponseTarget | None:
        item = self._items.get(selection_id)
        if item is None or item.reservation_status != "reserved":
            return None
        updated = replace(item, reservation_status=status)
        self._items[selection_id] = updated
        if status == "released":
            self._candidate_index.discard((item.session_id, item.candidate_id))
        return updated

    def invalidate_session(self, session_id: str) -> None:
        for key, item in tuple(self._items.items()):
            if item.session_id == session_id and item.reservation_status == "reserved":
                self._items[key] = replace(item, reservation_status="expired")


class InMemoryCommentResponseHistoryRepository:
    def __init__(self, capacity: int = 100) -> None:
        self._items: dict[str, deque[tuple[str | None, str, str]]] = {}
        self._capacity = capacity

    def record(
        self, session_id: str, author_id: str | None, text: str, message_type: str
    ) -> None:
        history = self._items.setdefault(session_id, deque(maxlen=self._capacity))
        history.append((author_id, text, message_type))

    def recent(self, session_id: str) -> tuple[tuple[str | None, str, str], ...]:
        return tuple(self._items.get(session_id, ()))
