from __future__ import annotations

import threading

from app.domain.activities import Activity, ActivityStatus, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.utils.trace import TraceLogger


class ActivityManager:
    """Activity の生成・前面化・保留・一時停止を管理する。"""

    def __init__(self) -> None:
        self._activities: dict[str, Activity] = {}
        self._foreground_activity_id: str | None = None
        self._lock = threading.RLock()
        self._trace_logger = TraceLogger()

    @property
    def foreground_activity(self) -> Activity | None:
        with self._lock:
            if self._foreground_activity_id is None:
                return None
            return self._activities.get(self._foreground_activity_id)

    def get_activity(self, activity_id: str) -> Activity | None:
        with self._lock:
            return self._activities.get(activity_id)

    def prepare_user_input(self, event: AgentEvent) -> Activity | None:
        """USER_TEXT受理時に自律Activityを退避し、会話を予約する。"""

        if event.event_type != AgentEventType.USER_TEXT:
            return None
        with self._lock:
            prepared = self._find_by_source_event(event.event_id)
            if prepared is not None:
                return prepared
            current = self.foreground_activity
            if (
                current is None
                or current.activity_type != ActivityType.AUTONOMOUS_TALK
                or not current.interruptible
            ):
                return None

            suspended = current.with_status(ActivityStatus.SUSPENDED)
            self._activities[current.activity_id] = suspended
            conversation = self._create_activity_from_event(event)
            active_conversation = self._activate(conversation)
            self._trace_logger.info(
                "activity_manager:user_input:autonomous_suspended",
                activity_id=suspended.activity_id,
                activity_type=suspended.activity_type.value,
                source_event_id=event.event_id,
                reason="user_text_received",
            )
            self._trace_logger.info(
                "activity_manager:user_input:conversation_prepared",
                activity_id=active_conversation.activity_id,
                source_event_id=event.event_id,
            )
            return active_conversation

    def handle_event(self, event: AgentEvent) -> Activity:
        """イベントから Activity を生成し、現在の foreground と調停する。

        戻り値は、ActionPlanner が今回のイベントに対して扱う Activity。
        foreground になれない場合は pending Activity を返す。
        """
        with self._lock:
            return self._handle_event_locked(event)

    def _handle_event_locked(self, event: AgentEvent) -> Activity:
        prepared = self._find_by_source_event(event.event_id)
        if prepared is not None:
            self._trace_logger.info(
                "activity_manager:handle_event:prepared_activity_reused",
                activity_id=prepared.activity_id,
                activity_type=prepared.activity_type.value,
                event_id=event.event_id,
            )
            return prepared
        self._trace_logger.write(
            "activity_manager:handle_event:start",
            event_type=event.event_type.value,
            event_id=event.event_id,
            event_priority=event.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        new_activity = self._create_activity_from_event(event)
        self._trace_logger.write(
            "activity_manager:handle_event:activity_created",
            activity_id=new_activity.activity_id,
            activity_type=new_activity.activity_type.value,
            activity_status=new_activity.status.value,
            activity_priority=new_activity.priority,
            interruptible=new_activity.interruptible,
            source_event_id=new_activity.source_event_id,
        )
        resolved_activity = self._resolve_activity(new_activity)
        self._trace_logger.write(
            "activity_manager:handle_event:resolved",
            activity_id=resolved_activity.activity_id,
            activity_type=resolved_activity.activity_type.value,
            activity_status=resolved_activity.status.value,
            activity_priority=resolved_activity.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        return resolved_activity

    def _find_by_source_event(self, event_id: str) -> Activity | None:
        return next(
            (
                activity
                for activity in self._activities.values()
                if activity.source_event_id == event_id
            ),
            None,
        )

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

        self._trace_logger.write(
            "activity_manager:complete_activity:start",
            activity_id=activity.activity_id,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
            foreground_activity_id=self._foreground_activity_id,
        )

        completed = activity.with_status(ActivityStatus.COMPLETED)
        self._activities[activity_id] = completed

        if self._foreground_activity_id == activity_id:
            self._foreground_activity_id = None

        self._trace_logger.write(
            "activity_manager:complete_activity:completed",
            activity_id=completed.activity_id,
            activity_type=completed.activity_type.value,
            activity_status=completed.status.value,
            foreground_activity_id=self._foreground_activity_id,
        )
        return completed

    def cancel_activity(self, activity_id: str, *, reason: str) -> Activity | None:
        """未完了Activityをキャンセルし、foregroundなら解除する。"""

        with self._lock:
            activity = self._activities.get(activity_id)
            if activity is None:
                return None
            if activity.status in {ActivityStatus.COMPLETED, ActivityStatus.CANCELED}:
                return activity
            canceled = activity.with_status(ActivityStatus.CANCELED)
            self._activities[activity_id] = canceled
            if self._foreground_activity_id == activity_id:
                self._foreground_activity_id = None
            self._trace_logger.info(
                "activity_manager:activity_canceled",
                activity_id=canceled.activity_id,
                activity_type=canceled.activity_type.value,
                previous_status=activity.status.value,
                activity_source_event_id=canceled.source_event_id,
                reason=reason,
            )
            return canceled

    def complete_foreground_activity(self) -> Activity | None:
        foreground = self.foreground_activity
        if foreground is None:
            self._trace_logger.write("activity_manager:complete_foreground_activity:no_foreground")
            return None

        self._trace_logger.write(
            "activity_manager:complete_foreground_activity:start",
            activity_id=foreground.activity_id,
            activity_type=foreground.activity_type.value,
            activity_status=foreground.status.value,
        )

        completed = self.complete_activity(foreground.activity_id)
        self.resume_next_pending()
        return completed

    def complete_processed_activity(self, activity_id: str) -> Activity | None:
        """実行対象Activityだけを完了し、foregroundだった場合だけ次を再開する。"""

        with self._lock:
            was_foreground = self._foreground_activity_id == activity_id
            completed = self.complete_activity(activity_id)
            if was_foreground:
                self.resume_next_pending()
            return completed

    def resume_next_pending(self) -> Activity | None:
        pending_activities = self.pending_activities()
        if not pending_activities:
            self._trace_logger.write("activity_manager:resume_next_pending:no_pending")
            return None

        next_activity = max(pending_activities, key=lambda activity: activity.priority)
        self._trace_logger.write(
            "activity_manager:resume_next_pending:selected",
            activity_id=next_activity.activity_id,
            activity_type=next_activity.activity_type.value,
            activity_priority=next_activity.priority,
            pending_activity_count=len(pending_activities),
        )
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

        if event.event_type == AgentEventType.APP_STARTED:
            return Activity(
                activity_type=ActivityType.STARTUP_REACTION,
                goal="起動直後の状況に反応し、配信準備中であることを自然に伝える",
                priority=90 + event.priority,
                context={"event_payload": event.payload},
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.STREAM_STARTED:
            return Activity(
                activity_type=ActivityType.STREAM_OPENING_GREETING,
                goal="配信開始時のあいさつをして、これから話し始める雰囲気を作る",
                priority=95 + event.priority,
                context={"event_payload": event.payload},
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.STREAM_ENDING:
            return Activity(
                activity_type=ActivityType.STREAM_CLOSING_GREETING,
                goal="配信終了前のあいさつをして、視聴者に自然に別れを伝える",
                priority=110 + event.priority,
                context={"event_payload": event.payload},
                interruptible=False,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.CURIOSITY_PEAK:
            return Activity(
                activity_type=ActivityType.AUTONOMOUS_TALK,
                goal="内的関心に基づいて自律的に話題を出して話す",
                priority=55 + event.priority,
                context={"event_payload": event.payload},
                interruptible=True,
                source_event_id=event.event_id,
            )

        if event.event_type == AgentEventType.SILENCE_TIMEOUT:
            return Activity(
                activity_type=ActivityType.IDLE_OBSERVATION,
                goal="配信中の間を観察する",
                priority=15 + event.priority,
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
        self._trace_logger.write(
            "activity_manager:resolve_activity:start",
            new_activity_id=new_activity.activity_id,
            new_activity_type=new_activity.activity_type.value,
            new_activity_priority=new_activity.priority,
            current_activity_id=current.activity_id if current is not None else None,
            current_activity_type=current.activity_type.value if current is not None else None,
            current_activity_priority=current.priority if current is not None else None,
            current_interruptible=current.interruptible if current is not None else None,
        )

        if current is None:
            self._trace_logger.write(
                "activity_manager:resolve_activity:activate_without_current",
                activity_id=new_activity.activity_id,
                activity_type=new_activity.activity_type.value,
            )
            return self._activate(new_activity)

        if self._should_activate(current, new_activity):
            self._trace_logger.write(
                "activity_manager:resolve_activity:suspend_current",
                current_activity_id=current.activity_id,
                current_activity_type=current.activity_type.value,
                new_activity_id=new_activity.activity_id,
                new_activity_type=new_activity.activity_type.value,
            )
            self._activities[current.activity_id] = current.with_status(ActivityStatus.SUSPENDED)
            return self._activate(new_activity)

        pending = new_activity.with_status(ActivityStatus.PENDING)
        self._trace_logger.write(
            "activity_manager:resolve_activity:pending",
            activity_id=pending.activity_id,
            activity_type=pending.activity_type.value,
            activity_priority=pending.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        self._activities[pending.activity_id] = pending
        return pending

    def _should_activate(self, current: Activity, new_activity: Activity) -> bool:
        self._trace_logger.write(
            "activity_manager:should_activate:evaluate",
            current_activity_id=current.activity_id,
            current_activity_type=current.activity_type.value,
            current_priority=current.priority,
            current_interruptible=current.interruptible,
            new_activity_id=new_activity.activity_id,
            new_activity_type=new_activity.activity_type.value,
            new_priority=new_activity.priority,
        )
        if not current.interruptible:
            self._trace_logger.write(
                "activity_manager:should_activate:false",
                reason="current_not_interruptible",
                current_activity_id=current.activity_id,
                new_activity_id=new_activity.activity_id,
            )
            return False

        should_activate = new_activity.priority > current.priority
        self._trace_logger.write(
            "activity_manager:should_activate:result",
            should_activate=should_activate,
            reason="new_priority_higher" if should_activate else "new_priority_not_higher",
            current_priority=current.priority,
            new_priority=new_activity.priority,
        )
        return should_activate

    def _activate(self, activity: Activity) -> Activity:
        active = activity.with_status(ActivityStatus.ACTIVE)
        self._activities[active.activity_id] = active
        self._foreground_activity_id = active.activity_id
        self._trace_logger.write(
            "activity_manager:activate",
            activity_id=active.activity_id,
            activity_type=active.activity_type.value,
            activity_priority=active.priority,
            foreground_activity_id=self._foreground_activity_id,
        )
        return active
