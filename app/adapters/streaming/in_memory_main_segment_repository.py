from __future__ import annotations

from threading import RLock

from app.domain.streaming import StreamMainSegmentActivity


class InMemoryStreamMainSegmentRepository:
    def __init__(self) -> None:
        self._items: dict[str, StreamMainSegmentActivity] = {}
        self._index: dict[tuple[str, str | None], str] = {}
        self._commands: dict[str, StreamMainSegmentActivity] = {}
        self._lock = RLock()

    def create(self, activity: StreamMainSegmentActivity) -> StreamMainSegmentActivity:
        with self._lock:
            key = (activity.session_id, activity.segment_id)
            if key in self._index:
                raise ValueError("main_segment.duplicate")
            self._items[activity.activity_id] = activity
            self._index[key] = activity.activity_id
            return activity

    def save(self, activity: StreamMainSegmentActivity) -> StreamMainSegmentActivity:
        with self._lock:
            current = self._items.get(activity.activity_id)
            if current is None or activity.version != current.version + 1:
                raise ValueError("main_segment.version_mismatch")
            self._items[activity.activity_id] = activity
            return activity

    def find_by_session(self, session_id: str) -> StreamMainSegmentActivity | None:
        with self._lock:
            return next(
                (item for item in self._items.values() if item.session_id == session_id), None
            )

    def command_result(self, command_id: str) -> StreamMainSegmentActivity | None:
        return self._commands.get(command_id)

    def save_command_result(
        self, command_id: str, activity: StreamMainSegmentActivity
    ) -> StreamMainSegmentActivity:
        self._commands[command_id] = activity
        return activity
