from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.plugins.youtube_streaming.domain import (
    LifecycleDecision,
    LifecycleOperation,
    StreamLifecycleClass,
    StreamMainSegmentStatus,
    StreamOpeningStatus,
    StreamSession,
    StreamSessionStatus,
    classify_lifecycle,
)
from app.ports.streaming_preparation import StreamSessionRepository


class ActivityReader(Protocol):
    def find_by_session(self, session_id: str) -> object | None: ...


LifecyclePublisher = Callable[[str, dict[str, object], str], None]


class StreamLifecycleGate:
    """配信Lifecycleに関する全操作の共通Policy判定点。"""

    _LIVE_EXTERNAL_OPERATIONS = {
        LifecycleOperation.START_OPENING,
        LifecycleOperation.START_MAIN_SEGMENT,
        LifecycleOperation.START_COMMENT_POLLING,
        LifecycleOperation.CONTINUE_COMMENT_POLLING,
        LifecycleOperation.EVALUATE_COMMENT,
        LifecycleOperation.EMIT_COMMENT_CANDIDATE,
        LifecycleOperation.SELECT_COMMENT_RESPONSE_TARGET,
        LifecycleOperation.START_COMMENT_RESPONSE,
        LifecycleOperation.GENERATE_COMMENT_RESPONSE,
        LifecycleOperation.ENQUEUE_COMMENT_RESPONSE_ACTION,
        LifecycleOperation.START_COMMENT_RESPONSE_SPEECH,
        LifecycleOperation.START_AUTONOMOUS_TALK,
        LifecycleOperation.SELECT_TOPIC,
    }
    _OUTPUT_OPERATIONS = {
        LifecycleOperation.START_LLM_GENERATION,
        LifecycleOperation.CREATE_ACTION_PLAN,
        LifecycleOperation.ENQUEUE_ACTION,
        LifecycleOperation.START_SPEECH,
        LifecycleOperation.UPDATE_SUBTITLE,
        LifecycleOperation.CHANGE_EXPRESSION,
        LifecycleOperation.START_MOTION,
    }

    def __init__(
        self,
        *,
        sessions: StreamSessionRepository,
        openings: ActivityReader,
        main_segments: ActivityReader,
        publisher: LifecyclePublisher | None = None,
    ) -> None:
        self._sessions = sessions
        self._openings = openings
        self._main = main_segments
        self._publisher = publisher or (lambda _event, _data, _trace: None)
        self._external: dict[str, dict[str, str]] = {}
        self._last_notifications: dict[
            tuple[str, str], tuple[bool, str | None, int]
        ] = {}
        active = sessions.find_active_or_preparing()
        self._current_session_id = active.session_id if active is not None else None

    def update_external_state(self, session_id: str, state: dict[str, str]) -> None:
        self._external[session_id] = dict(state)

    def active_session_id(self) -> str | None:
        session = self._sessions.find_active_or_preparing()
        if session is not None:
            self._current_session_id = session.session_id
        return self._current_session_id

    def evaluate(
        self,
        operation: LifecycleOperation,
        session_id: str,
        *,
        activity_type: str | None = None,
        expected_version: int | None = None,
        trace_id: str = "",
    ) -> LifecycleDecision:
        session = self._sessions.get(session_id)
        if session is None:
            return self._decision(
                operation,
                session_id,
                None,
                False,
                "lifecycle.stale_session",
                True,
                trace_id,
            )
        active = self._sessions.find_active_or_preparing()
        if active is not None and active.session_id != session_id:
            return self._decision(
                operation,
                session_id,
                session,
                False,
                "lifecycle.stale_session",
                True,
                trace_id,
            )
        if expected_version is not None and session.state_version != expected_version:
            return self._decision(
                operation,
                session_id,
                session,
                False,
                "lifecycle.version_mismatch",
                False,
                trace_id,
            )
        category = classify_lifecycle(session.status)
        if operation == LifecycleOperation.START_EMERGENCY_STOP:
            allowed = session.status in {
                StreamSessionStatus.LIVE,
                StreamSessionStatus.CLOSING_REQUESTED,
                StreamSessionStatus.CLOSING,
                StreamSessionStatus.STOPPING,
                StreamSessionStatus.STOP_FAILED,
                StreamSessionStatus.COMPLETED,
                StreamSessionStatus.EMERGENCY_STOPPED,
            }
            return self._decision(
                operation,
                session_id,
                session,
                allowed,
                None if allowed else "lifecycle.operation_not_allowed",
                not allowed,
                trace_id,
            )
        if category == StreamLifecycleClass.TERMINAL:
            return self._decision(
                operation,
                session_id,
                session,
                False,
                "lifecycle.terminal",
                False,
                trace_id,
            )
        if category == StreamLifecycleClass.EMERGENCY_ENDING:
            return self._decision(
                operation,
                session_id,
                session,
                False,
                "lifecycle.emergency_stopping",
                True,
                trace_id,
            )
        if operation == LifecycleOperation.START_NORMAL_END:
            allowed = session.status in {
                StreamSessionStatus.LIVE,
                StreamSessionStatus.STOP_FAILED,
            }
            return self._decision(
                operation,
                session_id,
                session,
                allowed,
                None if allowed else "lifecycle.operation_not_allowed",
                session.status == StreamSessionStatus.STOP_FAILED,
                trace_id,
            )
        if operation == LifecycleOperation.START_CLOSING:
            allowed = session.status in {
                StreamSessionStatus.CLOSING_REQUESTED,
                StreamSessionStatus.CLOSING,
            }
            return self._decision(
                operation,
                session_id,
                session,
                allowed,
                None if allowed else "lifecycle.ending",
                False,
                trace_id,
            )
        if (
            operation in self._OUTPUT_OPERATIONS
            and activity_type == "stream_closing_greeting"
        ):
            allowed = session.status in {
                StreamSessionStatus.CLOSING_REQUESTED,
                StreamSessionStatus.CLOSING,
            }
            return self._decision(
                operation,
                session_id,
                session,
                allowed,
                None if allowed else "lifecycle.operation_not_allowed",
                False,
                trace_id,
            )
        if category == StreamLifecycleClass.NORMAL_ENDING:
            return self._decision(
                operation,
                session_id,
                session,
                False,
                "lifecycle.ending",
                False,
                trace_id,
            )
        if category == StreamLifecycleClass.FAILED:
            return self._decision(
                operation,
                session_id,
                session,
                False,
                "lifecycle.failed",
                True,
                trace_id,
            )
        if session.status != StreamSessionStatus.LIVE:
            return self._decision(
                operation,
                session_id,
                session,
                False,
                "lifecycle.not_live",
                False,
                trace_id,
            )
        if operation == LifecycleOperation.START_MAIN_SEGMENT:
            opening = self._openings.find_by_session(session_id)
            if (
                opening is None
                or getattr(opening, "status", None) != StreamOpeningStatus.COMPLETED
            ):
                return self._decision(
                    operation,
                    session_id,
                    session,
                    False,
                    "lifecycle.opening_not_completed",
                    False,
                    trace_id,
                )
        if operation in {
            LifecycleOperation.SELECT_COMMENT_RESPONSE_TARGET,
            LifecycleOperation.START_COMMENT_RESPONSE,
            LifecycleOperation.GENERATE_COMMENT_RESPONSE,
            LifecycleOperation.ENQUEUE_COMMENT_RESPONSE_ACTION,
            LifecycleOperation.START_COMMENT_RESPONSE_SPEECH,
        }:
            main = self._main.find_by_session(session_id)
            if (
                main is None
                or getattr(main, "status", None) != StreamMainSegmentStatus.COMPLETED
            ):
                return self._decision(
                    operation,
                    session_id,
                    session,
                    False,
                    "lifecycle.main_segment_not_completed",
                    False,
                    trace_id,
                )
        if operation in self._LIVE_EXTERNAL_OPERATIONS | self._OUTPUT_OPERATIONS:
            external = self._external.get(session_id)
            if external is None or "unknown" in external.values():
                return self._decision(
                    operation,
                    session_id,
                    session,
                    False,
                    "lifecycle.external_state_unknown",
                    True,
                    trace_id,
                )
            if external != {
                "obs_output": "active",
                "youtube_stream": "active",
                "youtube_broadcast": "live",
                "stream_session": "live",
            }:
                return self._decision(
                    operation,
                    session_id,
                    session,
                    False,
                    "lifecycle.external_state_mismatch",
                    True,
                    trace_id,
                )
        return self._decision(
            operation, session_id, session, True, None, False, trace_id
        )

    def evaluate_policy(
        self,
        operation: str,
        context_id: str,
        *,
        activity_type: str | None = None,
        trace_id: str = "",
    ) -> LifecycleDecision:
        return self.evaluate(
            LifecycleOperation(operation),
            context_id,
            activity_type=activity_type,
            trace_id=trace_id,
        )

    def snapshot(self, session_id: str) -> dict[str, object]:
        session = self._sessions.get(session_id)
        operations = {}
        for operation in LifecycleOperation:
            decision = self.evaluate(operation, session_id)
            operations[operation.value] = {
                "allowed": decision.allowed,
                "reason_code": decision.reason_code,
            }
        return {
            "session_id": session_id,
            "session_status": session.status.value if session else "missing",
            "lifecycle_class": (
                classify_lifecycle(session.status).value if session else "failed"
            ),
            "state_version": session.state_version if session else None,
            "operations": operations,
        }

    def _decision(
        self,
        operation: LifecycleOperation,
        session_id: str,
        session: StreamSession | None,
        allowed: bool,
        reason: str | None,
        manual: bool,
        trace_id: str,
    ) -> LifecycleDecision:
        decision = LifecycleDecision(
            allowed,
            reason,
            session.status.value if session else "missing",
            operation in self._LIVE_EXTERNAL_OPERATIONS | self._OUTPUT_OPERATIONS,
            manual,
        )
        version = session.state_version if session else -1
        key = (session_id, operation.value)
        signature = (allowed, reason, version)
        if self._last_notifications.get(key) != signature:
            self._last_notifications[key] = signature
            event = (
                "stream_lifecycle.updated"
                if allowed
                else "stream_lifecycle.operation_blocked"
            )
            self._publisher(
                event,
                {
                    "session_id": session_id,
                    "operation": operation.value,
                    "allowed": allowed,
                    "reason_code": reason,
                    "session_status": decision.session_status,
                    "state_version": version,
                    "external_state_summary": (
                        dict(self._external[session_id])
                        if session_id in self._external
                        else "unknown"
                    ),
                    "evaluated_at": decision.evaluated_at.isoformat(),
                },
                trace_id,
            )
            if not allowed and operation in {
                LifecycleOperation.START_COMMENT_POLLING,
                LifecycleOperation.CONTINUE_COMMENT_POLLING,
            }:
                self._publisher(
                    "stream_lifecycle.polling_stop_required",
                    {"session_id": session_id, "reason_code": reason},
                    trace_id,
                )
            if not allowed and operation in self._OUTPUT_OPERATIONS:
                self._publisher(
                    "stream_lifecycle.actions_blocked",
                    {"session_id": session_id, "reason_code": reason},
                    trace_id,
                )
        return decision
