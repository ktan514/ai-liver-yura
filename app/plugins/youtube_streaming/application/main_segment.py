from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Protocol

from app.plugins.youtube_streaming.application.lifecycle_gate import StreamLifecycleGate
from app.plugins.youtube_streaming.domain import (
    LifecycleOperation,
    RetryMainSegmentCommand,
    StreamMainSegmentActivity,
    StreamMainSegmentRejected,
    StreamMainSegmentStatus,
    StreamOpeningActivity,
    StreamOpeningStatus,
    StreamSessionStatus,
)
from app.ports.streaming_preparation import RunOfShowRepository, StreamSessionRepository
from app.shared.contracts.plugins.runtime import SPEAK_ACTION_TYPE, PluginActivityResult


class MainSegmentRepository(Protocol):
    def create(
        self, activity: StreamMainSegmentActivity
    ) -> StreamMainSegmentActivity: ...
    def save(
        self, activity: StreamMainSegmentActivity
    ) -> StreamMainSegmentActivity: ...
    def find_by_session(self, session_id: str) -> StreamMainSegmentActivity | None: ...
    def command_result(self, command_id: str) -> StreamMainSegmentActivity | None: ...
    def save_command_result(
        self, command_id: str, activity: StreamMainSegmentActivity
    ) -> StreamMainSegmentActivity: ...


MainExecutor = Callable[[dict[str, object], str], Awaitable[PluginActivityResult]]
EventPublisher = Callable[[str, dict[str, object], str], None]
TopicSelector = Callable[[str, str, tuple[str, ...]], str]


class StreamMainSegmentUsecase:
    """Opening完了後、最初のmain Segmentを一度だけ実行する。"""

    def __init__(
        self,
        *,
        sessions: StreamSessionRepository,
        activities: MainSegmentRepository,
        run_of_show: RunOfShowRepository,
        executor: MainExecutor,
        event_publisher: EventPublisher | None = None,
        topic_selector: TopicSelector | None = None,
        require_main_segment: bool = True,
        lifecycle_gate: StreamLifecycleGate | None = None,
    ) -> None:
        self._sessions = sessions
        self._activities = activities
        self._run_of_show = run_of_show
        self._executor = executor
        self._publish = event_publisher or (lambda _event, _data, _trace: None)
        self._topic_selector = topic_selector
        self._require_main = require_main_segment
        self._verified_states: dict[str, dict[str, str]] = {}
        self._recent_topics: list[str] = []
        self._gate = lifecycle_gate

    def status(self, session_id: str) -> StreamMainSegmentActivity | None:
        return self._activities.find_by_session(session_id)

    async def start(
        self, opening: StreamOpeningActivity, verified_state: dict[str, str]
    ) -> StreamMainSegmentActivity:
        session = self._sessions.get(opening.session_id)
        if session is None:
            raise StreamMainSegmentRejected("main_segment.session.not_found")
        if session.status != StreamSessionStatus.LIVE:
            raise StreamMainSegmentRejected("main_segment.session.not_live")
        if opening.status != StreamOpeningStatus.COMPLETED:
            raise StreamMainSegmentRejected("main_segment.opening.not_completed")
        if not self._is_verified(verified_state):
            raise StreamMainSegmentRejected("main_segment.stream_state.unverified")
        if self._gate is not None:
            self._gate.update_external_state(session.session_id, verified_state)
            decision = self._gate.evaluate(
                LifecycleOperation.START_MAIN_SEGMENT,
                session.session_id,
                trace_id=opening.trace_id,
            )
            if not decision.allowed:
                raise StreamMainSegmentRejected(
                    decision.reason_code or "lifecycle.operation_not_allowed"
                )
        if self._activities.find_by_session(session.session_id) is not None:
            raise StreamMainSegmentRejected("main_segment.duplicate")
        if not session.run_of_show_id:
            return self._missing(
                session.session_id, opening.trace_id, "main_segment.run_of_show.missing"
            )
        try:
            segment = self._run_of_show.get_first_main_segment(session.run_of_show_id)
        except Exception as error:
            return self._missing(
                session.session_id,
                opening.trace_id,
                f"main_segment.run_of_show.{type(error).__name__}",
            )
        if segment is None:
            code = (
                "main_segment.required_missing"
                if self._require_main
                else "main_segment.optional_missing"
            )
            return self._missing(
                session.session_id, opening.trace_id, code, retryable=self._require_main
            )
        activity = StreamMainSegmentActivity(
            session.session_id,
            opening.trace_id,
            segment.segment_id,
            segment.order,
            segment.title,
        )
        self._activities.create(activity)
        self._sessions.save(
            session.attach_main_segment(segment.segment_id, activity.activity_id)
        )
        self._verified_states[session.session_id] = dict(verified_state)
        return await self._execute(activity, asdict(segment), session.title, opening)

    async def retry(
        self, command: RetryMainSegmentCommand
    ) -> StreamMainSegmentActivity:
        duplicate = self._activities.command_result(command.command_id)
        if duplicate is not None:
            return duplicate
        activity = self._activities.find_by_session(command.session_id)
        if activity is None or activity.activity_id != command.activity_id:
            raise StreamMainSegmentRejected("main_segment.not_found")
        if activity.version != command.expected_activity_version:
            raise StreamMainSegmentRejected("main_segment.version_mismatch")
        if activity.status != StreamMainSegmentStatus.FAILED:
            raise StreamMainSegmentRejected(
                f"main_segment.retry.{activity.status.value}"
            )
        session = self._sessions.get(command.session_id)
        if session is None or session.status != StreamSessionStatus.LIVE:
            raise StreamMainSegmentRejected("main_segment.session.not_live")
        state = self._verified_states.get(command.session_id)
        if state is None or not self._is_verified(state):
            raise StreamMainSegmentRejected("main_segment.stream_state.unverified")
        if not session.run_of_show_id:
            raise StreamMainSegmentRejected("main_segment.run_of_show.missing")
        segment = self._run_of_show.get_first_main_segment(session.run_of_show_id)
        if segment is None:
            raise StreamMainSegmentRejected("main_segment.required_missing")
        opening_summary = StreamOpeningActivity(
            session.session_id,
            activity.trace_id,
            session.opening_activity_id,
            status=StreamOpeningStatus.COMPLETED,
        )
        result = await self._execute(
            activity, asdict(segment), session.title, opening_summary
        )
        return self._activities.save_command_result(command.command_id, result)

    async def _execute(
        self,
        activity: StreamMainSegmentActivity,
        segment: dict[str, object],
        stream_title: str,
        opening: StreamOpeningActivity,
    ) -> StreamMainSegmentActivity:
        activity = self._activities.save(
            activity.transition(StreamMainSegmentStatus.RUNNING)
        )
        self._publish(
            "stream_main_segment.started", self._data(activity), activity.trace_id
        )
        topic = str(segment.get("topic") or "").strip()
        if not topic:
            if self._topic_selector is None:
                return self._fail(
                    activity, "main_segment.topic.unavailable", retryable=True
                )
            topic = self._topic_selector(
                str(segment.get("intent") or segment.get("title") or ""),
                stream_title,
                tuple(self._recent_topics),
            )
        activity = self._activities.save(
            activity.transition(StreamMainSegmentStatus.WAITING_FOR_OUTPUT, topic=topic)
        )
        self._publish(
            "stream_main_segment.topic_selected",
            {**self._data(activity), "topic": topic},
            activity.trace_id,
        )
        self._publish(
            "stream_main_segment.generation_started",
            self._data(activity),
            activity.trace_id,
        )
        payload: dict[str, object] = {
            "session_id": activity.session_id,
            "activity_type": "stream_main_segment",
            "plugin_id": "youtube_streaming",
            "stream_title": stream_title,
            "main_segment": segment,
            "segment_intent": segment.get("intent"),
            "current_topic": topic,
            "verified_stream_state": self._verified_states[activity.session_id],
            "opening_summary": opening.result or {"status": opening.status.value},
            "recent_topics": tuple(self._recent_topics),
        }
        try:
            self._publish(
                "stream_main_segment.output_started",
                self._data(activity),
                activity.trace_id,
            )
            self._publish(
                "stream_main_segment.speech_started",
                self._data(activity),
                activity.trace_id,
            )
            turn = await self._executor(payload, activity.trace_id)
        except Exception as error:
            return self._fail(
                activity, f"main_segment.output.{type(error).__name__}", retryable=True
            )
        speak = next(
            (
                item
                for item in (
                    turn.output_result.action_results if turn.output_result else ()
                )
                if item.action_type == SPEAK_ACTION_TYPE
            ),
            None,
        )
        result: dict[str, object] = {
            "activity_turn_id": turn.activity_turn_id,
            "generation_id": (
                turn.character_result.result_id if turn.character_result else None
            ),
            "action_id": speak.action_id if speak else None,
            "final_status": turn.final_status,
        }
        if speak is None or speak.status != "completed":
            return self._fail(
                activity,
                turn.failure_stage or "main_segment.speech.failed",
                result=result,
                retryable=True,
            )
        activity = self._activities.save(
            activity.transition(StreamMainSegmentStatus.COMPLETED, result=result)
        )
        self._recent_topics.append(topic)
        self._publish(
            "stream_main_segment.completed", self._data(activity), activity.trace_id
        )
        return activity

    def _missing(
        self, session_id: str, trace_id: str, code: str, *, retryable: bool = False
    ) -> StreamMainSegmentActivity:
        activity = StreamMainSegmentActivity(session_id, trace_id, None, None)
        self._activities.create(activity)
        return self._fail(
            activity.transition(StreamMainSegmentStatus.RUNNING),
            code,
            retryable=retryable,
        )

    def _fail(
        self,
        activity: StreamMainSegmentActivity,
        code: str,
        *,
        result: dict[str, object] | None = None,
        retryable: bool = False,
    ) -> StreamMainSegmentActivity:
        current = self._activities.find_by_session(activity.session_id)
        running = activity if current == activity else self._activities.save(activity)
        failed = self._activities.save(
            running.transition(
                StreamMainSegmentStatus.FAILED,
                failure_code=code,
                result=result,
                retryable=retryable,
            )
        )
        self._publish("stream_main_segment.failed", self._data(failed), failed.trace_id)
        return failed

    @staticmethod
    def _is_verified(state: dict[str, str]) -> bool:
        return state == {
            "obs_output": "active",
            "youtube_stream": "active",
            "youtube_broadcast": "live",
            "stream_session": "live",
        }

    @staticmethod
    def _data(activity: StreamMainSegmentActivity) -> dict[str, object]:
        return {
            "session_id": activity.session_id,
            "activity_id": activity.activity_id,
            "segment_id": activity.segment_id,
            "segment_index": activity.segment_index,
            "segment_title": activity.segment_title,
            "topic": activity.topic,
            "status": activity.status.value,
            "attempt": activity.attempt,
            "failure_code": activity.failure_code,
            "retryable": activity.retryable,
            "manual_intervention_required": activity.manual_intervention_required,
        }
