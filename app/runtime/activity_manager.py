from __future__ import annotations

from app.domain.activities import Activity, ActivityStatus, ActivityType
from app.domain.events import AgentEvent, AgentEventType


class ActivityManager:
    """Activity の生成・前面化・保留・一時停止を管理する。"""

    def __init__(self) -> None:
        self._activities: dict[str, Activity] = {}
        self._foreground_activity_id: str | None = None

    @property
    def foreground_activity(self) -> Activity | None:
        if self._foreground_activity_id is None:
            return None
        return self._activities.get(self._foreground_activity_id)

    def handle_event(self, event: AgentEvent) -> Activity:
        """イベントから Activity を生成し、現在の foreground と調停する。

        戻り値は、ActionPlanner が今回のイベントに対して扱う Activity。
        foreground になれない場合は pending Activity を返す。
        """
        new_activity = self._create_activity_from_event(event)
        return self._resolve_activity(new_activity)

    def list_activities(self) -> list[Activity]:
        return list(self._activities.values())

    def pending_activities(self) -> list[Activity]:
        return [
            activity
            for activity in self._activities.values()
            if activity.status == ActivityStatus.PENDING
        ]

    def suspended_activities(self) -> list[Activity]:
        return [
            activity
            for activity in self._activities.values()
            if activity.status == ActivityStatus.SUSPENDED
        ]

    def complete_activity(self, activity_id: str) -> Activity | None:
        activity = self._activities.get(activity_id)
        if activity is None:
            return None

        completed = activity.with_status(ActivityStatus.COMPLETED)
        self._activities[activity_id] = completed

        if self._foreground_activity_id == activity_id:
            self._foreground_activity_id = None

        return completed

    def complete_foreground_activity(self) -> Activity | None:
        foreground = self.foreground_activity
        if foreground is None:
            return None

        completed = self.complete_activity(foreground.activity_id)
        self.resume_next_pending()
        return completed

    def resume_next_pending(self) -> Activity | None:
        pending_activities = self.pending_activities()
        if not pending_activities:
            return None

        next_activity = max(pending_activities, key=lambda activity: activity.priority)
        return self._activate(next_activity)

    def _create_activity_from_event(self, event: AgentEvent) -> Activity:
        if event.event_type in (AgentEventType.USER_TEXT, AgentEventType.YOUTUBE_COMMENT):
            return Activity(
                activity_type=ActivityType.CONVERSATION_WITH_USER,
                goal="ユーザー入力に応答する",
                priority=100 + event.priority,
                context={"event_payload": event.payload},
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type in (AgentEventType.SILENCE_TIMEOUT, AgentEventType.CURIOSITY_PEAK):
            return Activity(
                activity_type=ActivityType.AUTONOMOUS_TALK,
                goal="自律的に話題を出して話す",
                priority=55 + event.priority,
                context={"event_payload": event.payload},
                interruptible=True,
                source_event_id=event.event_id,
            )

        return Activity(
            activity_type=ActivityType.IDLE_OBSERVATION,
            goal="状態を観察する",
            priority=10 + event.priority,
            context={"event_payload": event.payload},
            interruptible=True,
            source_event_id=event.event_id,
        )

    def _resolve_activity(self, new_activity: Activity) -> Activity:
        current = self.foreground_activity

        if current is None:
            return self._activate(new_activity)

        if self._should_activate(current, new_activity):
            self._activities[current.activity_id] = current.with_status(ActivityStatus.SUSPENDED)
            return self._activate(new_activity)

        pending = new_activity.with_status(ActivityStatus.PENDING)
        self._activities[pending.activity_id] = pending
        return pending

    def _should_activate(self, current: Activity, new_activity: Activity) -> bool:
        if not current.interruptible:
            return False

        return new_activity.priority > current.priority

    def _activate(self, activity: Activity) -> Activity:
        active = activity.with_status(ActivityStatus.ACTIVE)
        self._activities[active.activity_id] = active
        self._foreground_activity_id = active.activity_id
        return active
