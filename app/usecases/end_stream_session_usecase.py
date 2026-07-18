from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from app.domain.actions import ActionType
from app.domain.activity_turn_result import ActionExecutionStatus, ActivityTurnResult
from app.domain.streaming import (
    ApproveNormalStreamEndCommand,
    EmergencyStopStreamCommand,
    LifecycleOperation,
    StreamClosingActivity,
    StreamClosingStatus,
    StreamEndRejected,
    StreamEndResult,
    StreamMainSegmentActivity,
    StreamMainSegmentStatus,
    StreamSession,
    StreamSessionStatus,
)
from app.domain.streaming.health import utc_now
from app.ports.streaming_control import ObsStreamingControlPort, YouTubeStreamingControlPort
from app.ports.streaming_preparation import RunOfShowRepository, StreamSessionRepository
from app.usecases.stream_lifecycle_gate import StreamLifecycleGate

EndEventPublisher = Callable[[str, dict[str, object], str], None]
ClosingExecutor = Callable[[dict[str, object], str], Awaitable[ActivityTurnResult]]
OutputCanceler = Callable[[], bool]
EndCommand = ApproveNormalStreamEndCommand | EmergencyStopStreamCommand


class MainSegmentReader(Protocol):
    def find_by_session(self, session_id: str) -> StreamMainSegmentActivity | None: ...


class EndStreamSessionUsecase:
    def __init__(
        self,
        *,
        sessions: StreamSessionRepository,
        main_segments: MainSegmentReader,
        run_of_show: RunOfShowRepository,
        obs: ObsStreamingControlPort,
        youtube: YouTubeStreamingControlPort,
        closing_executor: ClosingExecutor,
        output_canceler: OutputCanceler,
        event_publisher: EndEventPublisher | None = None,
        test_mode: bool = False,
        lifecycle_gate: StreamLifecycleGate | None = None,
    ) -> None:
        self._sessions = sessions
        self._main = main_segments
        self._ros = run_of_show
        self._obs = obs
        self._youtube = youtube
        self._closing_executor = closing_executor
        self._cancel_output = output_canceler
        self._publish = event_publisher or (lambda _event, _data, _trace: None)
        self._test_mode = test_mode
        self._results: dict[str, StreamEndResult] = {}
        self._latest: StreamEndResult | None = None
        self._lock = asyncio.Lock()
        self._closing: dict[str, StreamClosingActivity] = {}
        self._normal_task: asyncio.Task[object] | None = None
        self._gate = lifecycle_gate

    @property
    def latest_result(self) -> StreamEndResult | None:
        return self._latest

    async def normal(self, command: ApproveNormalStreamEndCommand) -> StreamEndResult:
        if command.command_id in self._results:
            return self._results[command.command_id]
        current_task = asyncio.current_task()
        self._normal_task = current_task
        try:
            async with self._lock:
                return await self._normal_locked(command)
        finally:
            if self._normal_task is current_task:
                self._normal_task = None

    async def _normal_locked(self, command: ApproveNormalStreamEndCommand) -> StreamEndResult:
        session = self._validate(command.session_id, command.expected_state_version)
        if self._gate is not None:
            decision = self._gate.evaluate(
                LifecycleOperation.START_NORMAL_END,
                session.session_id,
                expected_version=command.expected_state_version,
                trace_id=command.trace_id,
            )
            if not decision.allowed:
                raise StreamEndRejected(decision.reason_code or "lifecycle.operation_not_allowed")
        if session.status not in {StreamSessionStatus.LIVE, StreamSessionStatus.STOP_FAILED}:
            raise StreamEndRejected("stream.end.normal.invalid_state")
        main = self._main.find_by_session(session.session_id)
        if main is None or main.status != StreamMainSegmentStatus.COMPLETED:
            raise StreamEndRejected("stream.end.main.not_completed")
        self._ensure_adapter_mode()
        started = utc_now()
        if session.status == StreamSessionStatus.LIVE:
            session = self._sessions.save(
                session.transition(StreamSessionStatus.CLOSING_REQUESTED, trace_id=command.trace_id)
            )
            self._event("stream_end.approved", command.trace_id, session.session_id)
            session = self._sessions.save(session.transition(StreamSessionStatus.CLOSING))
        closing_status = "completed"
        existing = self._closing.get(session.session_id)
        if existing is None or existing.status != StreamClosingStatus.COMPLETED:
            closing_status = await self._run_closing(session, command.trace_id)
            if closing_status != "completed":
                return self._failure(
                    command,
                    session,
                    started,
                    "closing",
                    closing_status,
                    "stream.end.closing_failed",
                )
        session = self._sessions.get(session.session_id) or session
        if session.status != StreamSessionStatus.STOPPING:
            session = self._sessions.save(session.transition(StreamSessionStatus.STOPPING))
        self._event("stream_end.stopping", command.trace_id, session.session_id)
        return await self._stop_external(command, session, started, "normal", closing_status)

    async def emergency(self, command: EmergencyStopStreamCommand) -> StreamEndResult:
        if command.command_id in self._results:
            return self._results[command.command_id]
        self._cancel_output()
        normal_task = self._normal_task
        if normal_task is not None and normal_task is not asyncio.current_task():
            normal_task.cancel()
        async with self._lock:
            session = self._validate_emergency(command.session_id, command.expected_state_version)
            if self._gate is not None:
                decision = self._gate.evaluate(
                    LifecycleOperation.START_EMERGENCY_STOP,
                    session.session_id,
                    trace_id=command.trace_id,
                )
                if not decision.allowed:
                    raise StreamEndRejected(
                        decision.reason_code or "lifecycle.operation_not_allowed"
                    )
            allowed = {
                StreamSessionStatus.LIVE,
                StreamSessionStatus.CLOSING_REQUESTED,
                StreamSessionStatus.CLOSING,
                StreamSessionStatus.STOPPING,
                StreamSessionStatus.STOP_FAILED,
            }
            if session.status not in allowed:
                raise StreamEndRejected("stream.end.emergency.invalid_state")
            self._ensure_adapter_mode()
            started = utc_now()
            session = self._sessions.save(
                session.transition(
                    StreamSessionStatus.EMERGENCY_STOP_REQUESTED, trace_id=command.trace_id
                )
            )
            self._event(
                "stream_emergency_stop.requested",
                command.trace_id,
                session.session_id,
                reason_code=command.reason_code,
            )
            canceled = self._cancel_output()
            self._event(
                "stream_emergency_stop.output_cancel_requested",
                command.trace_id,
                session.session_id,
                cancel_supported=canceled,
            )
            session = self._sessions.save(
                session.transition(StreamSessionStatus.EMERGENCY_STOPPING)
            )
            self._event("stream_emergency_stop.stopping", command.trace_id, session.session_id)
            return await self._stop_external(command, session, started, "emergency", "canceled")

    async def _run_closing(self, session: StreamSession, trace_id: str) -> str:
        if self._gate is not None:
            decision = self._gate.evaluate(
                LifecycleOperation.START_CLOSING,
                session.session_id,
                trace_id=trace_id,
            )
            if not decision.allowed:
                return "failed"
        run_of_show_id = session.run_of_show_id
        if not run_of_show_id:
            return "failed"
        segment = self._ros.get_closing_segment(run_of_show_id)
        if segment is None:
            return "failed"
        activity = StreamClosingActivity(
            session.session_id, trace_id, segment.segment_id
        ).with_status(StreamClosingStatus.RUNNING)
        self._closing[activity.session_id] = activity
        self._event(
            "stream_closing.started",
            trace_id,
            activity.session_id,
            activity_id=activity.activity_id,
            segment_id=segment.segment_id,
        )
        try:
            self._event("stream_closing.output_started", trace_id, activity.session_id)
            turn = await self._closing_executor(
                {
                    "session_id": session.session_id,
                    "closing_segment": {
                        "segment_id": segment.segment_id,
                        "title": segment.title,
                        "intent": segment.intent,
                        "duration_seconds": segment.duration_seconds,
                    },
                    "verified_stream_state": {"stream_session": "closing"},
                },
                trace_id,
            )
            speak = next(
                (
                    item
                    for item in (turn.output_result.action_results if turn.output_result else ())
                    if item.action_type == ActionType.SPEAK.value
                ),
                None,
            )
            if speak is None or speak.status != ActionExecutionStatus.COMPLETED:
                raise RuntimeError(turn.failure_stage or "closing.speech.failed")
        except Exception as error:
            self._closing[activity.session_id] = activity.with_status(
                StreamClosingStatus.FAILED, str(error)
            )
            return "failed"
        self._closing[activity.session_id] = activity.with_status(StreamClosingStatus.COMPLETED)
        self._event("stream_closing.completed", trace_id, activity.session_id)
        return "completed"

    async def _stop_external(
        self,
        command: EndCommand,
        session: StreamSession,
        started: datetime,
        mode: str,
        closing_status: str,
    ) -> StreamEndResult:
        broadcast = "unknown"
        obs = "unknown"
        try:
            if mode == "emergency":
                obs = await self._stop_obs_output()
            if broadcast != "complete":
                broadcast = await self._youtube.get_broadcast_status(
                    session.selected_broadcast_id
                )
            if broadcast != "complete":
                await self._youtube.transition_broadcast_to_complete(session.selected_broadcast_id)
            broadcast = await self._youtube.get_broadcast_status(session.selected_broadcast_id)
            if broadcast != "complete":
                raise RuntimeError("broadcast_not_complete")
            self._event(
                "stream_end.broadcast_complete"
                if mode == "normal"
                else "stream_emergency_stop.broadcast_complete",
                command.trace_id,
                session.session_id,
            )
            if mode == "normal":
                obs = await self._stop_obs_output()
            stream = await self._youtube.get_stream_status(session.selected_stream_id or "")
            if obs != "idle" or stream not in {"inactive", "no_data"}:
                raise RuntimeError("external_state_not_stopped")
        except Exception as error:
            return self._failure(
                command,
                session,
                started,
                "external_stop",
                closing_status,
                f"stream.end.{type(error).__name__}",
                broadcast=broadcast,
            )
        current = self._sessions.get(session.session_id) or session
        final_status = (
            StreamSessionStatus.COMPLETED
            if mode == "normal"
            else StreamSessionStatus.EMERGENCY_STOPPED
        )
        self._sessions.save(current.transition(final_status))
        event_prefix = "stream_end" if mode == "normal" else "stream_emergency_stop"
        self._event(f"{event_prefix}.obs_idle", command.trace_id, session.session_id)
        result = StreamEndResult(
            session.session_id,
            command.trace_id,
            command.command_id,
            mode,
            True,
            None,
            closing_status,
            broadcast,
            stream,
            obs,
            None,
            False,
            False,
            started,
            utc_now(),
        )
        self._results[result.command_id] = result
        self._latest = result
        self._event(f"{event_prefix}.completed", result.trace_id, result.session_id)
        return result

    async def _stop_obs_output(self) -> str:
        status = await self._obs.get_output_status()
        if status != "idle":
            await self._obs.stop_stream()
        return await self._obs.get_output_status()

    def _failure(
        self,
        command: EndCommand,
        session: StreamSession,
        started: datetime,
        step: str,
        closing: str,
        code: str,
        *,
        broadcast: str = "unknown",
    ) -> StreamEndResult:
        current = self._sessions.get(session.session_id) or session
        if current.status in {
            StreamSessionStatus.CLOSING,
            StreamSessionStatus.STOPPING,
            StreamSessionStatus.EMERGENCY_STOPPING,
        }:
            self._sessions.save(current.transition(StreamSessionStatus.STOP_FAILED))
        result = StreamEndResult(
            session.session_id,
            command.trace_id,
            command.command_id,
            "emergency" if isinstance(command, EmergencyStopStreamCommand) else "normal",
            False,
            step,
            closing,
            broadcast,
            "unknown",
            "unknown",
            code,
            True,
            True,
            started,
            utc_now(),
        )
        self._results[result.command_id] = result
        self._latest = result
        prefix = "stream_emergency_stop" if result.end_mode == "emergency" else "stream_end"
        self._event(f"{prefix}.failed", result.trace_id, result.session_id, failure_code=code)
        return result

    def _validate(self, session_id: str, version: int) -> StreamSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise StreamEndRejected("stream.session.not_found")
        if session.state_version != version:
            raise StreamEndRejected("stream.end.version_mismatch")
        return session

    def _validate_emergency(self, session_id: str, version: int) -> StreamSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise StreamEndRejected("stream.session.not_found")
        ending = session.status in {
            StreamSessionStatus.CLOSING_REQUESTED,
            StreamSessionStatus.CLOSING,
            StreamSessionStatus.STOPPING,
        }
        if session.state_version != version and not ending:
            raise StreamEndRejected("stream.end.version_mismatch")
        return session

    def _ensure_adapter_mode(self) -> None:
        if not self._test_mode and (
            self._obs.adapter_type == "fake" or self._youtube.adapter_type == "fake"
        ):
            raise StreamEndRejected("stream.end.fake_requires_test_mode")

    def _event(self, event: str, trace_id: str, session_id: str, **data: object) -> None:
        self._publish(event, {"session_id": session_id, **data}, trace_id)
