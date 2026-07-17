from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Protocol

from app.domain.actions import ActionType
from app.domain.activity_turn_result import ActionExecutionStatus, ActivityTurnResult
from app.domain.streaming import (
    LifecycleOperation,
    RetryOpeningCommand,
    StreamOpeningActivity,
    StreamOpeningRejected,
    StreamOpeningStatus,
    StreamSessionStatus,
    StreamStartResult,
)
from app.ports.streaming_preparation import RunOfShowRepository, StreamSessionRepository
from app.usecases.stream_lifecycle_gate import StreamLifecycleGate


class OpeningRepository(Protocol):
    def create(self, activity: StreamOpeningActivity) -> StreamOpeningActivity: ...
    def save(self, activity: StreamOpeningActivity) -> StreamOpeningActivity: ...
    def find_by_session(self, session_id: str) -> StreamOpeningActivity | None: ...
    def command_result(self, command_id: str) -> StreamOpeningActivity | None: ...
    def save_command_result(
        self, command_id: str, activity: StreamOpeningActivity
    ) -> StreamOpeningActivity: ...


OpeningExecutor = Callable[[dict[str, object], str], Awaitable[ActivityTurnResult]]
OpeningEventPublisher = Callable[[str, dict[str, object], str], None]
OpeningCompleted = Callable[[StreamOpeningActivity, dict[str, str]], Awaitable[object]]


class StreamOpeningUsecase:
    """LIVE確定後のopening一回分だけを実行する。"""

    def __init__(
        self,
        *,
        sessions: StreamSessionRepository,
        openings: OpeningRepository,
        run_of_show: RunOfShowRepository,
        executor: OpeningExecutor,
        event_publisher: OpeningEventPublisher | None = None,
        require_opening_segment: bool = True,
        completed_handler: OpeningCompleted | None = None,
        lifecycle_gate: StreamLifecycleGate | None = None,
    ) -> None:
        self._sessions = sessions
        self._openings = openings
        self._run_of_show = run_of_show
        self._executor = executor
        self._publish = event_publisher or (lambda _type, _data, _trace: None)
        self._require_segment = require_opening_segment
        self._completed_handler = completed_handler
        self._gate = lifecycle_gate

    def status(self, session_id: str) -> StreamOpeningActivity | None:
        return self._openings.find_by_session(session_id)

    async def start(
        self,
        session_id: str,
        start_result: StreamStartResult,
        *,
        adapter_types: tuple[str, str],
        test_mode: bool = False,
    ) -> StreamOpeningActivity:
        session = self._sessions.get(session_id)
        if session is None:
            raise StreamOpeningRejected("opening.session.not_found")
        if self._openings.find_by_session(session_id) is not None:
            raise StreamOpeningRejected("opening.session.duplicate")
        if session.status != StreamSessionStatus.LIVE or not start_result.successful:
            raise StreamOpeningRejected("opening.session.not_live")
        if (
            start_result.obs_status != "active"
            or start_result.youtube_stream_status != "active"
            or start_result.youtube_broadcast_status != "live"
        ):
            raise StreamOpeningRejected("opening.stream_state.unverified")
        if "fake" in adapter_types and not test_mode:
            raise StreamOpeningRejected("opening.fake_requires_test_mode")
        if self._gate is not None:
            state = {
                "obs_output": start_result.obs_status,
                "youtube_stream": start_result.youtube_stream_status,
                "youtube_broadcast": start_result.youtube_broadcast_status,
                "stream_session": session.status.value,
            }
            self._gate.update_external_state(session_id, state)
            decision = self._gate.evaluate(
                LifecycleOperation.START_OPENING, session_id, trace_id=start_result.trace_id
            )
            if not decision.allowed:
                raise StreamOpeningRejected(
                    decision.reason_code or "lifecycle.operation_not_allowed"
                )
        if not session.run_of_show_id:
            return self._create_failed(
                session_id, start_result.trace_id, None, "opening.run_of_show.missing"
            )
        try:
            segment = self._run_of_show.get_opening_segment(session.run_of_show_id)
        except Exception as error:
            return self._create_failed(session_id, start_result.trace_id, None, str(error))
        if segment is None:
            code = (
                "opening.segment.required_missing"
                if self._require_segment
                else "opening.segment.optional_missing"
            )
            activity = StreamOpeningActivity(session_id, start_result.trace_id, None)
            self._openings.create(activity)
            self._sessions.save(session.attach_opening(activity.activity_id))
            if self._require_segment:
                return self._fail(activity.transition(StreamOpeningStatus.RUNNING), code)
            activity = self._openings.save(
                activity.transition(StreamOpeningStatus.CANCELED, failure_code=code)
            )
            return activity
        activity = StreamOpeningActivity(session_id, start_result.trace_id, segment.segment_id)
        self._openings.create(activity)
        self._sessions.save(session.attach_opening(activity.activity_id))
        return await self._execute(activity, segment=asdict(segment), session_title=session.title)

    async def retry(self, command: RetryOpeningCommand) -> StreamOpeningActivity:
        duplicate = self._openings.command_result(command.command_id)
        if duplicate is not None:
            return duplicate
        activity = self._openings.find_by_session(command.session_id)
        if activity is None:
            raise StreamOpeningRejected("opening.not_found")
        if activity.version != command.expected_activity_version:
            raise StreamOpeningRejected("opening.version_mismatch")
        if activity.status != StreamOpeningStatus.FAILED:
            raise StreamOpeningRejected(f"opening.retry.{activity.status.value}")
        session = self._sessions.get(command.session_id)
        if session is None or session.status != StreamSessionStatus.LIVE:
            raise StreamOpeningRejected("opening.session.not_live")
        if not session.run_of_show_id:
            raise StreamOpeningRejected("opening.run_of_show.missing")
        try:
            segment = self._run_of_show.get_opening_segment(session.run_of_show_id)
        except Exception as error:
            raise StreamOpeningRejected(str(error)) from error
        if segment is None:
            raise StreamOpeningRejected("opening.segment.required_missing")
        result = await self._execute(activity, segment=asdict(segment), session_title=session.title)
        return self._openings.save_command_result(command.command_id, result)

    async def _execute(
        self, activity: StreamOpeningActivity, *, segment: dict[str, object], session_title: str
    ) -> StreamOpeningActivity:
        activity = self._openings.save(activity.transition(StreamOpeningStatus.RUNNING))
        common = self._event_data(activity)
        self._publish("stream_opening.started", common, activity.trace_id)
        self._publish(
            "stream_opening.segment_started", {**common, "segment": segment}, activity.trace_id
        )
        self._publish("stream_opening.generation_started", common, activity.trace_id)
        payload: dict[str, object] = {
            "session_id": activity.session_id,
            "activity_type": "stream_opening",
            "plugin_id": "youtube_streaming",
            "stream_title": session_title,
            "opening_segment": segment,
            "verified_stream_state": {
                "obs_output": "active",
                "youtube_stream": "active",
                "youtube_broadcast": "live",
                "stream_session": "live",
            },
        }
        try:
            self._publish("stream_opening.output_started", common, activity.trace_id)
            activity = self._openings.save(
                activity.transition(StreamOpeningStatus.WAITING_FOR_OUTPUT)
            )
            self._publish(
                "stream_opening.speech_started", self._event_data(activity), activity.trace_id
            )
            turn = await self._executor(payload, activity.trace_id)
        except Exception as error:
            return self._fail(activity, f"opening.output.{type(error).__name__}")
        speak = next(
            (
                item
                for item in (turn.output_result.action_results if turn.output_result else ())
                if item.action_type == ActionType.SPEAK.value
            ),
            None,
        )
        result: dict[str, object] = {
            "activity_turn_id": turn.activity_turn_id,
            "generation_id": turn.character_result.result_id if turn.character_result else None,
            "action_id": speak.action_id if speak else None,
            "final_status": turn.final_status,
        }
        if speak is None or speak.status != ActionExecutionStatus.COMPLETED:
            return self._fail(
                activity, turn.failure_stage or "opening.speech.failed", result=result
            )
        activity = self._openings.save(
            activity.transition(
                StreamOpeningStatus.COMPLETED,
                activity_turn_id=turn.activity_turn_id,
                result=result,
            )
        )
        self._publish("stream_opening.completed", self._event_data(activity), activity.trace_id)
        if self._completed_handler is not None:
            try:
                await self._completed_handler(
                    activity,
                    {
                        "obs_output": "active",
                        "youtube_stream": "active",
                        "youtube_broadcast": "live",
                        "stream_session": "live",
                    },
                )
            except Exception:
                # Opening完了とSession LIVEは巻き戻さず、main側の状態だけで失敗を表す。
                pass
        return activity

    def _create_failed(
        self, session_id: str, trace_id: str, segment_id: str | None, code: str
    ) -> StreamOpeningActivity:
        activity = StreamOpeningActivity(session_id, trace_id, segment_id)
        self._openings.create(activity)
        session = self._sessions.get(session_id)
        if session is not None and session.status == StreamSessionStatus.LIVE:
            self._sessions.save(session.attach_opening(activity.activity_id))
        return self._fail(activity.transition(StreamOpeningStatus.RUNNING), code)

    def _fail(
        self, activity: StreamOpeningActivity, code: str, *, result: dict[str, object] | None = None
    ) -> StreamOpeningActivity:
        if self._openings.find_by_session(activity.session_id) == activity:
            running = activity
        else:
            running = self._openings.save(activity)
        failed = self._openings.save(
            running.transition(StreamOpeningStatus.FAILED, failure_code=code, result=result)
        )
        self._publish("stream_opening.failed", self._event_data(failed), failed.trace_id)
        return failed

    @staticmethod
    def _event_data(activity: StreamOpeningActivity) -> dict[str, object]:
        return {
            "session_id": activity.session_id,
            "activity_id": activity.activity_id,
            "segment_id": activity.segment_id,
            "status": activity.status.value,
            "attempt": activity.attempt,
            "failure_code": activity.failure_code,
            "manual_intervention_required": activity.manual_intervention_required,
        }
