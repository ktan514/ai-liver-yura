from __future__ import annotations

from collections import OrderedDict

from app.domain.streaming import CommentModerationDecision


class InMemoryCommentModerationRepository:
    def __init__(self, capacity: int = 10_000) -> None:
        self._capacity = capacity
        self._items: OrderedDict[tuple[str, str], CommentModerationDecision] = OrderedDict()

    def save_decision(self, decision: CommentModerationDecision) -> CommentModerationDecision:
        key = (decision.session_id, decision.message_id)
        existing = self._items.get(key)
        if existing is not None:
            return existing
        self._items[key] = decision
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)
        return decision

    def get_decision(self, session_id: str, message_id: str) -> CommentModerationDecision | None:
        return self._items.get((session_id, message_id))

    def has_decision(self, session_id: str, message_id: str) -> bool:
        return (session_id, message_id) in self._items

    def recent(self, session_id: str, limit: int = 50) -> tuple[CommentModerationDecision, ...]:
        values = [item for item in self._items.values() if item.session_id == session_id]
        return tuple(values[-limit:])
