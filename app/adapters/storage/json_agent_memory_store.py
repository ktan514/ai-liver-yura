from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.shared.contracts.memory import (
    AgentMemorySnapshot,
    EmotionHistoryRecord,
    EpisodicMemoryRecord,
    SemanticMemoryRecord,
    UnfinishedActivityRecord,
    UnrecoveredTopicRecord,
)


class JsonAgentMemoryStore:
    """Shared Memory Snapshotを原子的に保存するJSON Adapter。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> AgentMemorySnapshot:
        if not self._path.exists():
            return AgentMemorySnapshot()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != "1":
            raise ValueError("AgentMemorySnapshotのschema_versionが不正です。")
        return AgentMemorySnapshot(
            episodic=tuple(
                EpisodicMemoryRecord(
                    event_id=str(item["event_id"]),
                    event_type=str(item["event_type"]),
                    occurred_at=self._datetime(item["occurred_at"]),
                    activity_id=self._optional_str(item.get("activity_id")),
                    counterpart_id=self._optional_str(item.get("counterpart_id")),
                )
                for item in self._items(payload, "episodic")
            ),
            semantic=tuple(
                SemanticMemoryRecord(
                    subject=str(item["subject"]),
                    fact=str(item["fact"]),
                    importance=float(item["importance"]),
                    learned_at=self._datetime(item["learned_at"]),
                    memory_id=str(item["memory_id"]),
                )
                for item in self._items(payload, "semantic")
            ),
            unfinished_activities=tuple(
                UnfinishedActivityRecord(
                    activity_id=str(item["activity_id"]),
                    activity_type=str(item["activity_type"]),
                    goal=str(item["goal"]),
                    status=str(item["status"]),
                    priority=int(item["priority"]),
                    updated_at=self._datetime(item["updated_at"]),
                )
                for item in self._items(payload, "unfinished_activities")
            ),
            unrecovered_topics=tuple(
                UnrecoveredTopicRecord(
                    topic_id=str(item["topic_id"]),
                    source_activity_id=str(item["source_activity_id"]),
                    summary=str(item["summary"]),
                    status=str(item["status"]),
                    importance=float(item["importance"]),
                    interrupted_at=self._optional_datetime(item.get("interrupted_at")),
                )
                for item in self._items(payload, "unrecovered_topics")
            ),
            emotion_history=tuple(
                EmotionHistoryRecord(
                    source_event_id=str(item["source_event_id"]),
                    before=self._mapping(item.get("before")),
                    after=self._mapping(item.get("after")),
                    reason=str(item["reason"]),
                    recorded_at=self._datetime(item["recorded_at"]),
                )
                for item in self._items(payload, "emotion_history")
            ),
        )

    def save(self, snapshot: AgentMemorySnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(snapshot)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(
                    payload,
                    file,
                    ensure_ascii=False,
                    indent=2,
                    default=self._json_default,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self._path)
        except BaseException:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _items(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise ValueError(f"{key}はobjectのlistで指定してください。")
        return value

    @staticmethod
    def _datetime(value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("datetimeはISO文字列で指定してください。")
        return datetime.fromisoformat(value)

    @classmethod
    def _optional_datetime(cls, value: object) -> datetime | None:
        return None if value is None else cls._datetime(value)

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _mapping(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError("emotion stateはobject形式で指定してください。")
        return {str(key): item for key, item in value.items()}

    @staticmethod
    def _json_default(value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"JSONへ変換できない型です: {type(value).__name__}")
