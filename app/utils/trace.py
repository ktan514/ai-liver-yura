

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TraceLogger:
    """Runtime 全体で使う簡易 Trace Logger。"""

    def __init__(self, trace_file_path: str | Path = "logs/runtime_trace.jsonl") -> None:
        self._trace_file_path = Path(trace_file_path)

    def write(self, label: str, **values: object) -> None:
        """1行 JSON 形式で Trace を出力する。"""

        self._trace_file_path.parent.mkdir(parents=True, exist_ok=True)

        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "label": label,
            **values,
        }

        with self._trace_file_path.open("a", encoding="utf-8") as trace_file:
            trace_file.write(
                json.dumps(record, ensure_ascii=False, default=str) + "\n"
            )


class NullTraceLogger:
    """Trace を出力しない Logger。テストや無効化用途で使う。"""

    def write(self, label: str, **values: object) -> None:
        pass