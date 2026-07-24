import json
import re

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


def test_debug_file_keeps_debug_details_out_of_info_summary(tmp_path) -> None:
    info_file = tmp_path / "runtime_trace.log"
    debug_file = tmp_path / "runtime_debug.log"
    TraceLogger.configure(
        level="INFO",
        trace_file_path=info_file,
        debug_file_enabled=True,
        debug_file_path=debug_file,
    )
    logger = TraceLogger()

    logger.debug(
        "agent_life_service:plan_next_event:skipped",
        reason="conversation_idle_timeout_not_reached",
    )
    logger.info("behavior_planner:activity_plan_evaluated", decision="conversation")

    info_content = info_file.read_text(encoding="utf-8")
    debug_content = debug_file.read_text(encoding="utf-8")
    assert "conversation_idle_timeout_not_reached" not in info_content
    assert "conversation_idle_timeout_not_reached" in debug_content
    assert "behavior_planner:activity_plan_evaluated" in info_content
    assert "behavior_planner:activity_plan_evaluated" in debug_content


def test_timestamp_uses_local_timezone_offset(tmp_path) -> None:
    trace_file = tmp_path / "trace.log"
    TraceLogger.configure(level="INFO", trace_file_path=trace_file)

    TraceLogger().info("app:start")

    timestamp = trace_file.read_text(encoding="utf-8").split(" ", maxsplit=1)[0]
    assert timestamp.endswith("Z") is False
    assert re.search(r"[+-]\d{2}:\d{2}$", timestamp)


def test_llm_details_are_one_line_and_separated_from_info(tmp_path) -> None:
    info_file = tmp_path / "runtime_trace.log"
    debug_file = tmp_path / "runtime_debug.log"
    TraceLogger.configure(
        level="INFO",
        trace_file_path=info_file,
        output_format="jsonl",
        debug_file_enabled=True,
        debug_file_path=debug_file,
        log_llm_prompts=True,
        log_llm_responses=True,
    )
    logger = TraceLogger()

    logger.llm_request(
        purpose="behavior_planning",
        provider="openai",
        model="test-model",
        activity_id="activity-1",
        event_id="event-1",
        session_id="session-1",
        request={"input": "一行目\n二行目"},
        user_input="しりとりしよう",
        available_capabilities=["games.shiritori.play"],
        planner_state={"mood": "excited"},
        constraints=["発話本文を生成しない"],
    )
    logger.llm_response(
        purpose="behavior_planning",
        provider="openai",
        model="test-model",
        activity_id="activity-1",
        raw_response='{"decision":"start_activity"}',
        parsed_response={"decision": "start_activity"},
        adopted_text="しりとりを開始する",
        stage="parsed",
    )

    assert not info_file.exists()
    lines = debug_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    request_record = json.loads(lines[0])
    response_record = json.loads(lines[1])
    assert request_record["request"]["input"] == "一行目\n二行目"
    assert request_record["available_capabilities"] == ["games.shiritori.play"]
    assert response_record["raw_response"] == '{"decision":"start_activity"}'
    assert response_record["parsed_response"] == {"decision": "start_activity"}
    assert response_record["adopted_text"] == "しりとりを開始する"


def test_sensitive_values_are_masked_in_nested_llm_details(
    tmp_path, monkeypatch
) -> None:
    debug_file = tmp_path / "runtime_debug.log"
    secret = "very-private-value-123"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    TraceLogger.configure(
        level="INFO",
        trace_file_path=tmp_path / "runtime_trace.log",
        output_format="jsonl",
        debug_file_enabled=True,
        debug_file_path=debug_file,
        log_llm_prompts=True,
    )

    TraceLogger().llm_request(
        purpose="conversation_generation",
        provider="openai",
        model="test-model",
        activity_id=None,
        event_id=None,
        session_id=None,
        request={
            "headers": {"Authorization": f"Bearer {secret}"},
            "api_key": secret,
            "input": (
                f"秘密を含む入力 {secret} " "postgresql://dbuser:dbpass@db.example/app"
            ),
        },
    )

    content = debug_file.read_text(encoding="utf-8")
    assert secret not in content
    record = json.loads(content)
    assert record["request"]["headers"]["Authorization"] == "***MASKED***"
    assert record["request"]["api_key"] == "***MASKED***"
    assert "***MASKED***" in record["request"]["input"]
    assert "dbpass" not in record["request"]["input"]


def test_llm_bodies_are_not_logged_when_disabled(tmp_path) -> None:
    debug_file = tmp_path / "runtime_debug.log"
    TraceLogger.configure(
        level="INFO",
        trace_file_path=tmp_path / "runtime_trace.log",
        debug_file_enabled=True,
        debug_file_path=debug_file,
        log_llm_prompts=False,
        log_llm_responses=False,
    )

    TraceLogger().llm_request(
        purpose="conversation_generation",
        provider="ollama",
        model="test-model",
        activity_id=None,
        event_id=None,
        session_id=None,
        request={"prompt": "記録してはいけない本文"},
    )
    TraceLogger().llm_response(
        purpose="conversation_generation",
        provider="ollama",
        model="test-model",
        activity_id=None,
        raw_response="記録してはいけない応答",
        adopted_text="記録してはいけない採用文",
    )

    assert not debug_file.exists()


def test_user_input_logging_obeys_setting(tmp_path) -> None:
    debug_file = tmp_path / "runtime_debug.log"
    TraceLogger.configure(
        level="INFO",
        trace_file_path=tmp_path / "runtime_trace.log",
        output_format="jsonl",
        debug_file_enabled=True,
        debug_file_path=debug_file,
        log_user_input=True,
    )

    TraceLogger().user_input(source="console", event_id="event-1", text="こんにちは")

    record = json.loads(debug_file.read_text(encoding="utf-8"))
    assert record["label"] == "user_input_received"
    assert record["source"] == "console"
    assert record["event_id"] == "event-1"
    assert record["text"] == "こんにちは"


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
