from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.events.agent_event_type import AgentEventType
from app.domain.trace_context import TraceContext


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """Runtimeへ流すイベント。

    Event は「起きたこと」を表す。
    外部入力だけでなく、内部状態変化や Action 実行結果も Event として扱う。
    """

    event_type: AgentEventType
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid4()))
    discardable: bool = False
    replace_key: str | None = None
    trace_context: TraceContext = field(default_factory=TraceContext.new)

    def __post_init__(self) -> None:
        if (
            self.trace_context.source_event_id is None
            or self.trace_context.activity_turn_id is None
        ):
            object.__setattr__(
                self,
                "trace_context",
                self.trace_context.derive(
                    source_event_id=self.trace_context.source_event_id or self.event_id,
                    activity_turn_id=self.trace_context.activity_turn_id or str(uuid4()),
                ),
            )
