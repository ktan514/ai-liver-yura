from __future__ import annotations

from collections import OrderedDict, deque
from threading import RLock

from app.plugins.youtube_streaming.domain import (
    CommentResponseHistoryEntry,
    StreamCommentResponseActivity,
)


class InMemoryCommentResponseActivityRepository:
    def __init__(self, capacity: int = 500) -> None:
        self._items: OrderedDict[str, StreamCommentResponseActivity] = OrderedDict()
        self._selection_index: dict[tuple[str, str], str] = {}
        self._commands: dict[str, StreamCommentResponseActivity] = {}
        self._capacity = capacity
        self._lock = RLock()

    def create(
        self, activity: StreamCommentResponseActivity
    ) -> StreamCommentResponseActivity:
        with self._lock:
            key = (activity.session_id, activity.selection_id)
            if key in self._selection_index:
                raise ValueError("comment_response.duplicate_activity")
            self._items[activity.activity_id] = activity
            self._selection_index[key] = activity.activity_id
            while len(self._items) > self._capacity:
                activity_id, old = self._items.popitem(last=False)
                self._selection_index.pop((old.session_id, old.selection_id), None)
                if activity_id == activity.activity_id:
                    raise ValueError("comment_response.repository_capacity")
            return activity

    def save(
        self, activity: StreamCommentResponseActivity
    ) -> StreamCommentResponseActivity:
        with self._lock:
            current = self._items.get(activity.activity_id)
            if current is None or activity.version != current.version + 1:
                raise ValueError("comment_response.version_mismatch")
            self._items[activity.activity_id] = activity
            return activity

    def get(self, activity_id: str) -> StreamCommentResponseActivity | None:
        return self._items.get(activity_id)

    def find_by_session(self, session_id: str) -> StreamCommentResponseActivity | None:
        return next(
            (
                item
                for item in reversed(self._items.values())
                if item.session_id == session_id
            ),
            None,
        )

    def find_by_selection(
        self, session_id: str, selection_id: str
    ) -> StreamCommentResponseActivity | None:
        activity_id = self._selection_index.get((session_id, selection_id))
        return self._items.get(activity_id) if activity_id else None

    def command_result(self, command_id: str) -> StreamCommentResponseActivity | None:
        return self._commands.get(command_id)

    def save_command_result(
        self, command_id: str, activity: StreamCommentResponseActivity
    ) -> StreamCommentResponseActivity:
        self._commands[command_id] = activity
        return activity


class InMemoryCommentResponseHistory:
    def __init__(self, capacity: int = 100) -> None:
        self._items: dict[str, deque[CommentResponseHistoryEntry]] = {}
        self._capacity = capacity

    def save(self, item: CommentResponseHistoryEntry) -> None:
        self._items.setdefault(item.session_id, deque(maxlen=self._capacity)).append(
            item
        )

    def recent(
        self, session_id: str, limit: int = 20
    ) -> tuple[CommentResponseHistoryEntry, ...]:
        return tuple(self._items.get(session_id, ()))[-limit:]
