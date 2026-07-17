from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Protocol

from app.config.app_config import CommentResponseSettings
from app.domain.actions import ActionType
from app.domain.activity_turn_result import ActionExecutionStatus, ActivityTurnResult
from app.domain.streaming import (
    CommentResponseHistoryEntry,
    CommentResponseRejected,
    CommentResponseTarget,
    LifecycleOperation,
    RetryCommentResponseCommand,
    StreamCommentResponseActivity,
    StreamCommentResponseStatus,
)
from app.ports.comment_response import (
    CommentResponseActivityRepository,
    CompletedCommentResponseHistoryRepository,
)
from app.usecases.stream_lifecycle_gate import StreamLifecycleGate


class SelectionManager(Protocol):
    def selection(self, selection_id: str) -> CommentResponseTarget | None: ...
    def reacquire(self, selection_id: str) -> CommentResponseTarget | None: ...
    def release(self, selection_id: str) -> CommentResponseTarget | None: ...
    def consume(self, selection_id: str) -> CommentResponseTarget | None: ...


ResponseExecutor = Callable[[dict[str, object], str], Awaitable[ActivityTurnResult]]
ResponsePublisher = Callable[[str, dict[str, object], str], None]


class CommentResponseUsecase:
    def __init__(
        self,
        *,
        gate: StreamLifecycleGate,
        activities: CommentResponseActivityRepository,
        selections: SelectionManager,
        history: CompletedCommentResponseHistoryRepository,
        executor: ResponseExecutor,
        settings: CommentResponseSettings,
        publisher: ResponsePublisher | None = None,
    ) -> None:
        self._gate = gate
        self._activities = activities
        self._selections = selections
        self._history = history
        self._executor = executor
        self._settings = settings
        self._publish = publisher or (lambda _event, _data, _trace: None)

    def status(self, session_id: str) -> StreamCommentResponseActivity | None:
        return self._activities.find_by_session(session_id)

    def recent(self, session_id: str) -> tuple[CommentResponseHistoryEntry, ...]:
        return self._history.recent(session_id)

    async def start(
        self, session_id: str, selection_id: str, trace_id: str
    ) -> StreamCommentResponseActivity:
        if self._activities.find_by_selection(session_id, selection_id) is not None:
            raise CommentResponseRejected("comment_response.duplicate_activity")
        target = self._require_target(session_id, selection_id)
        try:
            self._require_gate(LifecycleOperation.START_COMMENT_RESPONSE, session_id, trace_id)
        except CommentResponseRejected:
            self._selections.release(selection_id)
            self._publish(
                "stream_comments.reservation_released",
                {"session_id": session_id, "selection_id": selection_id},
                trace_id,
            )
            raise
        activity = self._activities.create(
            StreamCommentResponseActivity(session_id, trace_id, selection_id, target.candidate_id)
        )
        return await self._execute(activity, target)

    async def retry(self, command: RetryCommentResponseCommand) -> StreamCommentResponseActivity:
        duplicate = self._activities.command_result(command.command_id)
        if duplicate is not None:
            return duplicate
        activity = self._activities.get(command.activity_id)
        if activity is None or activity.session_id != command.session_id:
            raise CommentResponseRejected("comment_response.activity_not_found")
        if activity.selection_id != command.selection_id:
            raise CommentResponseRejected("comment_response.selection_mismatch")
        if activity.version != command.expected_activity_version:
            raise CommentResponseRejected("comment_response.version_mismatch")
        if activity.status != StreamCommentResponseStatus.FAILED:
            raise CommentResponseRejected(f"comment_response.retry.{activity.status.value}")
        if activity.attempt > self._settings.max_retries:
            raise CommentResponseRejected("comment_response.retry_limit")
        target = self._selections.reacquire(command.selection_id)
        if target is None:
            raise CommentResponseRejected("comment_response.reservation_unavailable")
        result = await self._execute(activity, target)
        return self._activities.save_command_result(command.command_id, result)

    async def _execute(
        self, activity: StreamCommentResponseActivity, target: CommentResponseTarget
    ) -> StreamCommentResponseActivity:
        activity = self._activities.save(activity.transition(StreamCommentResponseStatus.RUNNING))
        self._publish("stream_comments.response_started", self._event(activity), activity.trace_id)
        payload = {
            "session_id": activity.session_id,
            "activity_type": "stream_comment_response",
            "plugin_id": "youtube_streaming",
            "comment_response_target": {
                "selection_id": target.selection_id,
                "candidate_id": target.candidate_id,
                "sanitized_text": target.sanitized_text,
                "selected_score": target.selected_score,
                "selected_rank": target.selected_rank,
                "selection_reason": target.selection_reason,
                "author_id": target.author_id,
            },
            "comment_is_untrusted_external_data": True,
            "response_style": {
                "max_characters": self._settings.max_characters,
                "max_sentences": self._settings.max_sentences,
                "allow_follow_up_question": self._settings.allow_follow_up_question,
                "mention_author_name": self._settings.mention_author_name,
                "repeat_comment_text": self._settings.repeat_comment_text,
            },
            "verified_stream_state": {
                "obs_output": "active",
                "youtube_stream": "active",
                "youtube_broadcast": "live",
                "stream_session": "live",
            },
        }
        try:
            self._require_target(activity.session_id, activity.selection_id)
            self._require_gate(
                LifecycleOperation.GENERATE_COMMENT_RESPONSE,
                activity.session_id,
                activity.trace_id,
            )
            self._publish(
                "stream_comments.response_generation_started",
                self._event(activity),
                activity.trace_id,
            )
            self._require_gate(
                LifecycleOperation.ENQUEUE_COMMENT_RESPONSE_ACTION,
                activity.session_id,
                activity.trace_id,
            )
            activity = self._activities.save(
                activity.transition(StreamCommentResponseStatus.WAITING_FOR_OUTPUT)
            )
            self._publish(
                "stream_comments.response_output_started",
                self._event(activity),
                activity.trace_id,
            )
            self._require_target(activity.session_id, activity.selection_id)
            self._require_gate(
                LifecycleOperation.START_COMMENT_RESPONSE_SPEECH,
                activity.session_id,
                activity.trace_id,
            )
            self._publish(
                "stream_comments.response_speech_started",
                self._event(activity),
                activity.trace_id,
            )
            turn = await self._executor(payload, activity.trace_id)
        except CommentResponseRejected as error:
            return self._fail(activity, error.code)
        except Exception as error:
            return self._fail(activity, f"comment_response.output.{type(error).__name__}")
        speak = next(
            (
                item
                for item in (turn.output_result.action_results if turn.output_result else ())
                if item.action_type == ActionType.SPEAK.value
            ),
            None,
        )
        response = turn.character_result.adopted_text if turn.character_result else None
        result: dict[str, object] = {
            "activity_turn_id": turn.activity_turn_id,
            "generation_id": turn.character_result.result_id if turn.character_result else None,
            "action_id": speak.action_id if speak else None,
            "final_status": turn.final_status,
        }
        if speak is None or speak.status != ActionExecutionStatus.COMPLETED:
            code = turn.failure_stage or "comment_response.tts_or_playback_failed"
            return self._fail(activity, code, result=result)
        if self._selections.consume(activity.selection_id) is None:
            return self._fail(activity, "comment_response.consume_conflict", result=result)
        activity = self._activities.save(
            activity.transition(StreamCommentResponseStatus.COMPLETED, result=result)
        )
        self._history.save(
            CommentResponseHistoryEntry(
                activity.session_id,
                activity.selection_id,
                activity.candidate_id,
                target.message_id,
                target.author_id,
                None,
                (response or "")[:80],
                "completed",
            )
        )
        self._publish(
            "stream_comments.reservation_consumed", self._event(activity), activity.trace_id
        )
        self._publish(
            "stream_comments.response_completed", self._event(activity), activity.trace_id
        )
        return activity

    def _fail(
        self,
        activity: StreamCommentResponseActivity,
        code: str,
        *,
        result: dict[str, object] | None = None,
    ) -> StreamCommentResponseActivity:
        target = self._selections.selection(activity.selection_id)
        released = self._selections.release(activity.selection_id)
        failed = self._activities.save(
            activity.transition(
                StreamCommentResponseStatus.FAILED,
                failure_code=code,
                retryable=released is not None,
                result=result,
            )
        )
        self._publish(
            "stream_comments.reservation_released",
            {**self._event(failed), "released": released is not None},
            activity.trace_id,
        )
        if target is not None:
            self._history.save(
                CommentResponseHistoryEntry(
                    activity.session_id,
                    activity.selection_id,
                    activity.candidate_id,
                    target.message_id,
                    target.author_id,
                    None,
                    "",
                    "failed",
                )
            )
        self._publish("stream_comments.response_failed", self._event(failed), activity.trace_id)
        return failed

    def _require_target(self, session_id: str, selection_id: str) -> CommentResponseTarget:
        target = self._selections.selection(selection_id)
        if target is None:
            raise CommentResponseRejected("comment_response.reservation_missing")
        if target.session_id != session_id:
            raise CommentResponseRejected("comment_response.stale_session")
        if target.reservation_status == "expired" or target.expires_at <= datetime.now(
            timezone.utc
        ):
            raise CommentResponseRejected("comment_response.reservation_expired")
        if target.reservation_status != "reserved":
            raise CommentResponseRejected("comment_response.reservation_missing")
        return target

    def _require_gate(self, operation: LifecycleOperation, session_id: str, trace_id: str) -> None:
        decision = self._gate.evaluate(operation, session_id, trace_id=trace_id)
        if not decision.allowed:
            raise CommentResponseRejected(
                decision.reason_code or "comment_response.lifecycle_blocked"
            )

    @staticmethod
    def _event(activity: StreamCommentResponseActivity) -> dict[str, object]:
        return {
            "session_id": activity.session_id,
            "activity_id": activity.activity_id,
            "selection_id": activity.selection_id,
            "candidate_id": activity.candidate_id,
            "message_id_hash": hashlib.sha256(activity.candidate_id.encode()).hexdigest()[:12],
            "status": activity.status.value,
            "attempt": activity.attempt,
            "failure_code": activity.failure_code,
            "retryable": activity.retryable,
            "started_at": activity.started_at.isoformat() if activity.started_at else None,
            "completed_at": activity.completed_at.isoformat() if activity.completed_at else None,
        }
