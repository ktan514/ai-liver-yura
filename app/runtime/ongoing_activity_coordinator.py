from __future__ import annotations

from collections.abc import Mapping

from app.domain.activities import ActivityStatus, OngoingActivity
from app.domain.character_response import ActivityExecutionResult
from app.runtime.activity_manager import ActivityManager
from app.utils.trace import TraceLogger


class OngoingActivityCoordinator:
    """Plugin種別に依存せず、継続Activityの開始・Turn・終了を同期する。"""

    def __init__(self, activity_manager: ActivityManager) -> None:
        self._activity_manager = activity_manager
        self._trace_logger = TraceLogger()

    def start(
        self,
        *,
        activity_type: str,
        goal: str,
        expected_input: str,
        end_condition: str,
        context: Mapping[str, object],
        input_text: str,
        source_event_id: str | None,
        operation: str,
        constraints: Mapping[str, object],
    ) -> OngoingActivity:
        ongoing = self._activity_manager.start_ongoing_activity(
            activity_type=activity_type,
            goal=goal,
            expected_input=expected_input,
            end_condition=end_condition,
            context=dict(context),
        )
        begun = self._activity_manager.begin_ongoing_turn(
            input_text=input_text,
            source_event_id=source_event_id,
            operation=operation,
            constraints_snapshot=dict(constraints),
        )
        if begun is None:
            raise RuntimeError("作成したOngoingActivityのTurnを開始できませんでした。")
        self._trace_logger.info(
            "ongoing_activity_coordinator:started",
            ongoing_activity_id=ongoing.ongoing_activity_id,
            activity_type=activity_type,
            source_event_id=source_event_id,
            context_keys=sorted(context.keys()),
        )
        return begun

    def begin_turn(
        self,
        *,
        input_text: str,
        source_event_id: str | None,
        operation: str,
        constraints: Mapping[str, object],
    ) -> OngoingActivity:
        ongoing = self._activity_manager.begin_ongoing_turn(
            input_text=input_text,
            source_event_id=source_event_id,
            operation=operation,
            constraints_snapshot=dict(constraints),
        )
        if ongoing is None:
            raise RuntimeError("継続対象のOngoingActivityがありません。")
        return ongoing

    def record_execution(
        self,
        result: ActivityExecutionResult,
        *,
        context_updates: Mapping[str, object],
        expected_input: str,
        waiting_input: bool,
    ) -> OngoingActivity:
        ongoing = self._activity_manager.record_ongoing_execution(
            result,
            context_updates=dict(context_updates),
            expected_input=expected_input,
            waiting_input=waiting_input,
        )
        if ongoing is None:
            raise RuntimeError("OngoingActivityへ実行結果を記録できませんでした。")
        return ongoing

    def complete(self, *, reason: str) -> OngoingActivity | None:
        completed = self._activity_manager.end_ongoing_activity(reason=reason)
        if completed is not None:
            self._trace_logger.info(
                "ongoing_activity_coordinator:completed",
                ongoing_activity_id=completed.ongoing_activity_id,
                activity_type=completed.activity_type,
                reason=reason,
            )
        return completed

    def cancel(self, *, reason: str) -> OngoingActivity | None:
        canceled = self._activity_manager.cancel_ongoing_activity(reason=reason)
        if canceled is not None:
            self._trace_logger.info(
                "ongoing_activity_coordinator:canceled",
                ongoing_activity_id=canceled.ongoing_activity_id,
                activity_type=canceled.activity_type,
                reason=reason,
            )
        return canceled

    def pause(self, *, reason: str) -> OngoingActivity | None:
        paused = self._activity_manager.pause_ongoing_activity(reason=reason)
        if paused is not None:
            self._trace_logger.info(
                "ongoing_activity_coordinator:paused",
                ongoing_activity_id=paused.ongoing_activity_id,
                activity_type=paused.activity_type,
                reason=reason,
            )
        return paused

    def verify_context(
        self,
        *,
        session_id: str | None,
        plugin_id: str,
    ) -> OngoingActivity | None:
        ongoing = self._activity_manager.ongoing_activity
        if ongoing is None:
            return None
        expected_session_id = ongoing.context.get("game_session_id")
        expected_plugin_id = ongoing.context.get("plugin_id")
        if expected_plugin_id != plugin_id or (
            expected_session_id is not None and expected_session_id != session_id
        ):
            self._trace_logger.error(
                "ongoing_activity_coordinator:context_mismatch",
                ongoing_activity_id=ongoing.ongoing_activity_id,
                expected_plugin_id=expected_plugin_id,
                actual_plugin_id=plugin_id,
                expected_session_id=expected_session_id,
                actual_session_id=session_id,
            )
            raise RuntimeError("OngoingActivityとPlugin Sessionの関連が一致しません。")
        if ongoing.status not in {
            ActivityStatus.ACTIVE,
            ActivityStatus.WAITING,
            ActivityStatus.SUSPENDED,
        }:
            raise RuntimeError(f"継続できないOngoingActivity状態です: {ongoing.status.value}")
        return ongoing
