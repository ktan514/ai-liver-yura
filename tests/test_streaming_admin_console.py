from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.admin_api.console import (
    AdapterCapabilities,
    DiagnosticRingBuffer,
    OperatorActionState,
    RuntimeLogSettings,
    freshness,
    operator_action_for,
)
from streaming_admin.ui.console_models import TimelineTableModel
from streaming_admin.ui.stream_preparation_view_model import (
    freshness_label,
    start_button_decision,
    update_mode_label,
)


def test_update_mode_and_freshness_labels() -> None:
    assert update_mode_label("automatic") == "自動"
    assert update_mode_label("manual") == "手動"
    assert update_mode_label("event_driven") == "イベント駆動"
    assert freshness_label("stale") == "情報が古い"


def test_freshness_uses_observation_time() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert freshness((now - timedelta(seconds=10)).isoformat(), 30, now=now) == "fresh"
    assert freshness((now - timedelta(seconds=31)).isoformat(), 30, now=now) == "stale"
    assert freshness(None, 30, now=now) == "unknown"


def test_adapter_capability_drives_operator_action_and_fake_never_requires_studio() -> None:
    fake = AdapterCapabilities.for_adapter("fake")
    assert operator_action_for(fake, phase="starting")["action_type"] == "none"

    manual = AdapterCapabilities(
        can_start_broadcast=False,
        can_stop_broadcast=False,
        can_open_studio=True,
        can_check_status=True,
        requires_operator_confirmation=True,
        studio_url="https://studio.youtube.com/",
    )
    start = operator_action_for(manual, phase="starting")
    assert start["action_type"] == "youtube_start_required"
    assert start["status"] == "waiting"
    assert start["can_confirm"] is True
    assert operator_action_for(manual, phase="ending")["action_type"] == "youtube_stop_required"


def test_operator_action_state_transitions_are_explicit() -> None:
    waiting = OperatorActionState("youtube_start_required", "waiting")
    acknowledged = waiting.transition("acknowledged")
    assert acknowledged.status == "acknowledged"
    assert acknowledged.transition("completed").status == "completed"


def test_diagnostic_ring_buffer_is_bounded_and_resizable() -> None:
    buffer = DiagnosticRingBuffer(2)
    buffer.append({"event_id": "1"})
    buffer.append({"event_id": "2"})
    buffer.append({"event_id": "3"})
    assert [item["event_id"] for item in buffer.snapshot()] == ["2", "3"]
    buffer.resize(1)
    assert buffer.max_entries == 1
    assert [item["event_id"] for item in buffer.snapshot()] == ["3"]


def test_runtime_log_settings_can_change_level_and_disable_file() -> None:
    settings = RuntimeLogSettings({"path": "logs/test-runtime.log"})
    value = settings.apply({"level": "TRACE", "file_enabled": False, "ring_buffer_size": 42})
    assert value["level"] == "TRACE"
    assert value["file_enabled"] is False
    assert value["ring_buffer_size"] == 42


def test_timeline_filter_and_button_reason() -> None:
    model = TimelineTableModel()
    model.set_rows(
        [
            {"category": "obs", "result": "healthy", "event_name": "obs.updated"},
            {
                "category": "lifecycle",
                "result": "failed",
                "event_name": "opening.failed",
                "error_code": "opening.timeout",
            },
        ]
    )
    model.set_filter("all", errors_only=True)
    assert model.rowCount() == 1
    model.set_filter("obs")
    assert model.rowCount() == 1

    enabled, reason = start_button_decision(
        {"status": "preparing", "ready": False, "adapter_modes": {}}, False
    )
    assert enabled is False
    assert "配信準備" in reason
