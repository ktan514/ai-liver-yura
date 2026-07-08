from __future__ import annotations

from datetime import datetime, timezone

from app.common.trace import TraceLogger
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.drive_state_updater import DriveStateUpdater


class AgentLifeService:
    """AIライバーの生活・活動状態を更新する同期処理本体。

    AgentState の更新と ActivityManager からの状態同期を担当し、
    状態に応じて次に発生させる自律 Event を判断する。
    Thread や Queue には依存しない。
    """

    def __init__(
        self,
        activity_manager: ActivityManager,
        initial_state: AgentState | None = None,
        drive_state_updater: DriveStateUpdater | None = None,
        now: datetime | None = None,
    ) -> None:
        self._activity_manager = activity_manager
        self._agent_state = initial_state or AgentState()
        self._drive_state_updater = drive_state_updater or DriveStateUpdater()
        self._last_drive_updated_at = now or datetime.now(timezone.utc)
        self._last_autonomous_talk_planned_at: datetime | None = None
        self._trace_logger = TraceLogger()

    @property
    def agent_state(self) -> AgentState:
        return self._agent_state

    def plan_next_event(self, now: datetime | None = None) -> AgentEvent | None:
        """現在状態から、次に発生させる自律 Event を判断する。"""

        now = now or datetime.now(timezone.utc)
        self._update_drive_by_elapsed_time(now)
        self.sync_from_activity_manager()
        self._trace_logger.write(
            "agent_life_service:plan_next_event:start",
            active_activity_exists=self._agent_state.active_activity is not None,
            pending_activity_count=len(self._agent_state.pending_activities),
            suspended_activity_count=len(self._agent_state.suspended_activities),
            drive_curiosity=self._agent_state.current_drive.curiosity,
            drive_engagement=self._agent_state.current_drive.engagement,
            drive_boredom=self._agent_state.current_drive.boredom,
            drive_energy=self._agent_state.current_drive.energy,
            emotion_mood=self._agent_state.current_emotion.mood.value,
            emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
        )

        if self._agent_state.active_activity is not None:
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="active_activity_exists",
                active_activity_type=self._agent_state.active_activity.activity_type.value,
            )
            return None

        if self._agent_state.pending_activities:
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="pending_activity_exists",
                pending_activity_count=len(self._agent_state.pending_activities),
            )
            return None

        if self._agent_state.current_emotion.should_reduce_speech():
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="emotion_reduces_speech",
                emotion_mood=self._agent_state.current_emotion.mood.value,
                emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
            )
            return None

        if not self._agent_state.current_drive.should_start_autonomous_talk():
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="drive_too_weak",
                drive_curiosity=self._agent_state.current_drive.curiosity,
                drive_engagement=self._agent_state.current_drive.engagement,
                drive_boredom=self._agent_state.current_drive.boredom,
                drive_energy=self._agent_state.current_drive.energy,
            )
            return None

        minimum_pause_seconds = self._agent_state.current_emotion.speech_pause_seconds()

        if self._is_within_pause(
            since=self._agent_state.last_speech_finished_at,
            now=now,
            pause_seconds=minimum_pause_seconds,
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="after_speech_pause",
                pause_seconds=minimum_pause_seconds,
                last_speech_finished_at=self._agent_state.last_speech_finished_at,
            )
            return None

        if self._is_within_pause(
            since=self._agent_state.last_user_input_at,
            now=now,
            pause_seconds=minimum_pause_seconds,
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="after_user_input_pause",
                pause_seconds=minimum_pause_seconds,
                last_user_input_at=self._agent_state.last_user_input_at,
            )
            return None

        autonomous_talk_interval_seconds = self._autonomous_talk_interval_seconds()
        if self._is_within_pause(
            since=self._last_autonomous_talk_planned_at,
            now=now,
            pause_seconds=autonomous_talk_interval_seconds,
        ):
            self._trace_logger.write(
                "agent_life_service:plan_next_event:skipped",
                reason="autonomous_talk_interval",
                interval_seconds=autonomous_talk_interval_seconds,
                last_autonomous_talk_planned_at=self._last_autonomous_talk_planned_at,
                emotion_arousal=self._agent_state.current_emotion.arousal,
                emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
                drive_energy=self._agent_state.current_drive.energy,
            )
            return None

        self._last_autonomous_talk_planned_at = now

        self._trace_logger.write(
            "agent_life_service:plan_next_event:planned",
            event_type=AgentEventType.CURIOSITY_PEAK.value,
            reason="internal_drive",
            drive=self._agent_state.current_drive.strongest_drive_name(),
            drive_curiosity=self._agent_state.current_drive.curiosity,
            drive_engagement=self._agent_state.current_drive.engagement,
            drive_boredom=self._agent_state.current_drive.boredom,
            drive_energy=self._agent_state.current_drive.energy,
            autonomous_talk_interval_seconds=autonomous_talk_interval_seconds,
            emotion_arousal=self._agent_state.current_emotion.arousal,
            emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
        )

        return AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload={
                "reason": "internal_drive",
                "drive": self._agent_state.current_drive.strongest_drive_name(),
            },
            priority=10,
            discardable=True,
            replace_key="agent_life_service:curiosity_peak",
        )

    def handle_event(self, event: AgentEvent) -> AgentState:
        """Event を受け取り、AgentState に反映する。"""

        before_drive = self._agent_state.current_drive

        self._agent_state = self._agent_state.with_drive(
            self._drive_state_updater.update_by_event(
                self._agent_state.current_drive,
                event,
            )
        )

        after_drive = self._agent_state.current_drive
        self._trace_logger.write(
            "agent_life_service:handle_event:drive_updated",
            event_type=event.event_type.value,
            before_curiosity=before_drive.curiosity,
            before_engagement=before_drive.engagement,
            before_boredom=before_drive.boredom,
            before_energy=before_drive.energy,
            after_curiosity=after_drive.curiosity,
            after_engagement=after_drive.engagement,
            after_boredom=after_drive.boredom,
            after_energy=after_drive.energy,
        )

        if event.event_type in (
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        ):
            self._agent_state = self._agent_state.mark_user_input_received()

        if event.event_type == AgentEventType.SPEECH_STARTED:
            self._agent_state = self._agent_state.mark_speech_started()

        if event.event_type == AgentEventType.SPEECH_FINISHED:
            self._agent_state = self._agent_state.mark_speech_finished()

        return self.sync_from_activity_manager()

    def sync_from_activity_manager(self) -> AgentState:
        """ActivityManager の状態を AgentState に同期する。"""

        self._agent_state = (
            self._agent_state
            .with_active_activity(self._activity_manager.foreground_activity)
            .with_pending_activities(self._activity_manager.pending_activities())
            .with_suspended_activities(self._activity_manager.suspended_activities())
        )

        return self._agent_state

    def update_emotion(self, emotion: EmotionState) -> AgentState:
        """感情・気分状態を更新する。"""

        self._agent_state = self._agent_state.with_emotion(emotion)
        return self._agent_state

    def update_drive(self, drive: DriveState) -> AgentState:
        """内的動機状態を更新する。"""

        self._agent_state = self._agent_state.with_drive(drive)
        return self._agent_state

    def _update_drive_by_elapsed_time(self, now: datetime) -> None:
        before_drive = self._agent_state.current_drive
        elapsed_seconds = (now - self._last_drive_updated_at).total_seconds()
        updated_drive = self._drive_state_updater.update_by_timestamps(
            self._agent_state.current_drive,
            previous_time=self._last_drive_updated_at,
            current_time=now,
        )
        self._agent_state = self._agent_state.with_drive(updated_drive)
        self._last_drive_updated_at = now
        after_drive = self._agent_state.current_drive
        self._trace_logger.write(
            "agent_life_service:drive_updated_by_elapsed_time",
            elapsed_seconds=elapsed_seconds,
            before_curiosity=before_drive.curiosity,
            before_engagement=before_drive.engagement,
            before_boredom=before_drive.boredom,
            before_energy=before_drive.energy,
            after_curiosity=after_drive.curiosity,
            after_engagement=after_drive.engagement,
            after_boredom=after_drive.boredom,
            after_energy=after_drive.energy,
        )

    def _autonomous_talk_interval_seconds(self) -> float:
        """テンションから次の自律発話までの最低間隔を決める。"""

        emotion = self._agent_state.current_emotion
        drive = self._agent_state.current_drive
        tension = (
            emotion.arousal * 0.45
            + emotion.talkativeness * 0.45
            + drive.energy * 0.10
        )
        tension = max(0.0, min(1.0, tension))

        minimum_interval_seconds = 8.0
        maximum_interval_seconds = 60.0
        return maximum_interval_seconds - (
            (maximum_interval_seconds - minimum_interval_seconds) * tension
        )

    def _is_within_pause(
        self,
        since: datetime | None,
        now: datetime,
        pause_seconds: float,
    ) -> bool:
        if since is None:
            return False

        return (now - since).total_seconds() < pause_seconds