from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from streaming_admin.logging import ManualCheckLogModel, ManualCheckLogReader
from streaming_admin.ui.manual_check_log_widget import ManualCheckLogWidget


def write(path: Path, *values: object, end: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(json.dumps(value, ensure_ascii=False) for value in values) + end)


def entry(event: str, **values: object) -> dict[str, object]:
    return {
        "timestamp": "2026-07-17T12:00:00+09:00",
        "source": "core",
        "category": "stream.session",
        "event": event,
        "status": "completed",
        "session_id": "session",
        "activity_id": "activity",
        "reason": None,
        "details": values,
    }


def test_reader_tails_partial_parse_error_truncate_and_new_file(tmp_path: Path) -> None:
    first = tmp_path / "logs/manual_checks/streaming_demo_1.jsonl"
    write(first, entry("日本語"))
    reader = ManualCheckLogReader(tmp_path)
    reader.set_path(None)
    assert reader.path == first
    assert [item["event"] for item in reader.read_new()] == ["日本語"]
    assert reader.read_new() == []

    with first.open("ab") as stream:
        stream.write(b'{"event":"partial"')
    assert reader.read_new() == []
    with first.open("ab") as stream:
        stream.write(b"}\nnot-json\n")
    values = reader.read_new()
    assert values[0]["event"] == "partial"
    assert values[1]["event"] == "parse_error"

    first.write_text(json.dumps(entry("after_truncate")) + "\n", encoding="utf-8")
    assert reader.read_new()[0]["event"] == "after_truncate"
    second = tmp_path / "logs/manual_checks/streaming_demo_2.jsonl"
    write(second, entry("new_file"))
    os.utime(second, ns=(first.stat().st_mtime_ns + 1, first.stat().st_mtime_ns + 1))
    assert reader.discover_newer() is True
    assert reader.read_new()[0]["event"] == "new_file"


def test_reader_handles_missing_and_read_error(tmp_path: Path) -> None:
    reader = ManualCheckLogReader(tmp_path)
    assert reader.read_new() == []
    directory = tmp_path / "logs/manual_checks/streaming_demo_directory.jsonl"
    directory.mkdir(parents=True)
    reader.set_path(directory)
    try:
        reader.read_new()
    except OSError:
        pass
    else:
        raise AssertionError("directory read must fail")


def test_model_limits_filters_searches_and_masks_details() -> None:
    model = ManualCheckLogModel(max_rows=5000)
    values = [entry(f"event-{index}", token="secret") for index in range(5100)]
    values[-1]["category"] = "error"
    values[-1]["status"] = "failed"
    model.append(values)
    assert model.rowCount() == 5000
    assert "***REDACTED***" in model.detail(4999)
    assert "secret" not in model.detail(4999)
    model.set_filters(category="error", status="failed", keyword="event-5099")
    assert model.rowCount() == 1
    assert model.item(0)["event"] == "event-5099"  # type: ignore[index]


def test_widget_timer_reload_clear_follow_and_disconnected_file_access(tmp_path: Path) -> None:
    app = cast(QApplication, QApplication.instance() or QApplication([]))
    path = tmp_path / "logs/manual_checks/streaming_demo_ui.jsonl"
    write(path, entry("first"))
    widget = ManualCheckLogWidget(tmp_path)
    widget.configure("streaming_demo", {"enabled": True, "path": str(path)})
    assert widget.timer.isActive()
    assert widget.timer.interval() == 1000
    assert widget.model.rowCount() == 1
    widget.follow.setChecked(False)
    write(path, entry("second"))
    widget.poll()
    assert widget.model.rowCount() == 2
    assert widget.new_count.text() == "新着 1件"
    widget.follow.setChecked(True)
    assert widget.new_count.text() == ""
    widget.source_filter.setText("missing")
    assert widget.model.rowCount() == 0
    widget.source_filter.clear()
    widget.clear_display()
    assert widget.model.rowCount() == 0
    widget.reload()
    assert widget.model.rowCount() == 2
    widget.status.setText("Core: 切断")
    write(path, entry("offline"))
    widget.poll()
    assert widget.model.rowCount() == 3
    app.processEvents()
    widget.close()
