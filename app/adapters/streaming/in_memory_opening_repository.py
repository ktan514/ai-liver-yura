from __future__ import annotations

from threading import RLock

from app.domain.streaming import StreamOpeningActivity


class InMemoryStreamOpeningRepository:
    def __init__(self) -> None:
        self._items: dict[str, StreamOpeningActivity] = {}
        self._session_index: dict[str, str] = {}
        self._commands: dict[str, StreamOpeningActivity] = {}
        self._lock = RLock()

    def create(self, activity: StreamOpeningActivity) -> StreamOpeningActivity:
        with self._lock:
            if activity.session_id in self._session_index:
                raise ValueError("opening.session.duplicate")
            self._items[activity.activity_id] = activity
            self._session_index[activity.session_id] = activity.activity_id
            return activity

    def save(self, activity: StreamOpeningActivity) -> StreamOpeningActivity:
        with self._lock:
            current = self._items.get(activity.activity_id)
            if current is None or activity.version != current.version + 1:
                raise ValueError("opening.version_mismatch")
            self._items[activity.activity_id] = activity
            return activity

    def find_by_session(self, session_id: str) -> StreamOpeningActivity | None:
        with self._lock:
            activity_id = self._session_index.get(session_id)
            return self._items.get(activity_id) if activity_id else None

    def command_result(self, command_id: str) -> StreamOpeningActivity | None:
        with self._lock:
            return self._commands.get(command_id)

    def save_command_result(
        self, command_id: str, activity: StreamOpeningActivity
    ) -> StreamOpeningActivity:
        with self._lock:
            self._commands[command_id] = activity
            return activity
