from datetime import datetime, timezone

from app.adapters.prompt import SituationEvaluatorPromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.behavior import BehaviorPlanningContext
from app.domain.events import AgentEvent, AgentEventType
from app.domain.relationships import (
    RelationshipIdentity,
    RelationshipMemory,
    RelationshipState,
)
from app.runtime import ActivityManager, AgentLifeService
from app.runtime.character_response_pipeline import ResponseContextBuilder
from app.runtime.relationship_state_updater import RelationshipStateUpdater


def test_relationship_memory_preserves_independent_counterparts() -> None:
    occurred_at = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    memory = RelationshipMemory()
    memory = memory.record(
        RelationshipIdentity("youtube:viewer-1", "Alice", "viewer"),
        event_id="event-1",
        occurred_at=occurred_at,
    )
    memory = memory.record(
        RelationshipIdentity("youtube:viewer-2", "Bob", "member"),
        event_id="event-2",
        occurred_at=occurred_at,
    )
    memory = memory.record(
        RelationshipIdentity("youtube:viewer-1", "Alice 2", "member"),
        event_id="event-3",
        occurred_at=occurred_at,
    )
    memory = memory.record(
        RelationshipIdentity("youtube:viewer-1", "Alice 2", "member"),
        event_id="event-3",
        occurred_at=occurred_at,
    )

    alice = memory.get("youtube:viewer-1")
    bob = memory.get("youtube:viewer-2")
    assert alice is not None and bob is not None
    assert alice.display_name == "Alice 2"
    assert alice.role == "member"
    assert alice.interaction_count == 2
    assert alice.familiarity == 0.04
    assert bob.interaction_count == 1
    assert memory.current == alice


def test_relationship_memory_evicts_oldest_counterpart_at_limit() -> None:
    memory = RelationshipMemory(max_entries=2)
    for index in range(3):
        memory = memory.record(
            RelationshipIdentity(f"viewer-{index}", f"Viewer {index}"),
            event_id=f"event-{index}",
        )

    assert [item.counterpart_id for item in memory.relationships] == [
        "viewer-1",
        "viewer-2",
    ]
    assert memory.current_counterpart_id == "viewer-2"


def test_relationship_updater_uses_stable_youtube_identity_without_content_judgment() -> (
    None
):
    event = AgentEvent(
        event_type=AgentEventType.YOUTUBE_COMMENT,
        payload={
            "author": {
                "channel_id": "viewer-1",
                "display_name": "Alice",
                "role": "viewer",
            },
            "comment": "大好き！……でも最悪！",
        },
    )

    state = RelationshipStateUpdater().preview(RelationshipMemory(), event)

    assert state is not None
    assert state.counterpart_id == "youtube:viewer-1"
    assert state.trust == 0.5
    assert state.affinity == 0.0
    assert state.interaction_count == 1


def test_agent_life_service_keeps_relationship_across_turns() -> None:
    service = AgentLifeService(ActivityManager())
    first = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは", "source": "console"},
    )
    second = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "また来たよ", "source": "console"},
    )

    preview = service.preview_relationship(first)
    assert preview is not None and preview.interaction_count == 1
    assert service.agent_state.relationship_memory.current is None

    service.handle_event(first)
    service.handle_event(second)

    current = service.agent_state.relationship_memory.current
    assert current is not None
    assert current.counterpart_id == "local:user"
    assert current.interaction_count == 2
    assert current.familiarity == 0.04


def test_relationship_persistence_failure_does_not_stop_event_processing() -> None:
    class FailingStore:
        def load(self) -> RelationshipMemory:
            return RelationshipMemory()

        def save(self, memory: RelationshipMemory) -> None:
            raise OSError("disk unavailable")

    service = AgentLifeService(
        ActivityManager(),
        relationship_memory_store=FailingStore(),
    )

    state = service.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは", "source": "console"},
        )
    )

    assert state.relationship_memory.current is not None
    assert state.relationship_memory.current.interaction_count == 1


def test_relationship_context_reaches_situation_and_character_roles() -> None:
    relationship = RelationshipState(
        counterpart_id="youtube:viewer-1",
        display_name="Alice",
        role="member",
        familiarity=0.4,
        interaction_count=20,
    ).as_context()
    planning_context = BehaviorPlanningContext(
        user_text="また来たよ",
        source_event_id="event-1",
        available_capabilities=frozenset(),
        relationship=relationship,
    )

    situation_prompt = SituationEvaluatorPromptBuilder().build(planning_context)
    response_context = ResponseContextBuilder().build(
        Activity(
            activity_type=ActivityType.CONVERSATION_WITH_USER,
            goal="応答する",
            context={
                "event_payload": {
                    "text": "また来たよ",
                    "relationship": relationship,
                }
            },
        )
    )

    assert "Alice" in situation_prompt
    assert response_context.relationship == relationship
