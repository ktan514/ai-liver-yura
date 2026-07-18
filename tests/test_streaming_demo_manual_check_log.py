from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.admin_api import create_admin_api
from app.bootstrap import compose_streaming
from app.config.app_config import load_app_config
from app.plugins.youtube_streaming.adapters.manual_check_log import create_manual_check_log
from app.runtime.runtime_factory import create_stream_preparation_runtime


def records(logger: object) -> list[dict[str, Any]]:
    path = logger.path  # type: ignore[attr-defined]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_log_is_created_only_for_explicit_streaming_demo(tmp_path: Path) -> None:
    assert create_manual_check_log("streaming_demo", False) is None
    assert create_manual_check_log("console", True) is None
    logger = create_manual_check_log("streaming_demo", True, tmp_path)
    assert logger is not None and logger.path.exists()
    logger.close()


def test_events_are_correlated_sanitized_and_summarized(tmp_path: Path) -> None:
    logger = create_manual_check_log("streaming_demo", True, tmp_path)
    assert logger is not None
    logger.record_broker_event(
        "stream_opening.completed",
        {"session_id": "session", "activity_id": "opening", "status": "completed"},
        "trace",
    )
    logger.record_broker_event(
        "stream_comments.moderation_decided",
        {
            "session_id": "session",
            "candidate_id": "candidate",
            "selection_id": "selection",
            "status": "block",
            "comment": "連絡先は test@example.com / 090-1234-5678",
            "authorization": "Bearer secret-token",
            "raw_response": {"secret": True},
        },
        "trace",
    )
    logger.record_broker_event(
        "stream_end.completed", {"session_id": "session", "status": "completed"}, "trace"
    )
    logger.close()

    values = records(logger)
    serialized = json.dumps(values, ensure_ascii=False)
    assert "test@example.com" not in serialized
    assert "090-1234-5678" not in serialized
    assert "secret-token" not in serialized
    assert "raw_response" not in serialized
    opening = next(item for item in values if item["event"] == "opening_completed")
    assert opening["session_id"] == "session"
    assert opening["activity_id"] == "opening"
    assert opening["trace_id"] == "trace"
    assert any(item["event"] == "speak_emitted" for item in values)
    summary = next(item for item in values if item["event"] == "manual_check_summary")
    assert summary["status"] == "completed"
    assert summary["details"]["opening_count"] == 1
    assert summary["details"]["moderation_block_count"] == 1


def test_emergency_and_error_terminal_summaries_are_recorded(tmp_path: Path) -> None:
    emergency = create_manual_check_log("streaming_demo", True, tmp_path / "emergency")
    assert emergency is not None
    emergency.record_broker_event(
        "stream_emergency_stop.requested", {"session_id": "session"}, "trace"
    )
    emergency.record_broker_event(
        "stream_emergency_stop.completed",
        {"session_id": "session", "status": "emergency_stopped"},
        "trace",
    )
    emergency.close()
    emergency_values = records(emergency)
    assert any(item["event"] == "emergency_stop_requested" for item in emergency_values)
    assert any(
        item["event"] == "manual_check_summary" and item["status"] == "emergency_stopped"
        for item in emergency_values
    )

    failed = create_manual_check_log("streaming_demo", True, tmp_path / "failed")
    assert failed is not None
    failed.record_broker_event(
        "stream_end.failed",
        {
            "session_id": "session",
            "failure_code": "stream.end.failed",
            "manual_intervention_required": True,
        },
        "trace",
    )
    failed.record_broker_event(
        "stream_start.failed", {"session_id": "session", "status": "failed"}, "trace"
    )
    failed.close()
    failed_values = records(failed)
    assert any(item["event"] == "error" for item in failed_values)
    assert any(
        item["event"] == "manual_check_summary" and item["status"] == "failed"
        for item in failed_values
    )


def test_health_exposes_log_status_and_ui_endpoint_uses_same_writer(tmp_path: Path) -> None:
    logger = create_manual_check_log("streaming_demo", True, tmp_path)
    assert logger is not None
    runtime = create_stream_preparation_runtime(load_app_config())
    service = compose_streaming(
        runtime, demo_mode=True, manual_check_log=logger
    ).admin_api
    client = TestClient(create_admin_api(service))
    health = client.get("/api/v1/health").json()["manual_check_log"]
    assert health["enabled"] is True
    assert health["path"] == str(logger.path)
    response = client.post(
        "/api/v1/manual-check/ui-events",
        json={"event": "prepare_clicked", "details": {"authorization": "secret"}},
    )
    assert response.status_code == 202
    logger.close()
    values = records(logger)
    assert any(item["source"] == "ui" and item["event"] == "prepare_clicked" for item in values)
    assert "secret" not in json.dumps(values)


def test_demo_comment_text_and_processing_are_correlated_only_in_manual_log(
    tmp_path: Path,
) -> None:
    logger = create_manual_check_log("streaming_demo", True, tmp_path)
    assert logger is not None
    logger.record_demo_submission(
        test_case_id="case-1",
        message_id_hash="message-hash",
        text="海と山ならどっちが好き？",
        preset="通常コメント",
        author_role="viewer",
        message_type="textMessageEvent",
        is_paid=False,
        session_id="session",
        trace_id="trace",
    )
    logger.record_broker_event(
        "stream_demo.comment_queued",
        {
            "session_id": "session",
            "test_case_id": "case-1",
            "message_id_hash": "message-hash",
        },
        "trace",
    )
    logger.record_broker_event(
        "stream_comments.candidate_created",
        {
            "session_id": "session",
            "candidate_id": "candidate",
            "message_id_hash": "message-hash",
        },
        "trace",
    )
    logger.record_broker_event(
        "stream_comments.target_selected",
        {"session_id": "session", "candidate_id": "candidate", "selection_id": "selection"},
        "trace",
    )
    logger.record_broker_event(
        "stream_comments.response_completed",
        {"session_id": "session", "candidate_id": "candidate", "selection_id": "selection"},
        "trace",
    )
    logger.close()

    values = records(logger)
    correlated = [
        item
        for item in values
        if isinstance(item.get("details"), dict)
        and item["details"].get("test_case_id") == "case-1"
    ]
    assert {item["event"] for item in correlated} >= {
        "demo_comment_submitted",
        "comment_received",
        "candidate_created",
        "selection_reserved",
        "comment_response_completed",
    }
    received = next(item for item in values if item["event"] == "comment_received")
    assert received["details"]["normalized_text"] == "海と山ならどっちが好き？"
    response = next(item for item in values if item["event"] == "comment_response_completed")
    assert response["details"]["response_text"]
    notice = next(item for item in values if item["event"] == "manual_check_log_privacy_notice")
    assert notice["details"]["contains_demo_input_text"] is True
    assert notice["details"]["real_user_comments_logged"] is False
    submitted = next(item for item in values if item["event"] == "demo_comment_submitted")
    assert submitted["details"] | {
        "author_role": "viewer",
        "message_type": "textMessageEvent",
        "is_paid": False,
    } == submitted["details"]
    summary = next(item for item in values if item["event"] == "manual_check_summary")
    assert summary["details"]["submitted_test_count"] == 1
    assert summary["details"]["selected_count"] == 1
    assert summary["details"]["response_completed_count"] == 1


def test_demo_submission_masks_secret_assignments_but_keeps_pii_test_text(
    tmp_path: Path,
) -> None:
    logger = create_manual_check_log("streaming_demo", True, tmp_path)
    assert logger is not None
    logger.record_demo_submission(
        test_case_id="case-secret",
        message_id_hash="message-secret",
        text="連絡先 test@example.com api_key=super-secret password:letmein",
        preset="custom",
        author_role="viewer",
        message_type="textMessageEvent",
        is_paid=False,
        session_id="session",
        trace_id="trace",
    )
    logger.close()

    serialized = json.dumps(records(logger), ensure_ascii=False)
    assert "test@example.com" in serialized
    assert "super-secret" not in serialized
    assert "letmein" not in serialized
    assert serialized.count("[REDACTED]") == 2
