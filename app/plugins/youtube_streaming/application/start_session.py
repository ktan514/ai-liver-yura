"""Start a prepared YouTube streaming session."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.plugins.youtube_streaming.domain import (
    ApproveStreamStartCommand,
    StreamSessionStatus,
    StreamStartRejected,
    StreamStartResult,
)
from app.plugins.youtube_streaming.domain.health import utc_now
from app.ports.streaming_control import (
    ObsStreamingControlPort,
    YouTubeStreamingControlPort,
)
from app.ports.streaming_preparation import StreamSessionRepository
from app.utils.trace import TraceLogger

StartEventPublisher = Callable[[str, dict[str, object], str], None]


class StartStreamSessionUsecase:
    def __init__(
        self,
        *,
        sessions: StreamSessionRepository,
        obs: ObsStreamingControlPort,
        youtube: YouTubeStreamingControlPort,
        event_publisher: StartEventPublisher | None = None,
        poll_interval_seconds: float = 1.0,
        step_timeout_seconds: float = 30.0,
        trace_logger: TraceLogger | None = None,
        allow_fake_youtube: bool = False,
    ) -> None:
        self._sessions = sessions
        self._obs = obs
        self._youtube = youtube
        self._publish = event_publisher or (lambda event, data, trace: None)
        self._poll_interval = poll_interval_seconds
        self._step_timeout = step_timeout_seconds
        self._trace = trace_logger or TraceLogger()
        self._allow_fake_youtube = allow_fake_youtube
        self._results: dict[str, StreamStartResult] = {}
        self._latest: StreamStartResult | None = None
        self._lock = asyncio.Lock()

    @property
    def latest_result(self) -> StreamStartResult | None:
        return self._latest

    def set_event_publisher(self, publisher: StartEventPublisher) -> None:
        self._publish = publisher

    @property
    def uses_test_adapter(self) -> bool:
        return self._obs.adapter_type not in {"obs_websocket", "demo_fake"} or (
            self._youtube.adapter_type == "fake" and not self._allow_fake_youtube
        )

    async def execute(self, command: ApproveStreamStartCommand) -> StreamStartResult:
        async with self._lock:
            cached = self._results.get(command.command_id)
            if cached is not None:
                return replace(cached, duplicate=True)
            result = await self._execute_once(command)
            self._results[command.command_id] = result
            self._latest = result
            return result

    def validate(self, command: ApproveStreamStartCommand) -> None:
        session = self._sessions.get(command.session_id)
        if session is None:
            raise StreamStartRejected("stream.session.not_found")
        if self._obs.adapter_type not in {"obs_websocket", "demo_fake"}:
            raise StreamStartRejected("stream.start.test_adapter")
        if self._youtube.adapter_type == "fake" and not self._allow_fake_youtube:
            raise StreamStartRejected("stream.start.test_adapter")
        if session.state_version != command.expected_state_version:
            raise StreamStartRejected("stream.start.version_mismatch")
        if not command.approved_by.strip():
            raise StreamStartRejected("request.invalid")
        if session.status not in {
            StreamSessionStatus.READY,
            StreamSessionStatus.START_FAILED,
        }:
            raise StreamStartRejected("stream.start.not_ready")

    async def _execute_once(
        self, command: ApproveStreamStartCommand
    ) -> StreamStartResult:
        self.validate(command)
        session = self._sessions.get(command.session_id)
        assert session is not None
        if session.status == StreamSessionStatus.START_FAILED:
            session = self._sessions.save(
                session.transition(StreamSessionStatus.READY, failure_reasons=())
            )
        if session.status != StreamSessionStatus.READY or not session.can_start:
            raise StreamStartRejected("stream.start.not_ready")

        approved = self._sessions.save(
            session.transition(
                StreamSessionStatus.START_APPROVED,
                trace_id=command.trace_id,
                start_approved_by=command.approved_by,
                start_approved_at=command.approved_at,
            )
        )
        self._event(
            "stream_start.approved",
            command,
            approved_by=command.approved_by,
            approved_at=command.approved_at.isoformat(),
            attempt=1,
        )
        starting = self._sessions.save(
            approved.transition(StreamSessionStatus.STARTING, trace_id=command.trace_id)
        )
        self._event("stream_start.started", command)
        started_at = utc_now()
        obs_status = "unknown"
        stream_status = "unknown"
        broadcast_status = "unknown"
        step = "obs_start"
        try:
            obs_status = await self._obs.get_output_status()
            if obs_status not in {"active", "starting", "idle"}:
                raise StreamStartRejected("stream.start.obs_failed")
            if obs_status == "idle":
                await self._obs.start_stream()
                self._event(
                    "stream_start.step_updated", command, step="obs_start_requested"
                )
            step = "obs_active"
            obs_status = await self._poll(
                self._obs.get_output_status, "active", "obs_active"
            )
            self._event("stream_start.obs_active", command, obs_status=obs_status)

            stream_id = starting.selected_stream_id
            if not stream_id:
                raise StreamStartRejected("stream.start.youtube_stream_missing")
            step = "youtube_stream_active"
            stream_status = await self._poll(
                lambda: self._youtube.get_stream_status(stream_id),
                "active",
                "youtube_stream_active",
            )
            self._event(
                "stream_start.youtube_stream_active",
                command,
                youtube_stream_status=stream_status,
            )

            step = "broadcast_transition"
            broadcast_status = await self._youtube.get_broadcast_status(
                starting.selected_broadcast_id
            )
            if broadcast_status not in {"live", "ready", "testing"}:
                raise StreamStartRejected("stream.start.broadcast_transition_failed")
            if broadcast_status != "live":
                await self._youtube.transition_broadcast_to_live(
                    starting.selected_broadcast_id
                )
                self._event("stream_start.broadcast_transition_requested", command)
            step = "broadcast_live"
            broadcast_status = await self._poll(
                lambda: self._youtube.get_broadcast_status(
                    starting.selected_broadcast_id
                ),
                "live",
                "broadcast_live",
            )
            self._event("stream_start.broadcast_live", command)

            # Reconfirm all external states; no inferred success is allowed.
            obs_status = await self._obs.get_output_status()
            stream_status = await self._youtube.get_stream_status(stream_id)
            broadcast_status = await self._youtube.get_broadcast_status(
                starting.selected_broadcast_id
            )
            if (obs_status, stream_status, broadcast_status) != (
                "active",
                "active",
                "live",
            ):
                raise StreamStartRejected("stream.start.external_state_changed")
            live = self._sessions.save(
                starting.transition(StreamSessionStatus.LIVE, trace_id=command.trace_id)
            )
            result = StreamStartResult(
                live.session_id,
                command.trace_id,
                command.command_id,
                live.status.value,
                True,
                None,
                obs_status,
                stream_status,
                broadcast_status,
                None,
                False,
                started_at,
                utc_now(),
            )
            self._event("stream_start.completed", command, status="live")
            self._trace.info(
                "stream_start:completed",
                trace_id=command.trace_id,
                session_id=command.session_id,
                command_id=command.command_id,
                approved_by=command.approved_by,
            )
            return result
        except Exception as error:
            code = (
                error.code
                if isinstance(error, StreamStartRejected)
                else self._failure_code(step)
            )
            current = self._sessions.get(command.session_id) or starting
            failed = self._sessions.save(
                current.transition(
                    StreamSessionStatus.START_FAILED,
                    trace_id=command.trace_id,
                    failure_reasons=(code,),
                )
            )
            manual = (
                obs_status == "active"
                or stream_status == "active"
                or broadcast_status == "live"
            )
            result = StreamStartResult(
                failed.session_id,
                command.trace_id,
                command.command_id,
                failed.status.value,
                False,
                step,
                obs_status,
                stream_status,
                broadcast_status,
                code,
                manual,
                started_at,
                utc_now(),
            )
            self._event(
                "stream_start.failed",
                command,
                failed_step=step,
                failure_code=code,
                manual_intervention_required=manual,
            )
            return result

    async def _poll(
        self, read: Callable[[], Awaitable[str]], expected: str, step: str
    ) -> str:
        deadline = asyncio.get_running_loop().time() + self._step_timeout
        while True:
            value = str(await read())
            if value == expected:
                return value
            if value in {"unknown", "failed", "disconnected", "error"}:
                raise StreamStartRejected(self._failure_code(step))
            if asyncio.get_running_loop().time() >= deadline:
                raise StreamStartRejected(self._failure_code(step))
            await asyncio.sleep(self._poll_interval)

    @staticmethod
    def _failure_code(step: str) -> str:
        return {
            "obs_start": "stream.start.obs_failed",
            "obs_active": "stream.start.obs_active_timeout",
            "youtube_stream_active": "stream.start.youtube_stream_timeout",
            "broadcast_transition": "stream.start.broadcast_transition_failed",
            "broadcast_live": "stream.start.broadcast_live_timeout",
        }.get(step, "stream.start.failed")

    def _event(
        self, event_type: str, command: ApproveStreamStartCommand, **data: object
    ) -> None:
        self._publish(
            event_type,
            {
                "session_id": command.session_id,
                "command_id": command.command_id,
                **data,
            },
            command.trace_id,
        )
        audit: dict[str, object] = {
            "trace_id": command.trace_id,
            "session_id": command.session_id,
            "command_id": command.command_id,
            "approved_by": command.approved_by,
            "approved_at": command.approved_at,
        }
        audit.update(data)
        self._trace.info(event_type.replace(".", ":"), **audit)
