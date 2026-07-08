from __future__ import annotations
import threading

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from app.domain.activities import Activity
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState


@dataclass(frozen=True)
class PlannedActivity:
    """実行予定としてキューに積まれる Activity。"""

    activity: Activity
    source: str = "unknown"
    planning_reason: str = ""
    priority: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    planned_activity_id: str = field(default_factory=lambda: str(uuid4()))
    planned_drive: DriveState | None = None
    planned_emotion: EmotionState | None = None
    planned_topic: str | None = None

    @property
    def effective_priority(self) -> int:
        """Queue 内で使う優先度。明示値がなければ Activity の priority を使う。"""

        if self.priority is not None:
            return self.priority

        return self.activity.priority

    def is_expired(self, now: datetime | None = None) -> bool:
        """実行期限切れかどうかを判定する。"""

        if self.expires_at is None:
            return False

        current_time = now or datetime.now(timezone.utc)
        return self.expires_at <= current_time


class PlannedActivityQueue:
    """実行予定 Activity を優先度順に保持する thread-safe Queue。"""

    def __init__(self) -> None:
        self._items: list[PlannedActivity] = []
        self._lock = threading.RLock()

    def put(self, planned_activity: PlannedActivity) -> None:
        """Activity を実行待ち Queue に追加する。"""

        with self._lock:
            self._items.append(planned_activity)
            self._sort_locked()

    def extend(self, planned_activities: Iterable[PlannedActivity]) -> None:
        """複数の PlannedActivity を追加する。"""

        with self._lock:
            self._items.extend(planned_activities)
            self._sort_locked()

    def get(self, now: datetime | None = None) -> PlannedActivity | None:
        """期限切れを除外し、最も優先度の高い Activity を取り出す。"""

        with self._lock:
            self._discard_expired_locked(now=now)
            if not self._items:
                return None

            return self._items.pop(0)

    def peek(self, now: datetime | None = None) -> PlannedActivity | None:
        """期限切れを除外し、次に実行予定の Activity を参照する。"""

        with self._lock:
            self._discard_expired_locked(now=now)
            if not self._items:
                return None

            return self._items[0]

    def discard_expired(self, now: datetime | None = None) -> list[PlannedActivity]:
        """期限切れ Activity を Queue から除外し、除外した要素を返す。"""

        with self._lock:
            return self._discard_expired_locked(now=now)

    def clear(self) -> None:
        """Queue を空にする。"""

        with self._lock:
            self._items.clear()

    def items(self, now: datetime | None = None) -> list[PlannedActivity]:
        """現在 Queue に残っている Activity を優先度順で返す。"""

        with self._lock:
            self._discard_expired_locked(now=now)
            return list(self._items)

    def is_empty(self, now: datetime | None = None) -> bool:
        """Queue が空かどうかを返す。"""

        with self._lock:
            self._discard_expired_locked(now=now)
            return len(self._items) == 0

    def size(self, now: datetime | None = None) -> int:
        """Queue に残っている Activity 数を返す。"""

        with self._lock:
            self._discard_expired_locked(now=now)
            return len(self._items)

    def _sort_locked(self) -> None:
        """Lock 取得済みの状態で Queue を優先度順に並べる。"""

        self._items.sort(
            key=lambda item: (item.effective_priority, item.created_at),
            reverse=True,
        )

    def _discard_expired_locked(self, now: datetime | None = None) -> list[PlannedActivity]:
        """Lock 取得済みの状態で期限切れ Activity を除外する。"""

        expired_items: list[PlannedActivity] = []
        active_items: list[PlannedActivity] = []

        for item in self._items:
            if item.is_expired(now=now):
                expired_items.append(item)
            else:
                active_items.append(item)

        self._items = active_items
        return expired_items