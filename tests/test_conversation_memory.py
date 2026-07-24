from app.domain.activities import Activity, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicCategory, TopicHistory
from app.runtime import ActivityManager, AgentLifeService
from app.runtime.character_response_pipeline import ResponseContextBuilder


def test_short_term_memory_keeps_ordered_user_and_assistant_turns() -> None:
    memory = ShortTermMemory()

    memory.add_user_input(
        "深海魚について話そう",
        counterpart_id="local:user",
        display_name="Kei",
    )
    memory.add_speech("いいね、発光する魚の話をしよう。")
    memory.add_user_input(
        "どうして光るの？",
        counterpart_id="local:user",
        display_name="Kei",
    )

    assert memory.build_recent_conversation_summary() == (
        "- Kei: 深海魚について話そう\n"
        "- ゆら: いいね、発光する魚の話をしよう。\n"
        "- Kei: どうして光るの？"
    )


def test_agent_life_records_user_input_once_when_same_event_is_replayed() -> None:
    memory = ShortTermMemory()
    service = AgentLifeService(ActivityManager(), short_term_memory=memory)
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "覚えてる？", "source": "console"},
    )

    service.handle_event(event)
    service.handle_event(event)

    assert [item.text for item in memory.recent_conversation()] == ["覚えてる？"]
    assert service.agent_state.relationship_memory.current is not None
    assert service.agent_state.relationship_memory.current.interaction_count == 1


def test_response_context_uses_shared_conversation_and_topic_memory() -> None:
    memory = ShortTermMemory()
    memory.add_user_input("前に深海魚の話をしたね", display_name="Kei")
    memory.add_speech("発光する魚の話をしたね。")
    topics = TopicHistory()
    topics.add(category=TopicCategory.SEA_LIFE, summary="深海魚の発光について話した")
    context = ResponseContextBuilder(memory, topics).build(
        Activity(
            activity_type=ActivityType.CONVERSATION_WITH_USER,
            goal="会話を継続する",
            context={"event_payload": {"text": "続きを話そう"}},
        )
    )

    assert "Kei: 前に深海魚の話をしたね" in context.recent_conversation_summary
    assert "ゆら: 発光する魚の話をしたね。" in context.recent_conversation_summary
    assert context.recent_speech_summary == "- 発光する魚の話をしたね。"
    assert context.recent_topic_summary == "深海魚の発光について話した"
