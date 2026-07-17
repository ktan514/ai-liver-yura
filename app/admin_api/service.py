from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.adapters.streaming import (
    InMemoryCommentCandidateRepository,
    InMemoryCommentModerationRepository,
    InMemoryCommentRankingRepository,
    InMemoryCommentResponseActivityRepository,
    InMemoryCommentResponseHistory,
    InMemoryCommentResponseHistoryRepository,
    InMemoryCommentSelectionRepository,
)
from app.admin_api.dto import broadcast, health_item, session_snapshot, timestamp
from app.admin_api.manual_check_log import StreamingDemoManualCheckLog
from app.domain.streaming import (
    ApproveNormalStreamEndCommand,
    ApproveStreamStartCommand,
    CommentRankingContext,
    EmergencyStopStreamCommand,
    RetryCommentResponseCommand,
    RetryMainSegmentCommand,
    RetryOpeningCommand,
    StreamEndResult,
    StreamMainSegmentActivity,
    StreamOpeningActivity,
    StreamPreparationCommand,
    StreamStartRejected,
    StreamStartResult,
    YouTubeBroadcastSummary,
)
from app.ports.youtube_live_chat import LiveChatMessageDto
from app.runtime.runtime_coordinator import RuntimeCoordinator
from app.runtime.runtime_factory import StreamPreparationRuntime
from app.usecases import (
    CommentModerationUsecase,
    CommentRankingUsecase,
    CommentResponseUsecase,
    EndStreamSessionUsecase,
    StreamLifecycleGate,
    StreamMainSegmentUsecase,
    StreamOpeningUsecase,
    YouTubeLiveChatPoller,
)


@dataclass(frozen=True, slots=True)
class AdminEvent:
    event_id: str
    event_type: str
    occurred_at: str
    trace_id: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "trace_id": self.trace_id,
            "data": self.data,
        }


class EventBroker:
    """Fan-out SSE broker with a bounded replay buffer for Last-Event-ID."""

    def __init__(self, replay_size: int = 256) -> None:
        self._history: deque[AdminEvent] = deque(maxlen=replay_size)
        self._clients: set[asyncio.Queue[AdminEvent]] = set()
        self._observers: list[Callable[[str, dict[str, Any], str], None]] = []

    def add_observer(self, observer: Callable[[str, dict[str, Any], str], None]) -> None:
        self._observers.append(observer)

    def publish(self, event_type: str, data: dict[str, Any], trace_id: str = "") -> AdminEvent:
        event = AdminEvent(
            event_id=str(uuid4()),
            event_type=event_type,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id or str(uuid4()),
            data=data,
        )
        self._history.append(event)
        for observer in tuple(self._observers):
            observer(event_type, data, event.trace_id)
        for queue in tuple(self._clients):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._clients.discard(queue)
        return event

    def subscribe(self, last_event_id: str | None = None) -> asyncio.Queue[AdminEvent]:
        queue: asyncio.Queue[AdminEvent] = asyncio.Queue(maxsize=128)
        replay = last_event_id is None
        for event in self._history:
            if replay:
                queue.put_nowait(event)
            elif event.event_id == last_event_id:
                replay = True
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AdminEvent]) -> None:
        self._clients.discard(queue)


class AdminApiService:
    def __init__(
        self,
        runtime: StreamPreparationRuntime,
        broker: EventBroker | None = None,
        *,
        demo_mode: bool = False,
        manual_check_log: StreamingDemoManualCheckLog | None = None,
    ) -> None:
        self.runtime = runtime
        self.broker = broker or EventBroker()
        self.demo_mode = demo_mode
        self.manual_check_log = manual_check_log
        if manual_check_log is not None:
            self.broker.add_observer(manual_check_log.record_broker_event)
        self._auth_task: asyncio.Task[None] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._start_commands: dict[str, str] = {}
        self._start_progress: dict[str, Any] | None = None
        self._opening_usecase: StreamOpeningUsecase | None = None
        self._main_segment_usecase: StreamMainSegmentUsecase | None = None
        self._end_usecase: EndStreamSessionUsecase | None = None
        self._lifecycle_gate: StreamLifecycleGate | None = None
        self._comment_poller: YouTubeLiveChatPoller | None = None
        self._coordinator: RuntimeCoordinator | None = None
        self._comment_moderation: CommentModerationUsecase | None = None
        self._comment_ranking: CommentRankingUsecase | None = None
        self._comment_response: CommentResponseUsecase | None = None
        runtime.publisher.subscribe(self._preparation_completed)
        runtime.start_usecase.set_event_publisher(self._publish_start_event)

    def manual_check_status(self) -> dict[str, Any]:
        logger = self.manual_check_log
        return {
            "enabled": logger is not None,
            "path": str(logger.path) if logger is not None else None,
            "write_count": logger.count if logger is not None else 0,
            "last_write_at": logger.last_write_at if logger is not None else None,
        }

    def record_ui_operation(self, payload: dict[str, Any]) -> None:
        logger = self.manual_check_log
        if logger is None:
            raise PermissionError("manual_check.disabled")
        allowed = {
            "reload_slots_clicked",
            "prepare_clicked",
            "start_clicked",
            "normal_end_clicked",
            "emergency_stop_clicked",
            "demo_comment_submitted",
            "tab_changed",
            "streaming_admin_connected",
            "streaming_admin_disconnected",
        }
        event = str(payload.get("event") or "")
        if event not in allowed:
            raise ValueError("manual_check.invalid_event")
        details = payload.get("details")
        logger.record_ui(event, details if isinstance(details, dict) else {})

    def enqueue_demo_comment(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.demo_mode:
            raise PermissionError("demo.disabled")
        session = self.runtime.usecase.find_active_session()
        if session is None or session.status.value != "live" or self._comment_poller is None:
            raise RuntimeError("demo.live_session_required")
        enqueue = getattr(self.runtime.live_chat, "enqueue", None)
        if not callable(enqueue):
            raise RuntimeError("demo.live_chat_not_fake")
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        role = str(payload.get("author_role") or "viewer")
        kind = str(payload.get("message_type") or "textMessageEvent")
        is_paid = bool(payload.get("is_paid"))
        if is_paid:
            kind = "superChatEvent"
        message_id = str(payload.get("message_id") or uuid4())
        test_case_id = str(payload.get("test_case_id") or uuid4())
        message_id_hash = hashlib.sha256(message_id.encode()).hexdigest()[:12]
        author = {
            "channelId": f"demo-{role}",
            "displayName": str(payload.get("author_display_name") or "Demo Viewer")[:40],
            "isChatOwner": role == "owner",
            "isChatModerator": role == "moderator",
            "isChatSponsor": role == "member",
        }
        snippet: dict[str, Any] = {
            "type": kind,
            "publishedAt": datetime.now(timezone.utc).isoformat(),
            "displayMessage": text,
        }
        if is_paid:
            snippet["superChatDetails"] = {"amountMicros": "1000000", "currency": "JPY"}
        enqueue(LiveChatMessageDto(message_id, kind, snippet, author))
        if self.manual_check_log is not None:
            self.manual_check_log.record_demo_submission(
                test_case_id=test_case_id,
                message_id_hash=message_id_hash,
                text=text,
                preset=str(payload.get("preset") or "custom"),
                author_role=role,
                message_type=kind,
                is_paid=is_paid,
                session_id=session.session_id,
                trace_id=session.trace_id,
            )
        self.broker.publish(
            "stream_demo.comment_queued",
            {
                "session_id": session.session_id,
                "message_type": kind,
                "author_role": role,
                "text_length": len(text),
                "content_hash": hashlib.sha256(text.encode()).hexdigest()[:12],
                "message_id_hash": message_id_hash,
                "test_case_id": test_case_id,
                "is_paid": is_paid,
            },
            session.trace_id,
        )
        return {
            "accepted": True,
            "message_id": message_id,
            "test_case_id": test_case_id,
            "session_id": session.session_id,
        }

    def configure_opening(self, coordinator: RuntimeCoordinator) -> None:
        self._coordinator = coordinator

        def publish(event_type: str, data: dict[str, object], trace_id: str) -> None:
            self.broker.publish(event_type, data, trace_id)

        self._lifecycle_gate = StreamLifecycleGate(
            sessions=self.runtime.sessions,
            openings=self.runtime.openings,
            main_segments=self.runtime.main_segments,
            publisher=publish,
        )
        coordinator.configure_stream_lifecycle_gate(self._lifecycle_gate)
        ranking_settings = self.runtime.config.streaming.comment_ranking
        self._comment_ranking = CommentRankingUsecase(
            gate=self._lifecycle_gate,
            candidates=InMemoryCommentCandidateRepository(ranking_settings.max_pool_size),
            rankings=InMemoryCommentRankingRepository(),
            selections=InMemoryCommentSelectionRepository(),
            history=InMemoryCommentResponseHistoryRepository(ranking_settings.history_size),
            settings=ranking_settings,
            publisher=publish,
        )
        self._comment_response = CommentResponseUsecase(
            gate=self._lifecycle_gate,
            activities=InMemoryCommentResponseActivityRepository(),
            selections=self._comment_ranking,
            history=InMemoryCommentResponseHistory(),
            executor=coordinator.execute_stream_comment_response,
            settings=self.runtime.config.streaming.comment_response,
            publisher=publish,
        )

        def rank_candidate(candidate: Any, trace_id: str) -> None:
            ranker = self._comment_ranking
            if ranker is None:
                return
            main = self.runtime.main_segments.find_by_session(candidate.session_id)
            context = CommentRankingContext(
                current_segment="main",
                current_topic=str(getattr(main, "topic", "") or ""),
            )

            async def select_and_respond() -> None:
                target = await ranker.add_and_select(candidate, context, trace_id)
                responder = self._comment_response
                if target is not None and responder is not None:
                    try:
                        await responder.start(target.session_id, target.selection_id, trace_id)
                    except Exception as error:
                        publish(
                            "stream_comments.response_failed",
                            {
                                "session_id": target.session_id,
                                "selection_id": target.selection_id,
                                "failure_code": getattr(
                                    error, "code", "comment_response.start_failed"
                                ),
                            },
                            trace_id,
                        )

            asyncio.create_task(select_and_respond())

        self._comment_moderation = CommentModerationUsecase(
            gate=self._lifecycle_gate,
            repository=InMemoryCommentModerationRepository(),
            settings=self.runtime.config.streaming.moderation,
            publisher=publish,
            candidate_sink=rank_candidate,
        )
        coordinator.configure_comment_moderation(self._comment_moderation.evaluate_event)
        self._main_segment_usecase = StreamMainSegmentUsecase(
            sessions=self.runtime.sessions,
            activities=self.runtime.main_segments,
            run_of_show=self.runtime.run_of_show,
            executor=coordinator.execute_stream_main_segment,
            event_publisher=publish,
            lifecycle_gate=self._lifecycle_gate,
        )
        self._opening_usecase = StreamOpeningUsecase(
            sessions=self.runtime.sessions,
            openings=self.runtime.openings,
            run_of_show=self.runtime.run_of_show,
            executor=coordinator.execute_stream_opening,
            event_publisher=publish,
            completed_handler=self._main_segment_usecase.start,
            lifecycle_gate=self._lifecycle_gate,
        )
        self._end_usecase = EndStreamSessionUsecase(
            sessions=self.runtime.sessions,
            main_segments=self.runtime.main_segments,
            run_of_show=self.runtime.run_of_show,
            obs=self.runtime.obs_control,
            youtube=self.runtime.youtube_control,
            closing_executor=coordinator.execute_stream_closing,
            output_canceler=coordinator.cancel_stream_outputs,
            event_publisher=publish,
            test_mode=(
                self.demo_mode
                or (
                    self.runtime.obs_control.adapter_type == "fake"
                    and self.runtime.youtube_control.adapter_type == "fake"
                )
            ),
            lifecycle_gate=self._lifecycle_gate,
        )

    def lifecycle_status(self) -> dict[str, Any] | None:
        if self._lifecycle_gate is None:
            return None
        session = self.runtime.usecase.find_active_session()
        return self._lifecycle_gate.snapshot(session.session_id) if session else None

    async def approve_end(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._end_usecase is None:
            raise RuntimeError("stream.end.not_configured")
        if self._comment_poller is not None:
            self.broker.publish(
                "stream_comments.polling_stopping",
                {"session_id": str(payload["session_id"]), "reason_code": "lifecycle.ending"},
            )
            self._comment_poller.stop("lifecycle.ending")
        result = await self._end_usecase.normal(
            ApproveNormalStreamEndCommand(
                command_id=str(payload["command_id"]),
                trace_id=str(uuid4()),
                session_id=str(payload["session_id"]),
                expected_state_version=int(payload["expected_state_version"]),
                approved_by=str(payload["approved_by"]),
            )
        )
        return self._end_result(result)

    async def emergency_stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._end_usecase is None:
            raise RuntimeError("stream.end.not_configured")
        if self._comment_poller is not None:
            self.broker.publish(
                "stream_comments.polling_stopping",
                {
                    "session_id": str(payload["session_id"]),
                    "reason_code": "lifecycle.emergency_stopping",
                },
            )
            self._comment_poller.stop("lifecycle.emergency_stopping")
        result = await self._end_usecase.emergency(
            EmergencyStopStreamCommand(
                command_id=str(payload["command_id"]),
                trace_id=str(uuid4()),
                session_id=str(payload["session_id"]),
                expected_state_version=int(payload["expected_state_version"]),
                requested_by=str(payload["requested_by"]),
                reason_code=str(payload["reason_code"]),
                operator_note=str(payload["operator_note"])
                if payload.get("operator_note")
                else None,
            )
        )
        return self._end_result(result)

    def end_status(self) -> dict[str, Any] | None:
        result = self._end_usecase.latest_result if self._end_usecase else None
        return self._end_result(result) if result else None

    @staticmethod
    def _end_result(result: StreamEndResult) -> dict[str, Any]:
        return {
            "session_id": result.session_id,
            "trace_id": result.trace_id,
            "command_id": result.command_id,
            "end_mode": result.end_mode,
            "successful": result.successful,
            "failed_step": result.failed_step,
            "closing_status": result.closing_status,
            "youtube_broadcast_status": result.youtube_broadcast_status,
            "youtube_stream_status": result.youtube_stream_status,
            "obs_output_status": result.obs_output_status,
            "failure_code": result.failure_code,
            "retryable": result.retryable,
            "manual_intervention_required": result.manual_intervention_required,
            "started_at": timestamp(result.started_at),
            "completed_at": timestamp(result.completed_at),
        }

    def main_segment_status(self) -> dict[str, Any] | None:
        if self._main_segment_usecase is None:
            return None
        session = self.runtime.usecase.find_active_session()
        activity = self._main_segment_usecase.status(session.session_id) if session else None
        return self._main_segment_result(activity) if activity else None

    async def retry_main_segment(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._main_segment_usecase is None:
            raise RuntimeError("main_segment.not_configured")
        activity = await self._main_segment_usecase.retry(
            RetryMainSegmentCommand(
                command_id=str(payload["command_id"]),
                session_id=str(payload["session_id"]),
                activity_id=str(payload["activity_id"]),
                expected_activity_version=int(payload["expected_activity_version"]),
            )
        )
        return self._main_segment_result(activity)

    @staticmethod
    def _main_segment_result(activity: StreamMainSegmentActivity) -> dict[str, Any]:
        return {
            "activity_id": activity.activity_id,
            "session_id": activity.session_id,
            "trace_id": activity.trace_id,
            "segment_id": activity.segment_id,
            "segment_index": activity.segment_index,
            "segment_title": activity.segment_title,
            "topic": activity.topic,
            "status": activity.status.value,
            "attempt": activity.attempt,
            "failure_code": activity.failure_code,
            "retryable": activity.retryable,
            "manual_intervention_required": activity.manual_intervention_required,
            "started_at": timestamp(activity.started_at),
            "completed_at": timestamp(activity.completed_at),
            "result": activity.result,
            "version": activity.version,
            "speaking": activity.status.value == "waiting_for_output",
        }

    def _publish_start_event(self, event_type: str, data: dict[str, object], trace_id: str) -> None:
        if self._start_progress is not None:
            self._start_progress.update(data)
            if "obs_status" in data:
                self._start_progress["obs_output_status"] = data["obs_status"]
            self._start_progress["trace_id"] = trace_id
            self._start_progress["status"] = event_type.removeprefix("stream_start.")
            self._start_progress["start_step"] = event_type
        self.broker.publish(event_type, data, trace_id)

    async def auth_status(self) -> dict[str, Any]:
        state = await self.runtime.usecase.get_youtube_authentication_state()
        return {
            "status": state.status.value,
            "failure_code": state.failure_reason,
            "retryable": state.status.value == "authentication_failed",
            "observed_at": timestamp(state.observed_at),
            "adapter_type": self.runtime.usecase.youtube_adapter_type,
        }

    def start_authentication(self, command_id: str) -> bool:
        if self._auth_task is not None and not self._auth_task.done():
            return False
        self._auth_task = asyncio.create_task(self._authenticate(command_id))
        return True

    async def _authenticate(self, command_id: str) -> None:
        self.broker.publish("youtube.auth.started", {"command_id": command_id})
        try:
            state = await self.runtime.usecase.authenticate_youtube()
            event_type = (
                "youtube.auth.completed"
                if state.status.value == "authenticated"
                else "youtube.auth.failed"
            )
            self.broker.publish(event_type, await self.auth_status())
        except Exception:
            self.broker.publish(
                "youtube.auth.failed",
                {"failure_code": "youtube.auth.failed", "retryable": True},
            )

    async def broadcasts(self) -> list[dict[str, Any]]:
        return [broadcast(item) for item in await self.runtime.usecase.list_broadcasts()]

    def run_of_shows(self) -> list[dict[str, Any]]:
        return [
            {
                "run_of_show_id": item.run_of_show_id,
                "title": item.title,
                "planned_duration_seconds": item.planned_duration_seconds,
                "segment_count": item.segment_count,
                "version": item.version,
            }
            for item in self.runtime.usecase.list_run_of_shows()
        ]

    def current_session(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        return (
            session_snapshot(
                session,
                self.runtime.usecase.youtube_adapter_type,
                self.runtime.usecase.obs_adapter_type,
            )
            if session is not None
            else None
        )

    async def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id")
        session = self.runtime.usecase.get_session(session_id) if session_id else None
        if session is None:
            session = self.runtime.usecase.find_active_session()
        trace_id = str(uuid4())
        if session is None:
            session = self.runtime.usecase.create_session(
                YouTubeBroadcastSummary(str(payload["broadcast_id"]), ""),
                trace_id=trace_id,
                run_of_show_id=str(payload["run_of_show_id"]),
            )
            if self.manual_check_log is not None:
                self.manual_check_log.record(
                    "core",
                    "stream.session",
                    "session_created",
                    session_id=session.session_id,
                    trace_id=trace_id,
                    status=session.status.value,
                )
        expected = payload.get("expected_state_version")
        command = StreamPreparationCommand(
            command_id=str(payload["command_id"]),
            trace_id=trace_id,
            session_id=session.session_id,
            selected_broadcast_id=str(payload["broadcast_id"]),
            requested_by="streaming_admin",
            expected_state_version=session.state_version if expected is None else int(expected),
            run_of_show_id=str(payload["run_of_show_id"]),
        )
        self.broker.publish(
            "stream_preparation.started",
            {"session_id": session.session_id, "command_id": command.command_id},
            trace_id,
        )
        result = await self.runtime.usecase.execute(command)
        current = self.runtime.usecase.get_session(result.session_id)
        if current is None:
            raise RuntimeError("stream.session.not_found")
        return session_snapshot(
            current,
            self.runtime.usecase.youtube_adapter_type,
            self.runtime.usecase.obs_adapter_type,
        )

    def capabilities(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [
            {"capability": item, "status": "available"}
            for item in sorted(self.runtime.capability_registry.list_available())
        ]
        lifecycle = self.lifecycle_status()
        if lifecycle is not None and isinstance(lifecycle.get("operations"), dict):
            operations = lifecycle["operations"]
            mapping = {
                "stream.opening.start": "start_opening",
                "stream.main_segment.start": "start_main_segment",
                "stream.comment.poll": "start_comment_polling",
                "stream.comment.moderate": "evaluate_comment",
                "stream.comment.create_candidate": "emit_comment_candidate",
                "stream.comment.rank": "select_comment_response_target",
                "stream.comment.select_response_target": "select_comment_response_target",
                "stream.comment.respond": "start_comment_response",
                "stream.comment.response.speak": "start_comment_response_speech",
                "stream.autonomous_talk.start": "start_autonomous_talk",
                "stream.closing.start": "start_closing",
                "stream.session.end.normal": "start_normal_end",
                "stream.session.stop.emergency": "start_emergency_stop",
            }
            items = [item for item in items if item["capability"] not in mapping]
            for capability, operation in mapping.items():
                decision = operations.get(operation, {})
                items.append(
                    {
                        "capability": capability,
                        "status": "available"
                        if isinstance(decision, dict) and decision.get("allowed")
                        else "blocked",
                        "reason_code": decision.get("reason_code")
                        if isinstance(decision, dict)
                        else "lifecycle.operation_not_allowed",
                    }
                )
        live_chat_real = self.runtime.live_chat.adapter_type == "google"
        items = [item for item in items if item["capability"] != "youtube.live_chat.read"]
        items.append(
            {
                "capability": "youtube.live_chat.read",
                "status": "available" if live_chat_real else "blocked",
                "reason_code": None if live_chat_real else "live_chat.test_adapter",
            }
        )
        ranking = self.ranking_status()
        if ranking is not None and int(ranking.get("pool_size", 0)) <= 0:
            for item in items:
                if item["capability"] in {
                    "stream.comment.rank",
                    "stream.comment.select_response_target",
                }:
                    item["status"] = "blocked"
                    item["reason_code"] = "comment_ranking.no_candidate"
        selection = self.current_comment_selection()
        has_reservation = selection is not None and selection.get("selection") is not None
        if not has_reservation:
            for item in items:
                if item["capability"] in {
                    "stream.comment.respond",
                    "stream.comment.response.speak",
                }:
                    item["status"] = "blocked"
                    item["reason_code"] = "comment_response.reservation_missing"
        return sorted(items, key=lambda item: str(item["capability"]))

    async def refresh_obs(self) -> dict[str, Any]:
        checks = await self.runtime.usecase.inspect_obs()
        payload = {
            "adapter_type": self.runtime.usecase.obs_adapter_type,
            "checks": [health_item(item) for item in checks],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.broker.publish("obs.status.updated", payload)
        return payload

    def approve_start(self, payload: dict[str, Any]) -> str:
        command_id = str(payload["command_id"])
        existing_trace = self._start_commands.get(command_id)
        if existing_trace is not None:
            return existing_trace
        if self._start_task is not None and not self._start_task.done():
            raise StreamStartRejected("stream.start.already_in_progress")
        command = ApproveStreamStartCommand(
            command_id=command_id,
            trace_id=str(uuid4()),
            session_id=str(payload["session_id"]),
            expected_state_version=int(payload["expected_state_version"]),
            approved_by=str(payload["approved_by"]),
        )
        self.runtime.start_usecase.validate(command)
        self._start_commands[command.command_id] = command.trace_id
        self._start_progress = {
            "session_id": command.session_id,
            "trace_id": command.trace_id,
            "command_id": command.command_id,
            "status": "accepted",
            "start_step": "approval_accepted",
            "obs_output_status": "unknown",
            "youtube_stream_status": "unknown",
            "youtube_broadcast_status": "unknown",
            "manual_intervention_required": False,
        }
        self._start_task = asyncio.create_task(self._run_start(command))
        return command.trace_id

    async def _run_start(self, command: ApproveStreamStartCommand) -> None:
        result = await self.runtime.start_usecase.execute(command)
        if result.successful:
            if self._lifecycle_gate is not None:
                self._lifecycle_gate.update_external_state(
                    command.session_id,
                    {
                        "obs_output": result.obs_status,
                        "youtube_stream": result.youtube_stream_status,
                        "youtube_broadcast": result.youtube_broadcast_status,
                        "stream_session": "live",
                    },
                )
            self._start_comment_poller(command.session_id, command.trace_id)
        opening = self._opening_usecase
        if opening is not None and result.successful:
            await opening.start(
                command.session_id,
                result,
                adapter_types=(
                    self.runtime.usecase.youtube_adapter_type,
                    self.runtime.usecase.obs_adapter_type,
                ),
                test_mode=(
                    self.demo_mode
                    or (
                        self.runtime.usecase.youtube_adapter_type == "fake"
                        and self.runtime.usecase.obs_adapter_type == "fake"
                    )
                ),
            )

    def _start_comment_poller(self, session_id: str, trace_id: str) -> None:
        session = self.runtime.sessions.get(session_id)
        gate = self._lifecycle_gate
        coordinator = self._coordinator
        if session is None or gate is None or coordinator is None or not session.live_chat_id:
            return

        def publish(event: str, data: dict[str, object], trace: str) -> None:
            self.broker.publish(event, data, trace)

        poller = YouTubeLiveChatPoller(
            session_id=session_id,
            trace_id=trace_id,
            broadcast_id=session.selected_broadcast_id,
            live_chat_id=session.live_chat_id,
            adapter=self.runtime.live_chat,
            gate=gate,
            event_sink=coordinator.publish_event,
            publisher=publish,
        )
        self._comment_poller = poller
        poller.start()

    def comments_status(self) -> dict[str, Any] | None:
        poller = self._comment_poller
        if poller is None:
            return None
        status = poller.status
        return {
            "session_id": status.session_id,
            "status": status.status,
            "last_success_at": timestamp(status.last_success_at),
            "last_message_at": timestamp(status.last_message_at),
            "received_count": status.received_count,
            "emitted_count": status.emitted_count,
            "duplicate_count": status.duplicate_count,
            "dropped_count": status.dropped_count,
            "current_interval_ms": status.current_interval_ms,
            "attempt": status.attempt,
            "failure_code": status.failure_code,
            "retryable": status.retryable,
            "lifecycle_stop_reason": status.lifecycle_stop_reason,
            "adapter_type": self.runtime.live_chat.adapter_type,
        }

    def moderation_status(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        moderation = self._comment_moderation
        if session is None or moderation is None:
            return None
        status = moderation.status(session.session_id)
        return {
            "session_id": status.session_id,
            "evaluated_count": status.evaluated_count,
            "allowed": status.allowed,
            "blocked": status.blocked,
            "review": status.review,
            "ignored": status.ignored,
            "spam_count": status.spam_count,
            "unsafe_count": status.unsafe_count,
            "personal_data_count": status.personal_data_count,
            "queue_depth": status.queue_depth,
            "last_evaluated_at": timestamp(status.last_evaluated_at),
            "failure_code": status.failure_code,
            "lifecycle_stop_reason": status.lifecycle_stop_reason,
        }

    def moderation_recent(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        moderation = self._comment_moderation
        if session is None or moderation is None:
            return None
        items = moderation.recent(session.session_id)
        return {
            "session_id": session.session_id,
            "items": [
                {
                    "decision_id": item.decision_id,
                    "message_id_hash": hashlib.sha256(item.message_id.encode()).hexdigest()[:12],
                    "status": item.status,
                    "reason_codes": item.reason_codes,
                    "severity": item.severity,
                    "confidence": item.confidence,
                    "evaluated_at": timestamp(item.evaluated_at),
                    "policy_version": item.policy_version,
                }
                for item in items
            ],
        }

    def ranking_status(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        ranker = self._comment_ranking
        if session is None or ranker is None:
            return None
        status = ranker.status(session.session_id)
        return {
            "session_id": status.session_id,
            "pool_size": status.pool_size,
            "ranked_count": status.ranked_count,
            "selected_count": status.selected_count,
            "expired_count": status.expired_count,
            "dropped_count": status.dropped_count,
            "last_ranking_at": timestamp(status.last_ranking_at),
            "failure_code": status.failure_code,
            "lifecycle_stop_reason": status.lifecycle_stop_reason,
        }

    def ranking_top(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        ranker = self._comment_ranking
        if session is None or ranker is None:
            return None
        return {
            "session_id": session.session_id,
            "items": [
                {
                    "candidate_id": item.candidate_id,
                    "rank": item.rank,
                    "total_score": item.total_score,
                    "eligible": item.eligible,
                    "exclusion_reasons": item.exclusion_reasons,
                    "feature_scores": {
                        "recency": item.feature_scores.recency_score,
                        "relevance": item.feature_scores.relevance_score,
                        "novelty": item.feature_scores.novelty_score,
                        "conversation_fit": item.feature_scores.conversation_fit_score,
                        "engagement": item.feature_scores.engagement_score,
                        "fairness": item.feature_scores.author_fairness_score,
                        "diversity": item.feature_scores.diversity_score,
                        "priority_adjustment": item.feature_scores.priority_adjustment,
                    },
                    "fallback_used": item.fallback_used,
                }
                for item in ranker.top(session.session_id)
            ],
        }

    def current_comment_selection(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        ranker = self._comment_ranking
        if session is None or ranker is None:
            return None
        item = ranker.current_selection(session.session_id)
        return {
            "session_id": session.session_id,
            "selection": None
            if item is None
            else {
                "selection_id": item.selection_id,
                "candidate_id": item.candidate_id,
                "sanitized_text": item.sanitized_text[:300],
                "selected_score": item.selected_score,
                "selected_rank": item.selected_rank,
                "selection_reason": item.selection_reason,
                "reservation_status": item.reservation_status,
                "expires_at": item.expires_at.isoformat(),
            },
        }

    def comment_response_status(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        responder = self._comment_response
        if session is None or responder is None:
            return None
        activity = responder.status(session.session_id)
        return {
            "session_id": session.session_id,
            "activity": None if activity is None else self._comment_response_result(activity),
        }

    def comment_response_recent(self) -> dict[str, Any] | None:
        session = self.runtime.usecase.find_active_session()
        responder = self._comment_response
        if session is None or responder is None:
            return None
        return {
            "session_id": session.session_id,
            "items": [
                {
                    "response_id": item.response_id,
                    "selection_id": item.selection_id,
                    "candidate_id": item.candidate_id,
                    "message_id_hash": hashlib.sha256(item.message_id.encode()).hexdigest()[:12],
                    "response_summary": item.response_summary[:80],
                    "outcome": item.outcome,
                    "completed_at": item.completed_at.isoformat(),
                }
                for item in responder.recent(session.session_id)
            ],
        }

    async def retry_comment_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._comment_response is None:
            raise RuntimeError("comment_response.not_configured")
        activity = await self._comment_response.retry(
            RetryCommentResponseCommand(
                command_id=str(payload["command_id"]),
                session_id=str(payload["session_id"]),
                activity_id=str(payload["activity_id"]),
                selection_id=str(payload["selection_id"]),
                expected_activity_version=int(payload["expected_activity_version"]),
            )
        )
        return self._comment_response_result(activity)

    @staticmethod
    def _comment_response_result(activity: Any) -> dict[str, Any]:
        return {
            "activity_id": activity.activity_id,
            "selection_id": activity.selection_id,
            "candidate_id": activity.candidate_id,
            "status": activity.status.value,
            "attempt": activity.attempt,
            "version": activity.version,
            "failure_code": activity.failure_code,
            "retryable": activity.retryable,
            "started_at": timestamp(activity.started_at),
            "completed_at": timestamp(activity.completed_at),
        }

    async def refresh_comments_status(self) -> dict[str, Any] | None:
        return self.comments_status()

    def opening_status(self) -> dict[str, Any] | None:
        if self._opening_usecase is None:
            return None
        session = self.runtime.usecase.find_active_session()
        if session is None:
            return None
        activity = self._opening_usecase.status(session.session_id)
        return self._opening_result(activity) if activity is not None else None

    async def retry_opening(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._opening_usecase is None:
            raise RuntimeError("opening.not_configured")
        activity = await self._opening_usecase.retry(
            RetryOpeningCommand(
                command_id=str(payload["command_id"]),
                session_id=str(payload["session_id"]),
                expected_activity_version=int(payload["expected_activity_version"]),
            )
        )
        return self._opening_result(activity)

    @staticmethod
    def _opening_result(activity: StreamOpeningActivity) -> dict[str, Any]:
        return {
            "activity_id": activity.activity_id,
            "session_id": activity.session_id,
            "trace_id": activity.trace_id,
            "status": activity.status.value,
            "segment_id": activity.segment_id,
            "attempt": activity.attempt,
            "failure_code": activity.failure_code,
            "manual_intervention_required": activity.manual_intervention_required,
            "started_at": timestamp(activity.started_at),
            "completed_at": timestamp(activity.completed_at),
            "activity_turn_id": activity.activity_turn_id,
            "result": activity.result,
            "version": activity.version,
            "speaking": activity.status.value == "waiting_for_output",
        }

    def start_status(self) -> dict[str, Any] | None:
        result = self.runtime.start_usecase.latest_result
        if result is not None:
            return self._start_result(result)
        return dict(self._start_progress) if self._start_progress is not None else None

    @staticmethod
    def _start_result(result: StreamStartResult) -> dict[str, Any]:
        return {
            "session_id": result.session_id,
            "trace_id": result.trace_id,
            "command_id": result.command_id,
            "status": result.status,
            "successful": result.successful,
            "failed_step": result.failed_step,
            "obs_output_status": result.obs_status,
            "youtube_stream_status": result.youtube_stream_status,
            "youtube_broadcast_status": result.youtube_broadcast_status,
            "failure_code": result.failure_code,
            "manual_intervention_required": result.manual_intervention_required,
            "started_at": timestamp(result.started_at),
            "completed_at": timestamp(result.completed_at),
            "duplicate": result.duplicate,
        }

    def _preparation_completed(self, result: Any) -> None:
        current = self.runtime.usecase.get_session(result.session_id)
        if current is None:
            return
        for check in current.health_snapshot:
            self.broker.publish(
                "stream_preparation.check_updated",
                {
                    "session_id": current.session_id,
                    "check_id": check.check_id,
                    "status": check.status.value,
                },
                result.trace_id,
            )
        event_type = "stream_preparation.completed" if result.ready else "stream_preparation.failed"
        self.broker.publish(
            event_type,
            session_snapshot(
                current,
                self.runtime.usecase.youtube_adapter_type,
                self.runtime.usecase.obs_adapter_type,
            ),
            result.trace_id,
        )
        if result.ready and not self.runtime.start_usecase.uses_test_adapter:
            providers = self.runtime.capability_registry.resolve_providers("stream.session.prepare")
            if providers:
                for capability in (
                    "stream.session.start",
                    "obs.stream.start",
                    "youtube.broadcast.transition_live",
                ):
                    self.runtime.capability_registry.register(providers[0], capability)
        self.broker.publish("capability.updated", {"items": self.capabilities()}, result.trace_id)
