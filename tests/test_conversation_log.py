import json
from datetime import datetime, timezone

from app.utils.conversation_log import ConversationLogger


def test_conversation_logger_records_raw_text_speaker_source_and_time(tmp_path) -> None:
    path = tmp_path / "conversation.jsonl"
    logger = ConversationLogger(path)
    occurred_at = datetime(2026, 7, 20, 12, 34, 56, tzinfo=timezone.utc)

    logger.record(
        speaker="console",
        source="console",
        text="  加工しない本文  ",
        occurred_at=occurred_at,
        event_id="event-1",
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["timestamp"] == "2026-07-20T21:34:56.000+09:00"
    assert record["speaker"] == "console"
    assert record["source"] == "console"
    assert record["text"] == "  加工しない本文  "
    assert record["event_id"] == "event-1"
