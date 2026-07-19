from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.prompt import SituationEvaluatorPromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.behavior import BehaviorPlanningContext
from app.domain.events import AgentEvent, AgentEventType
from app.domain.situation import SituationState
from app.runtime import ActivityManager, AgentLifeService


def test_situation_state_keeps_event_and_activity_snapshot_without_text() -> None:
    occurred_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    state = SituationState().observe_event(
        event_id="event-1",
        event_type="user_text",
        occurred_at=occurred_at,
        input_source="console",
        input_authority_role="administrator",
        attention_target="local:user",
    )
    state = state.with_activity_snapshot(
        active_activity_id="activity-1",
        active_activity_type="conversation_with_user",
        pending_activity_count=2,
        suspended_activity_count=1,
        ongoing_activity_id=None,
        ongoing_activity_type=None,
        ongoing_activity_status=None,
    )

    context = state.as_context()
    assert context["last_event_id"] == "event-1"
    assert context["active_activity_type"] == "conversation_with_user"
    assert context["input_authority_role"] == "administrator"
    assert context["pending_activity_count"] == 2
    assert "発話本文" not in str(context)


def test_agent_life_service_continuously_updates_situation_and_attention() -> None:
    manager = ActivityManager()
    service = AgentLifeService(manager)
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは", "source": "console"},
    )

    service.handle_event(event)
    manager.register_plugin_activity(
        Activity(
            ActivityType.CONVERSATION_WITH_USER,
            "応答する",
            source_event_id=event.event_id,
        )
    )
    state = service.sync_from_activity_manager()

    assert state.attention_target == "local:user"
    assert state.current_situation.last_event_id == event.event_id
    assert state.current_situation.input_source == "console"
    assert state.current_situation.active_activity_type == "conversation_with_user"


def test_situation_context_reaches_situation_evaluator_prompt() -> None:
    context = BehaviorPlanningContext(
        user_text="続きを話そう",
        source_event_id="event-1",
        available_capabilities=frozenset(),
        situation={
            "active_activity_type": "conversation_with_user",
            "pending_activity_count": 1,
        },
        memory={"semantic_facts": [{"subject": "viewer.favorite", "fact": "ramen"}]},
    )

    prompt = SituationEvaluatorPromptBuilder().build(context)

    assert '"active_activity_type": "conversation_with_user"' in prompt
    assert '"pending_activity_count": 1' in prompt
    assert '"subject": "viewer.favorite"' in prompt
