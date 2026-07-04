from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.activities.activity_status import ActivityStatus
from app.domain.activities.activity_type import ActivityType


@dataclass(frozen=True, slots=True)
class Activity:
    """継続する目的を表す。

    例:
      - ユーザーと会話する
      - 自律的に話す
      - 返答を待つ
      - 外部刺激に反応する
    """

    activity_type: ActivityType
    goal: str
    status: ActivityStatus = ActivityStatus.PENDING
    priority: int = 0
    context: dict[str, Any] = field(default_factory=dict)
    interruptible: bool = True
    source_event_id: str | None = None
    activity_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def with_status(self, status: ActivityStatus) -> Activity:
        return replace(self, status=status, updated_at=datetime.now(timezone.utc))

    def with_priority(self, priority: int) -> Activity:
        return replace(self, priority=priority, updated_at=datetime.now(timezone.utc))
