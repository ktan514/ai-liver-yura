from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any


class TraceLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    OFF = 100

    @classmethod
    def parse(cls, value: str | TraceLevel) -> TraceLevel:
        if isinstance(value, TraceLevel):
            return value
        try:
            return cls[value.upper()]
        except KeyError as error:
            choices = ", ".join(level.name for level in cls)
            raise ValueError(f"未対応のトレースレベルです: {value} ({choices})") from error


class TraceLogger:
    """レベルフィルタとテキスト/JSONL出力に対応したTrace Logger。"""

    _lock = threading.Lock()
    _trace_file_path = Path("logs/runtime_trace.log")
    _minimum_level = TraceLevel.INFO
    _format = "text"
    _max_bytes = 5 * 1024 * 1024
    _backup_count = 5

    def __init__(self, trace_file_path: str | Path | None = None) -> None:
        self._instance_trace_file_path = (
            Path(trace_file_path) if trace_file_path is not None else None
        )

    @classmethod
    def configure(
        cls,
        *,
        level: str | TraceLevel,
        trace_file_path: str | Path,
        output_format: str = "text",
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        normalized_format = output_format.lower()
        if normalized_format not in {"text", "jsonl"}:
            raise ValueError(f"未対応のトレース形式です: {output_format} (text, jsonl)")
        if max_bytes <= 0:
            raise ValueError("max_bytes は1以上で指定してください。")
        if backup_count < 0:
            raise ValueError("backup_count は0以上で指定してください。")
        cls._minimum_level = TraceLevel.parse(level)
        cls._trace_file_path = Path(trace_file_path)
        cls._format = normalized_format
        cls._max_bytes = max_bytes
        cls._backup_count = backup_count

    def debug(self, label: str, **values: object) -> None:
        self._write(TraceLevel.DEBUG, label, values)

    def info(self, label: str, **values: object) -> None:
        self._write(TraceLevel.INFO, label, values)

    def warning(self, label: str, **values: object) -> None:
        self._write(TraceLevel.WARNING, label, values)

    def error(self, label: str, **values: object) -> None:
        self._write(TraceLevel.ERROR, label, values)

    def write(
        self,
        label: str,
        *,
        level: str | TraceLevel | None = None,
        **values: object,
    ) -> None:
        """動的レベルまたは既存呼び出し用のTraceを出力する。"""

        record_level = TraceLevel.parse(level) if level is not None else self._infer_level(label)
        self._write(record_level, label, values)

    def _write(self, record_level: TraceLevel, label: str, values: dict[str, object]) -> None:
        """設定レベル以上のTraceを1行で出力する。"""

        if record_level < self._minimum_level or self._minimum_level is TraceLevel.OFF:
            return

        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        record: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record_level.name,
            "label": label,
            **values,
        }
        line = self._format_record(record)
        trace_file_path = self._instance_trace_file_path or self._trace_file_path

        with self._lock:
            trace_file_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(trace_file_path, line)
            with trace_file_path.open("a", encoding="utf-8") as trace_file:
                trace_file.write(line + "\n")

    @classmethod
    def _rotate_if_needed(cls, trace_file_path: Path, line: str) -> None:
        if not trace_file_path.exists():
            return
        next_record_size = len((line + "\n").encode("utf-8"))
        if trace_file_path.stat().st_size + next_record_size <= cls._max_bytes:
            return

        if cls._backup_count == 0:
            trace_file_path.write_text("", encoding="utf-8")
            return

        oldest_backup = cls._backup_path(trace_file_path, cls._backup_count)
        oldest_backup.unlink(missing_ok=True)
        for index in range(cls._backup_count - 1, 0, -1):
            source = cls._backup_path(trace_file_path, index)
            if source.exists():
                source.replace(cls._backup_path(trace_file_path, index + 1))
        trace_file_path.replace(cls._backup_path(trace_file_path, 1))

    @staticmethod
    def _backup_path(trace_file_path: Path, index: int) -> Path:
        return trace_file_path.with_name(f"{trace_file_path.name}.{index}")

    @staticmethod
    def _infer_level(label: str) -> TraceLevel:
        error_markers = (":error", "_failed", ":failed")
        warning_markers = (":fallback", "fallback_used")
        if any(marker in label for marker in error_markers):
            return TraceLevel.ERROR
        if any(marker in label for marker in warning_markers):
            return TraceLevel.WARNING
        return TraceLevel.DEBUG

    @classmethod
    def _format_record(cls, record: dict[str, Any]) -> str:
        if cls._format == "jsonl":
            return json.dumps(record, ensure_ascii=False, default=str)

        values = " ".join(
            f"{key}={cls._format_value(value)}"
            for key, value in record.items()
            if key not in {"timestamp", "level", "label"}
        )
        base = f"{record['timestamp']} {record['level']:<7} {record['label']}"
        return f"{base} | {values}" if values else base

    @staticmethod
    def _format_value(value: object) -> str:
        if isinstance(value, str) and value and not any(char.isspace() for char in value):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)


class NullTraceLogger:
    """Traceを出力しないLogger。テストや無効化用途で使う。"""

    def debug(self, label: str, **values: object) -> None:
        pass

    def info(self, label: str, **values: object) -> None:
        pass

    def warning(self, label: str, **values: object) -> None:
        pass

    def error(self, label: str, **values: object) -> None:
        pass

    def write(
        self,
        label: str,
        *,
        level: str | TraceLevel | None = None,
        **values: object,
    ) -> None:
        pass
