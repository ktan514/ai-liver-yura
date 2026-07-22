from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.trace_context import TraceContext


@dataclass(frozen=True, slots=True)
class AutonomousSituationContext:
    """外部入力を含まない、自律Activity計画用の客観的状態。"""

    source_event_id: str
    agent_state: dict[str, object]
    drive_state: dict[str, float]
    emotion_state: dict[str, object]
    topic_state: dict[str, object]
    recent_speech_summary: str
    recent_topic_summary: str
    interrupted_topic: dict[str, object] | None
    stream_status: str
    ongoing_activity: dict[str, object] | None
    available_activity_definitions: tuple[str, ...]
    current_time_context: str
    relationship_state: dict[str, object] = field(default_factory=dict)
    event_context: dict[str, object] = field(default_factory=dict)
    trace_context: TraceContext | None = None


@dataclass(frozen=True, slots=True)
class AutonomousSituationAnalysis:
    """Situation Evaluatorが整理した自律行動候補。発話本文は含めない。"""

    suggested_action: str
    topic_candidate: str
    planning_reason: str
    relation_to_interrupted_topic: str
    conversation_phase: str | None = None
    initiative_level: float | None = None
    constraints: dict[str, object] = field(default_factory=dict)
