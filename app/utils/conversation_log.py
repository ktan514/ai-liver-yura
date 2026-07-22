from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class ConversationLogger:
    """調査用に、生の会話入出力だけを時系列のJSONLへ記録する。"""

    _lock = threading.Lock()
    _default_path = Path("logs/conversation.jsonl")

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else self._default_path

    def record(
        self,
        *,
        speaker: str,
        source: str,
        text: str,
        speaker_name: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        action_id: str | None = None,
    ) -> None:
        """正規化や要約をしていない本文と、その発生元・時刻を1件記録する。"""

        if not text:
            return
        timestamp = occurred_at or datetime.now(timezone.utc)
        record = {
            "timestamp": timestamp.astimezone().isoformat(timespec="milliseconds"),
            "speaker": speaker,
            "speaker_name": speaker_name,
            "source": source,
            "text": text,
            "event_id": event_id,
            "action_id": action_id,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
