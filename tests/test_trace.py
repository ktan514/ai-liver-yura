import json

import pytest

from app.utils.trace import TraceLogger


@pytest.fixture(autouse=True)
def restore_trace_configuration(tmp_path):
    yield
    TraceLogger.configure(
        level="INFO",
        trace_file_path=tmp_path / "restored.log",
        output_format="text",
    )


def test_info_level_filters_debug_records(tmp_path) -> None:
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(level="INFO", trace_file_path=trace_file)
    logger = TraceLogger()

    logger.debug("details", value=1)
    logger.info("lifecycle", value=2)

    content = trace_file.read_text(encoding="utf-8")
    assert "details" not in content
    assert "INFO    lifecycle | value=2" in content


def test_write_accepts_dynamic_level(tmp_path) -> None:
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(level="INFO", trace_file_path=trace_file)

    TraceLogger().write("dynamic", level="WARNING", reason="fallback")

    content = trace_file.read_text(encoding="utf-8")
    assert "WARNING dynamic | reason=fallback" in content


def test_error_label_is_logged_without_explicit_level(tmp_path) -> None:
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(level="ERROR", trace_file_path=trace_file)

    TraceLogger().write("component:request:error", reason="timeout")

    content = trace_file.read_text(encoding="utf-8")
    assert "ERROR   component:request:error | reason=timeout" in content


def test_jsonl_format_contains_level(tmp_path) -> None:
    trace_file = tmp_path / "trace.jsonl"
    TraceLogger.configure(
        level="DEBUG",
        trace_file_path=trace_file,
        output_format="jsonl",
    )

    TraceLogger().write("component:detail", value="日本語")

    record = json.loads(trace_file.read_text(encoding="utf-8"))
    assert record["level"] == "DEBUG"
    assert record["label"] == "component:detail"
    assert record["value"] == "日本語"


def test_off_level_does_not_create_file(tmp_path) -> None:
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(level="OFF", trace_file_path=trace_file)

    TraceLogger().error("component:error")

    assert not trace_file.exists()


def test_configure_rejects_unsupported_format(tmp_path) -> None:
    with pytest.raises(ValueError, match="未対応のトレース形式"):
        TraceLogger.configure(
            level="INFO",
            trace_file_path=tmp_path / "trace.log",
            output_format="csv",
        )


def test_rotates_log_and_keeps_configured_backup_count(tmp_path) -> None:
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(
        level="DEBUG",
        trace_file_path=trace_file,
        max_bytes=1,
        backup_count=2,
    )
    logger = TraceLogger()

    for index in range(1, 5):
        logger.write(f"record:{index}")

    assert "record:4" in trace_file.read_text(encoding="utf-8")
    assert "record:3" in (tmp_path / "trace.log.1").read_text(encoding="utf-8")
    second_backup = (tmp_path / "trace.log.2").read_text(encoding="utf-8")
    assert "record:2" in second_backup
    assert "record:1" not in second_backup
    assert not (tmp_path / "trace.log.3").exists()


def test_rotation_without_backups_truncates_current_log(tmp_path) -> None:
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(
        level="DEBUG",
        trace_file_path=trace_file,
        max_bytes=1,
        backup_count=0,
    )
    logger = TraceLogger()

    logger.write("record:first")
    logger.write("record:second")

    content = trace_file.read_text(encoding="utf-8")
    assert "record:first" not in content
    assert "record:second" in content
    assert not (tmp_path / "trace.log.1").exists()


@pytest.mark.parametrize(
    ("max_bytes", "backup_count", "message"),
    [(0, 1, "max_bytes"), (1, -1, "backup_count")],
)
def test_configure_rejects_invalid_rotation_settings(
    tmp_path, max_bytes: int, backup_count: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TraceLogger.configure(
            level="INFO",
            trace_file_path=tmp_path / "trace.log",
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
