from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.shared.testing import STREAMING_DEMO_SPEECH


def create_manual_check_log(
    runtime_mode: str, enabled: bool, directory: Path = Path("logs/manual_checks")
) -> StreamingDemoManualCheckLog | None:
    if runtime_mode != "streaming_demo" or not enabled:
        return None
    return StreamingDemoManualCheckLog(directory)


class StreamingDemoManualCheckLog:
    """Flush-on-write, allow-list-only evidence log for local demo runs."""

    EVENT_MAP = {
        "stream_preparation.started": ("stream.session", "session_preparing"),
        "stream_preparation.ready": ("stream.session", "session_ready"),
        "stream_start.approved": ("stream.session", "session_approved"),
        "stream_start.started": ("stream.session", "session_starting"),
        "stream_start.completed": ("stream.session", "session_live"),
        "stream_start.obs_active": ("stream.external", "obs_state_changed"),
        "stream_start.youtube_stream_active": (
            "stream.external",
            "youtube_stream_state_changed",
        ),
        "stream_start.broadcast_live": (
            "stream.external",
            "youtube_broadcast_state_changed",
        ),
        "stream_start.failed": ("error", "session_failed"),
        "stream_opening.started": ("stream.activity", "opening_started"),
        "stream_opening.completed": ("stream.activity", "opening_completed"),
        "stream_main_segment.started": ("stream.activity", "main_started"),
        "stream_main_segment.completed": ("stream.activity", "main_completed"),
        "stream_demo.comment_queued": ("stream.comment", "comment_received"),
        "stream_comments.message_deduplicated": (
            "stream.comment",
            "comment_deduplicated",
        ),
        "stream_comments.moderation_decided": ("stream.comment", "moderation_decided"),
        "stream_comments.candidate_created": ("stream.comment", "candidate_created"),
        "stream_comments.ranking_completed": ("stream.comment", "ranking_completed"),
        "stream_comments.target_selected": ("stream.comment", "selection_reserved"),
        "stream_comments.reservation_consumed": (
            "stream.comment",
            "selection_consumed",
        ),
        "stream_comments.reservation_released": (
            "stream.comment",
            "selection_released",
        ),
        "stream_comments.response_started": (
            "stream.activity",
            "comment_response_started",
        ),
        "stream_comments.response_completed": (
            "stream.activity",
            "comment_response_completed",
        ),
        "stream_comments.response_failed": ("error", "comment_response_failed"),
        "stream_closing.started": ("stream.activity", "closing_started"),
        "stream_closing.completed": ("stream.activity", "closing_completed"),
        "stream_end.approved": ("stream.end", "normal_end_requested"),
        "stream_end.stopping": ("stream.session", "session_ending"),
        "stream_end.broadcast_complete": ("stream.external", "youtube_stop_completed"),
        "stream_end.obs_idle": ("stream.external", "obs_stop_completed"),
        "stream_end.completed": ("stream.session", "session_completed"),
        "stream_emergency_stop.requested": ("stream.end", "emergency_stop_requested"),
        "stream_emergency_stop.completed": (
            "stream.session",
            "session_emergency_stopped",
        ),
        "stream_emergency_stop.broadcast_complete": (
            "stream.external",
            "youtube_stop_completed",
        ),
        "stream_emergency_stop.obs_idle": ("stream.external", "obs_stop_completed"),
        "stream_end.failed": ("error", "error"),
        "stream_emergency_stop.failed": ("error", "error"),
        "stream_comments.polling_stopping": ("stream.comment", "poller_stopping"),
        "stream_comments.polling_stopped": ("stream.comment", "poller_stopped"),
    }
    SAFE_FIELDS = {
        "session_id",
        "activity_id",
        "candidate_id",
        "selection_id",
        "status",
        "reason_code",
        "message_id_hash",
        "message_types",
        "count",
        "priority_hint",
        "failure_code",
        "retryable",
        "manual_intervention_required",
        "author_role",
        "message_type",
        "text_length",
        "content_hash",
        "is_paid",
        "deduplicated",
        "obs_status",
        "youtube_stream_status",
        "youtube_broadcast_status",
        "preset",
        "test_case_id",
        "submitted_text",
        "normalized_text",
        "response_text",
        "text_truncated",
        "original_text_length",
        "moderation_status",
        "moderation_reason",
        "ranking_score",
        "selected",
        "responded",
        "spoken_text",
        "expression",
        "activity_type",
        "contains_demo_input_text",
        "real_user_comments_logged",
        "opening_count",
        "main_count",
        "comment_received_count",
        "comment_response_count",
        "moderation_block_count",
        "closing_count",
        "error_count",
        "submitted_test_count",
        "allowed_count",
        "blocked_count",
        "reviewed_count",
        "deduplicated_count",
        "selected_count",
        "response_completed_count",
        "response_failed_count",
        "test_case_ids",
    }
    _SECRET_ASSIGNMENT = re.compile(
        r"(?i)(\b(?:authorization|access_token|refresh_token|admin_token|stream_key|"
        r"client_secret|api_key|password)\b\s*[=:]\s*)([^\s,;]+)"
    )

    def __init__(self, directory: Path = Path("logs/manual_checks")) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        self.path = directory / f"streaming_demo_{now:%Y%m%d_%H%M%S}.jsonl"
        self._file = self.path.open("x", encoding="utf-8")
        self._counts: Counter[str] = Counter()
        self._last_session_status: str | None = None
        self._demo_cases: dict[str, dict[str, Any]] = {}
        self._case_by_message_hash: dict[str, str] = {}
        self._case_by_candidate: dict[str, str] = {}
        self._case_by_selection: dict[str, str] = {}
        self._summary_written = False
        self.last_write_at: str | None = None
        self.record("core", "runtime", "demo_mode_started")
        self.record(
            "core",
            "manual_check",
            "manual_check_log_privacy_notice",
            details={
                "status": "demo_text_logging_enabled",
                "reason_code": "local_streaming_demo_only",
                "contains_demo_input_text": True,
                "real_user_comments_logged": False,
            },
        )

    @property
    def count(self) -> int:
        return sum(self._counts.values())

    def record_broker_event(
        self, event_type: str, data: dict[str, Any], trace_id: str
    ) -> None:
        mapped = self.EVENT_MAP.get(event_type)
        if mapped is None:
            return
        category, event = mapped
        case_id = self._resolve_case(event_type, data)
        case = self._demo_cases.get(case_id or "")
        enriched = dict(data)
        if case_id is not None:
            enriched["test_case_id"] = case_id
        if event == "comment_received" and case is not None:
            enriched["normalized_text"] = case["submitted_text"]
            enriched["text_truncated"] = case["text_truncated"]
        if event == "comment_deduplicated" and case is not None:
            enriched["deduplicated"] = True
            case["deduplicated"] = True
        status = str(data.get("status")) if data.get("status") is not None else None
        if event == "moderation_decided":
            decision = str(data.get("status") or "review")
            event = {
                "allow": "moderation_allowed",
                "block": "moderation_blocked",
                "review": "moderation_reviewed",
            }.get(decision, "moderation_reviewed")
        if case is not None and event.startswith("moderation_"):
            moderation_status = str(data.get("status") or "review")
            case["moderation_status"] = moderation_status
            enriched["moderation_status"] = moderation_status
            reasons = data.get("reason_codes")
            if isinstance(reasons, (list, tuple)):
                enriched["moderation_reason"] = ",".join(
                    str(reason) for reason in reasons
                )
                case["moderation_reason"] = enriched["moderation_reason"]
        if case is not None and event == "ranking_completed":
            for item in data.get("top", []):
                if (
                    isinstance(item, dict)
                    and str(item.get("candidate_id")) in self._case_by_candidate
                ):
                    enriched["ranking_score"] = float(item.get("total_score") or 0.0)
                    case["ranking_score"] = enriched["ranking_score"]
                    break
        if case is not None and event == "selection_reserved":
            case["selected"] = True
            enriched["selected"] = True
            enriched["ranking_score"] = float(data.get("selected_score") or 0.0)
            case["ranking_score"] = enriched["ranking_score"]
        if case is not None and event == "comment_response_completed":
            case["responded"] = True
            enriched["response_text"] = STREAMING_DEMO_SPEECH["stream_comment_response"]
            case["response_text"] = enriched["response_text"]
        activity_types = {
            "opening_completed": "stream_opening_greeting",
            "main_completed": "stream_main_segment",
            "closing_completed": "stream_closing_greeting",
        }
        activity_type = activity_types.get(event)
        if activity_type is not None:
            enriched.update(
                {
                    "spoken_text": STREAMING_DEMO_SPEECH[activity_type],
                    "expression": (
                        "soft_smile"
                        if activity_type == "stream_closing_greeting"
                        else "smile"
                    ),
                    "activity_type": activity_type,
                }
            )
        self.record(
            "core",
            category,
            event,
            trace_id=trace_id,
            status=status,
            details=enriched,
            allow_demo_text=event
            in {
                "comment_received",
                "comment_response_completed",
                "opening_completed",
                "main_completed",
                "closing_completed",
            },
        )
        if event.endswith("_completed") and category == "stream.activity":
            activity_id = data.get("activity_id")
            for output_event in (
                "subtitle_emitted",
                "expression_emitted",
                "speak_emitted",
                "tts_completed",
                "playback_completed",
            ):
                self.record(
                    "core",
                    "stream.output",
                    output_event,
                    activity_id=str(activity_id) if activity_id else None,
                    trace_id=trace_id,
                )
        if event in {
            "session_completed",
            "session_emergency_stopped",
            "session_failed",
        }:
            self._last_session_status = event.removeprefix("session_")
            self.write_summary()

    def record_demo_submission(
        self,
        *,
        test_case_id: str,
        message_id_hash: str,
        text: str,
        preset: str,
        author_role: str,
        message_type: str,
        is_paid: bool,
        session_id: str,
        trace_id: str,
    ) -> None:
        sanitized_text = self._SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", text)
        limited = sanitized_text[:1000]
        case = {
            "test_case_id": test_case_id,
            "submitted_text": limited,
            "text_truncated": len(sanitized_text) > len(limited),
            "preset": preset,
            "text_length": len(limited),
            "original_text_length": len(text),
            "author_role": author_role,
            "message_type": message_type,
            "is_paid": is_paid,
            "moderation_status": None,
            "moderation_reason": None,
            "ranking_score": None,
            "selected": False,
            "responded": False,
            "deduplicated": False,
            "response_text": None,
        }
        self._demo_cases[test_case_id] = case
        self._case_by_message_hash[message_id_hash] = test_case_id
        self.record(
            "ui",
            "manual_check",
            "demo_comment_submitted",
            session_id=session_id,
            trace_id=trace_id,
            details=case,
            allow_demo_text=True,
        )

    def _resolve_case(self, event_type: str, data: dict[str, Any]) -> str | None:
        explicit = data.get("test_case_id")
        case_id = str(explicit) if explicit else None
        message_hash = data.get("message_id_hash")
        candidate_id = data.get("candidate_id")
        selection_id = data.get("selection_id")
        if case_id is None and message_hash:
            case_id = self._case_by_message_hash.get(str(message_hash))
        if case_id is None and candidate_id:
            case_id = self._case_by_candidate.get(str(candidate_id))
        if case_id is None and selection_id:
            case_id = self._case_by_selection.get(str(selection_id))
        if case_id is None and event_type == "stream_comments.ranking_completed":
            for item in data.get("top", []):
                if isinstance(item, dict):
                    case_id = self._case_by_candidate.get(str(item.get("candidate_id")))
                    if case_id:
                        break
        if case_id and candidate_id:
            self._case_by_candidate[str(candidate_id)] = case_id
        if case_id and selection_id:
            self._case_by_selection[str(selection_id)] = case_id
        return case_id

    def record_ui(self, event: str, details: dict[str, Any] | None = None) -> None:
        self.record("ui", "ui.operation", event, details=details or {})

    def record(
        self,
        source: str,
        category: str,
        event: str,
        *,
        session_id: str | None = None,
        activity_id: str | None = None,
        trace_id: str | None = None,
        status: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
        allow_demo_text: bool = False,
    ) -> None:
        text_fields = {"submitted_text", "normalized_text", "response_text"}
        safe = {
            key: value
            for key, value in (details or {}).items()
            if key in self.SAFE_FIELDS
            and (allow_demo_text or key not in text_fields)
            and isinstance(value, (str, int, float, bool, list, type(None)))
        }
        payload = {
            "timestamp": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(
                timespec="milliseconds"
            ),
            "source": source,
            "category": category,
            "event": event,
            "session_id": session_id or safe.pop("session_id", None),
            "activity_id": activity_id or safe.pop("activity_id", None),
            "trace_id": trace_id,
            "candidate_id": safe.pop("candidate_id", None),
            "selection_id": safe.pop("selection_id", None),
            "status": status,
            "reason": reason or safe.pop("reason_code", None),
            "details": safe,
        }
        self._file.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        self._file.flush()
        self.last_write_at = str(payload["timestamp"])
        self._counts[event] += 1

    def write_summary(self) -> None:
        if self._summary_written:
            return
        self._summary_written = True
        self.record(
            "core",
            "manual_check",
            "manual_check_summary",
            status=self._last_session_status,
            details={
                "opening_count": self._counts["opening_completed"],
                "main_count": self._counts["main_completed"],
                "comment_received_count": self._counts["comment_received"],
                "comment_response_count": self._counts["comment_response_completed"],
                "moderation_block_count": self._counts["moderation_blocked"],
                "closing_count": self._counts["closing_completed"],
                "error_count": sum(
                    count for event, count in self._counts.items() if "failed" in event
                ),
                "submitted_test_count": len(self._demo_cases),
                "allowed_count": self._counts["moderation_allowed"],
                "blocked_count": self._counts["moderation_blocked"],
                "reviewed_count": self._counts["moderation_reviewed"],
                "deduplicated_count": self._counts["comment_deduplicated"],
                "selected_count": self._counts["selection_reserved"],
                "response_completed_count": self._counts["comment_response_completed"],
                "response_failed_count": self._counts["comment_response_failed"],
                "test_case_ids": list(self._demo_cases),
                "test_case_count": len(self._demo_cases),
                "responded_test_case_count": sum(
                    bool(case["responded"]) for case in self._demo_cases.values()
                ),
            },
        )

    def close(self) -> None:
        if self._file.closed:
            return
        self.write_summary()
        self.record("core", "manual_check", "manual_check_log_closed")
        self._file.close()
