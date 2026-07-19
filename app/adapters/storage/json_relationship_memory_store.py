from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.domain.relationships import RelationshipMemory, RelationshipState
from app.ports.relationship_memory_store import RelationshipMemoryStore


class JsonRelationshipMemoryStore(RelationshipMemoryStore):
    """RelationshipMemoryをローカルJSONへ原子的に保存するAdapter。"""

    _SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, max_entries: int = 1000) -> None:
        if max_entries <= 0:
            raise ValueError("max_entriesは1以上にしてください。")
        self._path = Path(path)
        self._max_entries = max_entries

    def load(self) -> RelationshipMemory:
        if not self._path.exists():
            return RelationshipMemory(max_entries=self._max_entries)
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self._SCHEMA_VERSION
        ):
            raise ValueError("RelationshipMemoryのschema_versionが不正です。")
        raw_relationships = payload.get("relationships")
        if not isinstance(raw_relationships, list):
            raise ValueError("relationshipsはlist形式で指定してください。")
        relationships = tuple(self._deserialize(item) for item in raw_relationships)
        relationships = relationships[-self._max_entries :]
        current = payload.get("current_counterpart_id")
        if current is not None and not isinstance(current, str):
            raise ValueError("current_counterpart_idは文字列またはnullです。")
        if current is not None and not any(
            item.counterpart_id == current for item in relationships
        ):
            current = None
        return RelationshipMemory(
            relationships=relationships,
            current_counterpart_id=current,
            max_entries=self._max_entries,
        )

    def save(self, memory: RelationshipMemory) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            "current_counterpart_id": memory.current_counterpart_id,
            "relationships": [self._serialize(item) for item in memory.relationships],
        }
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
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
    def _serialize(state: RelationshipState) -> dict[str, object]:
        return {
            "counterpart_id": state.counterpart_id,
            "display_name": state.display_name,
            "role": state.role,
            "familiarity": state.familiarity,
            "trust": state.trust,
            "affinity": state.affinity,
            "interaction_count": state.interaction_count,
            "last_interaction_at": (
                state.last_interaction_at.isoformat()
                if state.last_interaction_at is not None
                else None
            ),
            "last_event_id": state.last_event_id,
        }

    @staticmethod
    def _deserialize(value: Any) -> RelationshipState:
        if not isinstance(value, dict):
            raise ValueError("relationshipはobject形式で指定してください。")
        last_interaction_at = value.get("last_interaction_at")
        if last_interaction_at is not None and not isinstance(last_interaction_at, str):
            raise ValueError("last_interaction_atは文字列またはnullです。")
        return RelationshipState(
            counterpart_id=str(value["counterpart_id"]),
            display_name=str(value["display_name"]),
            role=str(value.get("role", "user")),
            familiarity=float(value.get("familiarity", 0.0)),
            trust=float(value.get("trust", 0.5)),
            affinity=float(value.get("affinity", 0.0)),
            interaction_count=int(value.get("interaction_count", 0)),
            last_interaction_at=(
                datetime.fromisoformat(last_interaction_at)
                if last_interaction_at is not None
                else None
            ),
            last_event_id=(
                str(value["last_event_id"])
                if value.get("last_event_id") is not None
                else None
            ),
        )
