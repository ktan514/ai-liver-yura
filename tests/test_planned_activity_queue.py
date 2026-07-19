from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.activities import Activity, ActivityType
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue


def _create_activity(
    activity_type: ActivityType = ActivityType.AUTONOMOUS_TALK,
    priority: int = 10,
    goal: str = "自律的に話す",
) -> Activity:
    return Activity(
        activity_type=activity_type,
        goal=goal,
        priority=priority,
        context={},
        interruptible=True,
    )


def test_planned_activity_uses_activity_priority_when_priority_is_not_specified() -> (
    None
):
    activity = _create_activity(priority=42)

    planned_activity = PlannedActivity(activity=activity)

    assert planned_activity.effective_priority == 42


def test_planned_activity_uses_explicit_priority_when_specified() -> None:
    activity = _create_activity(priority=10)

    planned_activity = PlannedActivity(activity=activity, priority=80)

    assert planned_activity.effective_priority == 80


def test_planned_activity_is_expired_when_expires_at_is_past() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    activity = _create_activity()
    planned_activity = PlannedActivity(
        activity=activity,
        expires_at=now - timedelta(seconds=1),
    )

    assert planned_activity.is_expired(now=now) is True


def test_planned_activity_is_not_expired_when_expires_at_is_future() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    activity = _create_activity()
    planned_activity = PlannedActivity(
        activity=activity,
        expires_at=now + timedelta(seconds=1),
    )

    assert planned_activity.is_expired(now=now) is False


def test_queue_get_returns_highest_priority_activity_first() -> None:
    queue = PlannedActivityQueue()
    low = PlannedActivity(activity=_create_activity(priority=10))
    high = PlannedActivity(activity=_create_activity(priority=90))
    middle = PlannedActivity(activity=_create_activity(priority=50))

    queue.put(low)
    queue.put(high)
    queue.put(middle)

    assert queue.get() == high
    assert queue.get() == middle
    assert queue.get() == low
    assert queue.get() is None


def test_queue_get_uses_explicit_priority_before_activity_priority() -> None:
    queue = PlannedActivityQueue()
    activity_high = PlannedActivity(activity=_create_activity(priority=90))
    explicit_high = PlannedActivity(
        activity=_create_activity(priority=10), priority=100
    )

    queue.put(activity_high)
    queue.put(explicit_high)

    assert queue.get() == explicit_high
    assert queue.get() == activity_high


def test_queue_peek_does_not_remove_activity() -> None:
    queue = PlannedActivityQueue()
    planned_activity = PlannedActivity(activity=_create_activity(priority=10))

    queue.put(planned_activity)

    assert queue.peek() == planned_activity
    assert queue.size() == 1
    assert queue.get() == planned_activity
    assert queue.size() == 0


def test_queue_discards_expired_activities() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    queue = PlannedActivityQueue()
    expired = PlannedActivity(
        activity=_create_activity(priority=100),
        expires_at=now - timedelta(seconds=1),
    )
    active = PlannedActivity(
        activity=_create_activity(priority=10),
        expires_at=now + timedelta(seconds=1),
    )

    queue.put(expired)
    queue.put(active)

    discarded = queue.discard_expired(now=now)

    assert discarded == [expired]
    assert queue.items(now=now) == [active]
    assert queue.get(now=now) == active


def test_queue_is_empty_and_size_ignore_expired_activities() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    queue = PlannedActivityQueue()
    expired = PlannedActivity(
        activity=_create_activity(priority=100),
        expires_at=now - timedelta(seconds=1),
    )

    queue.put(expired)

    assert queue.is_empty(now=now) is True
    assert queue.size(now=now) == 0


def test_queue_clear_removes_all_activities() -> None:
    queue = PlannedActivityQueue()
    queue.put(PlannedActivity(activity=_create_activity(priority=10)))
    queue.put(PlannedActivity(activity=_create_activity(priority=20)))

    queue.clear()

    assert queue.is_empty() is True
    assert queue.get() is None


def test_discard_where_removes_only_matching_autonomous_activities() -> None:
    queue = PlannedActivityQueue()
    autonomous = PlannedActivity(
        activity=_create_activity(ActivityType.AUTONOMOUS_TALK, priority=50)
    )
    observation = PlannedActivity(
        activity=_create_activity(ActivityType.IDLE_OBSERVATION, priority=10)
    )
    queue.extend([autonomous, observation])

    discarded = queue.discard_where(
        lambda item: item.activity.activity_type == ActivityType.AUTONOMOUS_TALK
    )

    assert discarded == [autonomous]
    assert queue.items() == [observation]


def test_queue_extend_adds_multiple_activities() -> None:
    queue = PlannedActivityQueue()
    low = PlannedActivity(activity=_create_activity(priority=10))
    high = PlannedActivity(activity=_create_activity(priority=90))

    queue.extend([low, high])

    assert queue.size() == 2
    assert queue.get() == high
    assert queue.get() == low
