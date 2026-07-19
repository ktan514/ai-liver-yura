from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, cast
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class TraceContext:
    """一つの処理系列をEventからOutputまで関連付けるimmutableなContext。"""

    trace_id: str = ""
    parent_trace_id: str | None = None
    source_event_id: str | None = None
    activity_turn_id: str | None = None
    ongoing_activity_id: str | None = None
    confirmation_id: str | None = None
    behavior_plan_id: str | None = None
    activity_execution_result_id: str | None = None
    character_generation_result_id: str | None = None
    output_unit_id: str | None = None
    activity_result_id: str | None = None
    plugin_session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.trace_id:
            object.__setattr__(self, "trace_id", str(uuid4()))

    @classmethod
    def new(
        cls,
        *,
        source_event_id: str | None = None,
        parent_trace_id: str | None = None,
    ) -> TraceContext:
        return cls(source_event_id=source_event_id, parent_trace_id=parent_trace_id)

    def derive(self, **updates: str | None) -> TraceContext:
        allowed = {item.name for item in fields(self)} - {"trace_id"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"未対応のTraceContextキーです: {sorted(unknown)}")
        return replace(self, **cast(Any, updates))

    def child(self, *, source_event_id: str | None = None) -> TraceContext:
        return TraceContext.new(
            source_event_id=source_event_id,
            parent_trace_id=self.trace_id,
        )

    def as_log_fields(self) -> dict[str, str]:
        return {
            item.name: value
            for item in fields(self)
            if (value := getattr(self, item.name)) is not None
        }


def trace_context_from(value: object) -> TraceContext | None:
    if isinstance(value, TraceContext):
        return value
    if not isinstance(value, dict):
        return None
    nested = value.get("trace_context")
    return nested if isinstance(nested, TraceContext) else None
