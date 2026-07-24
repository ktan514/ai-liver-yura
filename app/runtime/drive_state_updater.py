from __future__ import annotations

from datetime import datetime

from app.domain.drives import DriveState
from app.domain.events import AgentEvent, AgentEventType
from app.utils.trace import TraceLogger


class DriveStateUpdater:
    """Event と時間経過から DriveState を更新する Runtime 部品。"""

    def __init__(self, trace_logger: TraceLogger | None = None) -> None:
        self._trace_logger = trace_logger or TraceLogger()

    def update_by_event(self, drive: DriveState, event: AgentEvent) -> DriveState:
        """AgentEvent の種類に応じて内的動機を更新する。"""

        if event.event_type in (
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        ):
            updated_drive = self._apply_user_input(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:user_input",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
            )
            return updated_drive

        if event.event_type in (
            AgentEventType.APP_STARTED,
            AgentEventType.STREAM_STARTED,
        ):
            updated_drive = self._apply_lifecycle_started(drive, event)
            self._write_update_trace(
                "drive_state_updater:update_by_event:lifecycle_started",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
            )
            return updated_drive

        if event.event_type == AgentEventType.SPEECH_FINISHED:
            updated_drive = self._apply_speech_finished(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:speech_finished",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
            )
            return updated_drive

        if event.event_type == AgentEventType.ACTION_FAILED:
            updated_drive = self._apply_action_failed(drive)
            self._write_update_trace(
                "drive_state_updater:update_by_event:action_failed",
                before_drive=drive,
                after_drive=updated_drive,
                event_type=event.event_type.value,
            )
            return updated_drive

        self._trace_logger.write(
            "drive_state_updater:update_by_event:no_change",
            event_type=event.event_type.value,
            curiosity=drive.curiosity,
            engagement=drive.engagement,
            boredom=drive.boredom,
            energy=drive.energy,
        )
        return drive

    def update_by_elapsed_time(
        self,
        drive: DriveState,
        elapsed_seconds: float,
    ) -> DriveState:
        """時間経過に応じて内的動機を更新する。"""

        elapsed_minutes = max(0.0, elapsed_seconds) / 60.0

        updated_drive = DriveState(
            curiosity=drive.curiosity + (0.06 * elapsed_minutes),
            engagement=drive.engagement - (0.01 * elapsed_minutes),
            boredom=drive.boredom + (0.14 * elapsed_minutes),
            energy=drive.energy - (0.005 * elapsed_minutes),
        )
        self._write_update_trace(
            "drive_state_updater:update_by_elapsed_time",
            before_drive=drive,
            after_drive=updated_drive,
            elapsed_seconds=elapsed_seconds,
            elapsed_minutes=elapsed_minutes,
        )
        return updated_drive

    def update_by_timestamps(
        self,
        drive: DriveState,
        previous_time: datetime,
        current_time: datetime,
    ) -> DriveState:
        """前回更新時刻と現在時刻の差分から内的動機を更新する。"""

        elapsed_seconds = (current_time - previous_time).total_seconds()
        return self.update_by_elapsed_time(drive, elapsed_seconds)

    def _apply_lifecycle_started(
        self, drive: DriveState, event: AgentEvent
    ) -> DriveState:
        if event.event_type == AgentEventType.STREAM_STARTED:
            return DriveState(
                curiosity=drive.curiosity + 0.08,
                engagement=drive.engagement + 0.18,
                boredom=drive.boredom + 0.02,
                energy=drive.energy + 0.04,
            )
        return drive

    def _apply_user_input(self, drive: DriveState) -> DriveState:
        return DriveState(
            curiosity=drive.curiosity + 0.1,
            engagement=drive.engagement + 0.2,
            boredom=drive.boredom - 0.3,
            energy=drive.energy - 0.03,
        )

    def _apply_speech_finished(self, drive: DriveState) -> DriveState:
        return DriveState(
            curiosity=drive.curiosity - 0.015,
            engagement=drive.engagement + 0.02,
            boredom=drive.boredom - 0.02,
            energy=drive.energy - 0.015,
        )

    def _apply_action_failed(self, drive: DriveState) -> DriveState:
        return DriveState(
            curiosity=drive.curiosity + 0.05,
            engagement=drive.engagement - 0.1,
            boredom=drive.boredom + 0.05,
            energy=drive.energy - 0.05,
        )

    def _write_update_trace(
        self,
        label: str,
        before_drive: DriveState,
        after_drive: DriveState,
        **values: object,
    ) -> None:
        self._trace_logger.debug(
            label,
            **values,
            before_curiosity=before_drive.curiosity,
            before_engagement=before_drive.engagement,
            before_boredom=before_drive.boredom,
            before_energy=before_drive.energy,
            after_curiosity=after_drive.curiosity,
            after_engagement=after_drive.engagement,
            after_boredom=after_drive.boredom,
            after_energy=after_drive.energy,
        )
