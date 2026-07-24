from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from app.domain.actions import ActionPlan
from app.domain.activities import Activity
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.memory import AgentMemoryState
from app.domain.relationships import RelationshipMemory
from app.domain.situation import SituationState


@dataclass(frozen=True, slots=True)
class AgentState:
    """AIライバーの現在状態を保持するRuntime用モデル。"""

    active_activity: Activity | None = None
    pending_activities: list[Activity] = field(default_factory=list)
    suspended_activities: list[Activity] = field(default_factory=list)
    running_actions: list[ActionPlan] = field(default_factory=list)
    prepared_actions: list[ActionPlan] = field(default_factory=list)
    current_emotion: EmotionState = field(default_factory=EmotionState)
    current_drive: DriveState = field(default_factory=DriveState)
    relationship_memory: RelationshipMemory = field(default_factory=RelationshipMemory)
    current_situation: SituationState = field(default_factory=SituationState)
    memory: AgentMemoryState = field(default_factory=AgentMemoryState)
    attention_target: str | None = None
    stream_status: str = "idle"
    last_user_input_at: datetime | None = None
    last_speech_started_at: datetime | None = None
    last_speech_finished_at: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def with_active_activity(self, activity: Activity | None) -> AgentState:
        return replace(
            self,
            active_activity=activity,
            updated_at=datetime.now(timezone.utc),
        )

    def with_pending_activities(self, activities: list[Activity]) -> AgentState:
        return replace(
            self,
            pending_activities=list(activities),
            updated_at=datetime.now(timezone.utc),
        )

    def with_suspended_activities(self, activities: list[Activity]) -> AgentState:
        return replace(
            self,
            suspended_activities=list(activities),
            updated_at=datetime.now(timezone.utc),
        )

    def with_running_actions(self, actions: list[ActionPlan]) -> AgentState:
        return replace(
            self,
            running_actions=list(actions),
            updated_at=datetime.now(timezone.utc),
        )

    def with_prepared_actions(self, actions: list[ActionPlan]) -> AgentState:
        return replace(
            self,
            prepared_actions=list(actions),
            updated_at=datetime.now(timezone.utc),
        )

    def with_emotion(self, emotion: EmotionState) -> AgentState:
        return replace(
            self,
            current_emotion=emotion,
            updated_at=datetime.now(timezone.utc),
        )

    def with_drive(self, drive: DriveState) -> AgentState:
        return replace(
            self,
            current_drive=drive,
            updated_at=datetime.now(timezone.utc),
        )

    def with_relationship_memory(self, memory: RelationshipMemory) -> AgentState:
        return replace(
            self,
            relationship_memory=memory,
            updated_at=datetime.now(timezone.utc),
        )

    def with_situation(self, situation: SituationState) -> AgentState:
        return replace(
            self,
            current_situation=situation,
            updated_at=datetime.now(timezone.utc),
        )

    def with_memory(self, memory: AgentMemoryState) -> AgentState:
        return replace(self, memory=memory, updated_at=datetime.now(timezone.utc))

    def with_attention_target(self, attention_target: str | None) -> AgentState:
        return replace(
            self,
            attention_target=attention_target,
            updated_at=datetime.now(timezone.utc),
        )

    def with_stream_status(self, stream_status: str) -> AgentState:
        if not stream_status:
            raise ValueError("stream_status は空文字にできません。")

        return replace(
            self,
            stream_status=stream_status,
            updated_at=datetime.now(timezone.utc),
        )

    def mark_user_input_received(self, occurred_at: datetime | None = None) -> AgentState:
        return replace(
            self,
            last_user_input_at=occurred_at or datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def mark_speech_started(self, occurred_at: datetime | None = None) -> AgentState:
        return replace(
            self,
            last_speech_started_at=occurred_at or datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def mark_speech_finished(self, occurred_at: datetime | None = None) -> AgentState:
        return replace(
            self,
            last_speech_finished_at=occurred_at or datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
