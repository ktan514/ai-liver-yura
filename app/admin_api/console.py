from __future__ import annotations

import json
import logging
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.utils.trace import TraceLevel, TraceLogger

UPDATE_MODES = frozenset({"automatic", "manual", "event_driven"})
FRESHNESS_VALUES = frozenset({"fresh", "stale", "unknown"})
OPERATOR_ACTIONS = frozenset(
    {
        "none",
        "youtube_start_required",
        "youtube_stop_required",
        "authentication_required",
        "obs_confirmation_required",
        "recovery_decision_required",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def freshness(
    last_updated_at: object, stale_after_seconds: int, *, now: datetime | None = None
) -> str:
    if not isinstance(last_updated_at, str) or not last_updated_at:
        return "unknown"
    try:
        observed = datetime.fromisoformat(last_updated_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
    except ValueError:
        return "unknown"
    current = now or datetime.now(timezone.utc)
    return (
        "stale"
        if (current - observed).total_seconds() > stale_after_seconds
        else "fresh"
    )


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    can_start_broadcast: bool
    can_stop_broadcast: bool
    can_open_studio: bool
    can_check_status: bool
    requires_operator_confirmation: bool
    studio_url: str | None = None

    @classmethod
    def for_adapter(
        cls, adapter_type: str, override: Mapping[str, Any] | None = None
    ) -> AdapterCapabilities:
        # Both adapters currently implement transition and status APIs. Composition may
        # override this for a manual-only adapter without teaching the UI adapter names.
        defaults = cls(
            can_start_broadcast=adapter_type in {"fake", "google"},
            can_stop_broadcast=adapter_type in {"fake", "google"},
            can_open_studio=False,
            can_check_status=adapter_type in {"fake", "google"},
            requires_operator_confirmation=False,
        )
        if not override:
            return defaults
        values = asdict(defaults)
        for key in values:
            if key in override:
                values[key] = override[key]
        return cls(**values)


@dataclass(frozen=True, slots=True)
class OperatorActionState:
    action_type: str = "none"
    status: str = "not_required"

    def transition(self, target: str) -> OperatorActionState:
        allowed = {
            "not_required": {"waiting"},
            "waiting": {"acknowledged", "completed", "expired"},
            "acknowledged": {"completed", "expired"},
            "completed": set(),
            "expired": set(),
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(
                f"invalid operator action transition: {self.status} -> {target}"
            )
        return OperatorActionState(self.action_type, target)


def operator_action_for(
    capabilities: AdapterCapabilities,
    *,
    phase: str,
    auth_status: str = "authenticated",
) -> dict[str, Any]:
    if auth_status not in {"authenticated", "not_required"}:
        action = "authentication_required"
        title = "YouTube認証が必要です"
    elif phase == "starting" and not capabilities.can_start_broadcast:
        action = "youtube_start_required"
        title = "YouTube Studioで配信を開始してください"
    elif phase == "ending" and not capabilities.can_stop_broadcast:
        action = "youtube_stop_required"
        title = "YouTube Studioで配信を終了してください"
    else:
        action = "none"
        title = "人間の操作は不要です"
    return {
        "action_type": action,
        "status": "not_required" if action == "none" else "waiting",
        "title": title,
        "description": (
            "" if action == "none" else "Studioで操作後、状態を確認してください。"
        ),
        "steps": (
            []
            if action == "none"
            else ["映像と音声を確認", "公開状態を変更", "状態を確認"]
        ),
        "studio_url": capabilities.studio_url,
        "can_confirm": action != "none" and capabilities.can_check_status,
        "can_cancel": action != "none",
        "can_retry": action != "none",
    }


class DiagnosticRingBuffer:
    def __init__(self, max_entries: int = 500) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._items: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = threading.RLock()

    @property
    def max_entries(self) -> int:
        return int(self._items.maxlen or 0)

    def resize(self, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        with self._lock:
            self._items = deque(self._items, maxlen=max_entries)

    def append(self, item: Mapping[str, Any]) -> None:
        with self._lock:
            self._items.append(dict(item))

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items]


class RuntimeLogSettings:
    LEVELS = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR"}

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        value = dict(initial or {})
        self.values: dict[str, Any] = {
            "file_enabled": value.get("file_enabled", True),
            "level": str(value.get("level", "INFO")).upper(),
            "path": str(value.get("path", "logs/runtime_trace.log")),
            "max_retention_days": int(value.get("max_retention_days", 14)),
            "max_file_size": int(value.get("max_file_size", 5 * 1024 * 1024)),
            "backup_count": int(value.get("backup_count", 5)),
            "ring_buffer_size": int(value.get("ring_buffer_size", 500)),
            "obs_auto_refresh": bool(value.get("obs_auto_refresh", False)),
            "obs_refresh_interval": int(value.get("obs_refresh_interval", 30)),
            "youtube_auto_refresh": bool(value.get("youtube_auto_refresh", False)),
            "youtube_refresh_interval": int(value.get("youtube_refresh_interval", 30)),
            "stale_after_seconds": int(value.get("stale_after_seconds", 60)),
            "show_operator_dialogs": bool(value.get("show_operator_dialogs", True)),
        }
        self.apply({})

    def apply(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        candidate = {**self.values, **dict(changes)}
        level = str(candidate["level"]).upper()
        if level not in self.LEVELS:
            raise ValueError("unsupported log level")
        for key in (
            "max_file_size",
            "ring_buffer_size",
            "obs_refresh_interval",
            "youtube_refresh_interval",
            "stale_after_seconds",
        ):
            if int(candidate[key]) < 1:
                raise ValueError(f"{key} must be positive")
        if (
            int(candidate["backup_count"]) < 0
            or int(candidate["max_retention_days"]) < 0
        ):
            raise ValueError("retention values must not be negative")
        candidate["level"] = level
        self.values = candidate
        trace_level: str | TraceLevel = "DEBUG" if level == "TRACE" else level
        if not bool(candidate["file_enabled"]):
            trace_level = TraceLevel.OFF
        TraceLogger.configure(
            level=trace_level,
            trace_file_path=str(candidate["path"]),
            max_bytes=int(candidate["max_file_size"]),
            backup_count=int(candidate["backup_count"]),
        )
        logging.getLogger().setLevel(
            logging.DEBUG if level == "TRACE" else getattr(logging, level)
        )
        return dict(self.values)


def timeline_entry(
    event_type: str, data: Mapping[str, Any], trace_id: str = ""
) -> dict[str, Any]:
    lowered = event_type.lower()
    if "obs" in lowered:
        category = "obs"
    elif "youtube" in lowered:
        category = "youtube"
    elif "speech" in lowered or "opening" in lowered or "main" in lowered:
        category = "speech" if "speech" in lowered else "lifecycle"
    elif "error" in lowered or "failed" in lowered:
        category = "error"
    else:
        category = "lifecycle" if event_type.startswith("stream") else "system"
    error_code = data.get("error_code") or data.get("failure_code")
    result = (
        "failed"
        if error_code or "failed" in lowered
        else str(data.get("status") or "updated")
    )
    return {
        "timestamp": utc_now(),
        "category": category,
        "event_name": event_type,
        "result": result,
        "summary": str(data.get("summary") or data.get("message") or result),
        "detail": dict(data),
        "event_id": str(uuid4()),
        "activity_id": data.get("activity_id"),
        "action_id": data.get("action_id"),
        "trace_id": trace_id,
        "error_code": error_code,
        "error_message": data.get("error_message") or data.get("failure_message"),
    }


def save_snapshot(
    snapshot: Mapping[str, Any], directory: str | Path = "logs/diagnostics"
) -> str:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"diagnostic-{stamp}.json"
    target.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(target)
