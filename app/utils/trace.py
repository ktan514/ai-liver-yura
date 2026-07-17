from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

from app.domain.trace_context import TraceContext


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
    _timezone = "local"
    _debug_file_enabled = False
    _debug_file_path = Path("logs/runtime_debug.log")
    _log_llm_prompts = False
    _log_llm_responses = False
    _log_user_input = False
    _sensitive_key = re.compile(
        r"^(?:[a-z0-9]+[_-])*(?:api[_-]?key|authorization|password|passwd|token|"
        r"access[_-]?token|"
        r"refresh[_-]?token|auth[_-]?token|bearer[_-]?token|secret|client[_-]?secret|"
        r"dsn|db[_-]?url|database[_-]?url|credentials?)$",
        re.IGNORECASE,
    )
    _sensitive_env_key = re.compile(
        r"(?:api[_-]?key|authorization|password|passwd|(?:^|[_-])token(?:$|[_-])|"
        r"secret|dsn|credential)",
        re.IGNORECASE,
    )
    _inline_secret_patterns = (
        re.compile(r"(?i)(bearer\s+)[^\s\"']+"),
        re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}\b"),
        re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+(@)"),
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://"
            r"[^\s\"']+"
        ),
        re.compile(
            r"(?i)((?:api[_-]?key|authorization|password|passwd|token|secret|dsn)"
            r"\s*[:=]\s*)[^\s,;\"']+"
        ),
    )

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
        timezone_name: str = "local",
        debug_file_enabled: bool = False,
        debug_file_path: str | Path = "logs/runtime_debug.log",
        log_llm_prompts: bool = False,
        log_llm_responses: bool = False,
        log_user_input: bool = False,
    ) -> None:
        normalized_format = output_format.lower()
        if normalized_format not in {"text", "jsonl"}:
            raise ValueError(f"未対応のトレース形式です: {output_format} (text, jsonl)")
        if max_bytes <= 0:
            raise ValueError("max_bytes は1以上で指定してください。")
        if backup_count < 0:
            raise ValueError("backup_count は0以上で指定してください。")
        if timezone_name.lower() != "local":
            raise ValueError("trace.timezone は local を指定してください。")
        cls._minimum_level = TraceLevel.parse(level)
        cls._trace_file_path = Path(trace_file_path)
        cls._format = normalized_format
        cls._max_bytes = max_bytes
        cls._backup_count = backup_count
        cls._timezone = timezone_name.lower()
        cls._debug_file_enabled = debug_file_enabled
        cls._debug_file_path = Path(debug_file_path)
        cls._log_llm_prompts = log_llm_prompts
        cls._log_llm_responses = log_llm_responses
        cls._log_user_input = log_user_input

    def debug(self, label: str, **values: object) -> None:
        self._write(TraceLevel.DEBUG, label, values)

    def info(self, label: str, **values: object) -> None:
        self._write(TraceLevel.INFO, label, values)

    def warning(self, label: str, **values: object) -> None:
        self._write(TraceLevel.WARNING, label, values)

    def error(self, label: str, **values: object) -> None:
        self._write(TraceLevel.ERROR, label, values)

    def bind(self, context: TraceContext | None = None, **values: object) -> TraceContextLogger:
        bound = context.as_log_fields() if context is not None else {}
        return TraceContextLogger(self, {**bound, **values})

    def llm_request(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        activity_id: str | None,
        event_id: str | None,
        session_id: str | None,
        request: object,
        user_input: object = None,
        available_capabilities: object = None,
        planner_state: object = None,
        constraints: object = None,
        llm_role: str | None = None,
        model_key: str | None = None,
        service: str | None = None,
        trace_id: str | None = None,
        parent_trace_id: str | None = None,
        source_event_id: str | None = None,
        activity_turn_id: str | None = None,
        ongoing_activity_id: str | None = None,
        confirmation_id: str | None = None,
        behavior_plan_id: str | None = None,
        activity_execution_result_id: str | None = None,
        character_generation_result_id: str | None = None,
        output_unit_id: str | None = None,
        activity_result_id: str | None = None,
        game_session_id: str | None = None,
        request_id: str | None = None,
        attempt: int = 1,
    ) -> None:
        if not self._log_llm_prompts:
            return
        self.debug(
            "llm_request",
            purpose=purpose,
            provider=provider,
            model=model,
            activity_id=activity_id,
            event_id=event_id,
            session_id=session_id,
            request=request,
            user_input=user_input,
            available_capabilities=available_capabilities,
            planner_state=planner_state,
            constraints=constraints,
            llm_role=llm_role or purpose,
            model_key=model_key or model,
            service=service or provider,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            source_event_id=source_event_id or event_id,
            activity_turn_id=activity_turn_id or activity_id,
            ongoing_activity_id=ongoing_activity_id,
            confirmation_id=confirmation_id,
            behavior_plan_id=behavior_plan_id,
            activity_execution_result_id=activity_execution_result_id,
            character_generation_result_id=character_generation_result_id,
            output_unit_id=output_unit_id,
            activity_result_id=activity_result_id,
            game_session_id=game_session_id,
            request_id=request_id,
            attempt=attempt,
        )

    def llm_response(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        activity_id: str | None,
        raw_response: object,
        parsed_response: object = None,
        adopted_text: str | None = None,
        fallback_used: bool = False,
        stage: str = "completed",
        llm_role: str | None = None,
        model_key: str | None = None,
        service: str | None = None,
        trace_id: str | None = None,
        parent_trace_id: str | None = None,
        source_event_id: str | None = None,
        activity_turn_id: str | None = None,
        ongoing_activity_id: str | None = None,
        confirmation_id: str | None = None,
        behavior_plan_id: str | None = None,
        activity_execution_result_id: str | None = None,
        character_generation_result_id: str | None = None,
        output_unit_id: str | None = None,
        activity_result_id: str | None = None,
        game_session_id: str | None = None,
        request_id: str | None = None,
        attempt: int = 1,
    ) -> None:
        if not self._log_llm_responses:
            return
        self.debug(
            "llm_response",
            purpose=purpose,
            provider=provider,
            model=model,
            activity_id=activity_id,
            stage=stage,
            raw_response=raw_response,
            parsed_response=parsed_response,
            adopted_text=adopted_text,
            fallback_used=fallback_used,
            llm_role=llm_role or purpose,
            model_key=model_key or model,
            service=service or provider,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            source_event_id=source_event_id,
            activity_turn_id=activity_turn_id or activity_id,
            ongoing_activity_id=ongoing_activity_id,
            confirmation_id=confirmation_id,
            behavior_plan_id=behavior_plan_id,
            activity_execution_result_id=activity_execution_result_id,
            character_generation_result_id=character_generation_result_id,
            output_unit_id=output_unit_id,
            activity_result_id=activity_result_id,
            game_session_id=game_session_id,
            request_id=request_id,
            attempt=attempt,
        )

    def user_input(
        self,
        *,
        source: str,
        event_id: str,
        text: str,
        normalized: bool = True,
        trace_id: str | None = None,
        parent_trace_id: str | None = None,
        activity_turn_id: str | None = None,
        confirmation_id: str | None = None,
    ) -> None:
        if not self._log_user_input:
            return
        self.debug(
            "user_input_received",
            source=source,
            event_id=event_id,
            text=text,
            normalized=normalized,
            text_length=len(text),
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            source_event_id=event_id,
            activity_turn_id=activity_turn_id,
            confirmation_id=confirmation_id,
        )

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

        primary_enabled = (
            self._minimum_level is not TraceLevel.OFF and record_level >= self._minimum_level
        )
        debug_enabled = self._debug_file_enabled and self._minimum_level is not TraceLevel.OFF
        if not primary_enabled and not debug_enabled:
            return

        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        masked_values = self._mask(values)
        if not isinstance(masked_values, dict):
            masked_values = {}
        record: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record_level.name,
            "label": label,
            **masked_values,
        }
        line = self._format_record(record)
        trace_file_path = self._instance_trace_file_path or self._trace_file_path

        with self._lock:
            if primary_enabled:
                self._append(trace_file_path, line)
            if debug_enabled and self._debug_file_path != trace_file_path:
                self._append(self._debug_file_path, line)

    @classmethod
    def _append(cls, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        cls._rotate_if_needed(path, line)
        with path.open("a", encoding="utf-8") as trace_file:
            trace_file.write(line + "\n")

    @classmethod
    def _mask(cls, value: object, key: str | None = None) -> object:
        if key is not None and cls._sensitive_key.search(key):
            return "***MASKED***"
        if isinstance(value, dict):
            return {
                str(item_key): cls._mask(item, str(item_key)) for item_key, item in value.items()
            }
        if is_dataclass(value) and not isinstance(value, type):
            return cls._mask(asdict(value))
        if isinstance(value, Enum):
            return cls._mask(value.value)
        if isinstance(value, (list, tuple, set, frozenset)):
            return [cls._mask(item) for item in value]
        if isinstance(value, str):
            masked = value
            for env_key, env_value in os.environ.items():
                if env_value and len(env_value) >= 4 and cls._sensitive_env_key.search(env_key):
                    masked = masked.replace(env_value, "***MASKED***")
            for pattern in cls._inline_secret_patterns:
                if pattern.groups == 1:
                    masked = pattern.sub(r"\1***MASKED***", masked)
                elif pattern.groups == 2:
                    masked = pattern.sub(r"\1***MASKED***\2", masked)
                else:
                    masked = pattern.sub("***MASKED***", masked)
            return masked
        return value

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

    def bind(self, context: TraceContext | None = None, **values: object) -> TraceContextLogger:
        return TraceContextLogger(self, values)

    def llm_request(self, **values: object) -> None:
        pass

    def llm_response(self, **values: object) -> None:
        pass

    def user_input(self, **values: object) -> None:
        pass

    def write(
        self,
        label: str,
        *,
        level: str | TraceLevel | None = None,
        **values: object,
    ) -> None:
        pass


class TraceContextLogger:
    """TraceContextを各レコードへ一貫して付与するLogger Adapter。"""

    def __init__(self, logger: TraceLogger | NullTraceLogger, values: dict[str, object]) -> None:
        self._logger = logger
        self._values = dict(values)

    def bind(self, context: TraceContext | None = None, **values: object) -> TraceContextLogger:
        contextual = context.as_log_fields() if context is not None else {}
        return TraceContextLogger(self._logger, {**self._values, **contextual, **values})

    def debug(self, label: str, **values: object) -> None:
        self._logger.debug(label, **self._merge(values))

    def info(self, label: str, **values: object) -> None:
        self._logger.info(label, **self._merge(values))

    def warning(self, label: str, **values: object) -> None:
        self._logger.warning(label, **self._merge(values))

    def error(self, label: str, **values: object) -> None:
        self._logger.error(label, **self._merge(values))

    def write(self, label: str, *, level: str | TraceLevel | None = None, **values: object) -> None:
        self._logger.write(label, level=level, **self._merge(values))

    def _merge(self, values: dict[str, object]) -> dict[str, object]:
        return {**self._values, **values}
