from datetime import datetime, timedelta, timezone

from app.domain.conversation_flow import (
    ConversationFloorState,
    ConversationFlowState,
    ConversationOrigin,
    SpeechPurpose,
    UserResponseKind,
)
from app.runtime.conversation_flow_controller import (
    ConversationFlowController,
    ConversationTurnPolicy,
)


def test_response_returns_floor_and_blocks_immediate_autonomous_talk() -> None:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    controller = ConversationFlowController()

    controller.begin_response()
    controller.record_output(
        "それは気持ちよさそうだね。",
        SpeechPurpose.EMPATHIZE,
        topic="海",
        now=now,
    )

    assert controller.state.floor_state == ConversationFloorState.YIELDING_TO_USER
    assert not controller.can_start_autonomous_talk(now + timedelta(seconds=10))
    assert controller.can_start_autonomous_talk(now + timedelta(seconds=31))


def test_silence_is_not_recorded_as_user_interest() -> None:
    controller = ConversationFlowController()
    controller.record_output("少し落ち着くね。", SpeechPurpose.SHARE_REACTION)

    assert controller.state.user_response_observed is False
    assert controller.state.user_response_kind == UserResponseKind.NONE


def test_topic_change_resets_same_topic_turns() -> None:
    state = ConversationFlowState(
        current_topic="海",
        topic_origin=ConversationOrigin.AUTONOMOUS,
        same_topic_turns=2,
    )
    controller = ConversationFlowController(state=state)

    controller.on_user_input(UserResponseKind.TOPIC_CHANGE, topic="山")

    assert controller.state.current_topic == "山"
    assert controller.state.same_topic_turns == 0
    assert controller.state.topic_origin == ConversationOrigin.USER


def test_topic_origin_changes_autonomous_turn_limit() -> None:
    policy = ConversationTurnPolicy(
        user_topic_max_autonomous_turns=1,
        autonomous_topic_max_turns=2,
        default_yield_seconds=0,
    )
    state = ConversationFlowState(
        floor_state=ConversationFloorState.IDLE,
        topic_origin=ConversationOrigin.USER,
        same_topic_turns=1,
    )
    controller = ConversationFlowController(state=state, policy=policy)

    assert not controller.can_start_autonomous_talk()

    controller.state.topic_origin = ConversationOrigin.TASK
    assert controller.can_start_autonomous_talk()


def test_open_prompt_remains_available_until_resolved() -> None:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    controller = ConversationFlowController(
        policy=ConversationTurnPolicy(open_prompt_ttl_seconds=60)
    )
    prompt = controller.register_open_prompt("海と山ならどちらが好き？", now=now)

    assert controller.state.active_open_prompts(now + timedelta(seconds=30)) == [prompt]
    assert controller.resolve_open_prompt(prompt.prompt_id) == prompt
    assert controller.state.active_open_prompts(now + timedelta(seconds=30)) == []
