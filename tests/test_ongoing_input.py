from __future__ import annotations

import pytest

from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorDecision,
    BehaviorPlanningContext,
    OngoingActivityPlanningContext,
    OngoingInputDecision,
    SituationAnalysis,
)
from app.runtime.behavior_planner import ActivityPlanValidator
from app.runtime.ongoing_input import (
    OngoingActivityTransitionPolicy,
    OngoingInputInterpreter,
)


def _definition(activity_type: str, capability: str) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability=capability,
        provider_plugin_id=f"{activity_type}_plugin",
        supported_operations=(
            ActivityOperation.START,
            ActivityOperation.CONTINUE,
            ActivityOperation.STOP,
        ),
    )


def _context() -> BehaviorPlanningContext:
    current = _definition("word_game", "games.word_game")
    other = _definition("quiz", "games.quiz")
    return BehaviorPlanningContext(
        user_text="input",
        source_event_id="event-1",
        available_capabilities=frozenset({"games.word_game", "games.quiz"}),
        activity_definitions=(current, other),
        active_activity_definition=current,
        ongoing_activity_type="word_game",
        ongoing_activity=OngoingActivityPlanningContext(
            ongoing_activity_id="ongoing-1",
            activity_type="word_game",
            status="waiting",
            goal="言葉を交互につなぐ",
            constraints={"theme": "海"},
            expected_input="前の語尾から始まる単語",
            turn_count=2,
            current_operation="continue",
            plugin_state_summary={"plugin_id": "word_game_plugin"},
            recent_turns=({"sequence": 2, "operation": "continue"},),
        ),
    )


@pytest.mark.parametrize(
    ("analysis", "expected"),
    [
        (
            SituationAnalysis(
                "word_game", ActivityOperation.CONTINUE, "継続する", confidence=0.99
            ),
            OngoingInputDecision.CONTINUE_CURRENT,
        ),
        (
            SituationAnalysis(
                "word_game", ActivityOperation.STOP, "停止する", confidence=0.99
            ),
            OngoingInputDecision.STOP_CURRENT,
        ),
        (
            SituationAnalysis(
                None,
                ActivityOperation.DISCUSS,
                "現在の活動について話す",
                hypothetical=True,
                confidence=0.99,
            ),
            OngoingInputDecision.CONVERSATION_ABOUT_CURRENT,
        ),
        (
            SituationAnalysis(
                None,
                ActivityOperation.DISCUSS,
                "別の話をする",
                ongoing_input_decision=OngoingInputDecision.CONVERSATION_UNRELATED,
                confidence=0.99,
            ),
            OngoingInputDecision.CONVERSATION_UNRELATED,
        ),
        (
            SituationAnalysis(
                None,
                None,
                "停止しない",
                negated=True,
                confidence=0.99,
            ),
            OngoingInputDecision.CONTINUE_CURRENT,
        ),
        (
            SituationAnalysis(None, None, "曖昧", confidence=0.3),
            OngoingInputDecision.ASK_CONFIRMATION,
        ),
    ],
)
def test_ongoing_input_interpreter_is_activity_agnostic(
    analysis: SituationAnalysis,
    expected: OngoingInputDecision,
) -> None:
    interpretation = OngoingInputInterpreter().interpret(_context(), analysis)

    assert interpretation is not None
    assert interpretation.decision == expected


def test_starting_other_activity_requires_confirmation_and_preserves_current() -> None:
    context = _context()
    analysis = SituationAnalysis(
        "quiz",
        ActivityOperation.START,
        "クイズを開始する",
        confidence=0.99,
    )
    interpretation = OngoingInputInterpreter().interpret(context, analysis)
    assert interpretation is not None

    plan = OngoingActivityTransitionPolicy().plan(context, analysis, interpretation)

    assert plan.decision == BehaviorDecision.ASK_CONFIRMATION
    assert plan.ongoing_input_decision == OngoingInputDecision.START_OTHER_ACTIVITY
    assert plan.current_activity_preserved is True
    assert plan.requested_new_activity == "quiz"


def test_explicit_switch_builds_stop_then_start_plan_without_preserving_current() -> None:
    context = _context()
    analysis = SituationAnalysis(
        "quiz",
        ActivityOperation.START,
        "現在のゲームを終了してクイズを開始する",
        confidence=0.99,
        ongoing_input_decision=OngoingInputDecision.SWITCH_ACTIVITY,
    )
    interpretation = OngoingInputInterpreter().interpret(context, analysis)
    assert interpretation is not None

    plan = OngoingActivityTransitionPolicy().plan(context, analysis, interpretation)

    assert plan.decision == BehaviorDecision.SWITCH_ACTIVITY
    assert plan.activity_type == "quiz"
    assert plan.required_capability == "games.quiz"
    assert plan.current_activity_type == "word_game"
    assert plan.current_activity_capability == "games.word_game"
    assert plan.current_activity_preserved is False


def test_switch_target_capability_rejection_does_not_authorize_current_stop() -> None:
    context = _context()
    analysis = SituationAnalysis(
        "quiz",
        ActivityOperation.START,
        "現在のゲームを終了してクイズを開始する",
        confidence=0.99,
        ongoing_input_decision=OngoingInputDecision.SWITCH_ACTIVITY,
    )
    interpretation = OngoingInputInterpreter().interpret(context, analysis)
    assert interpretation is not None
    plan = OngoingActivityTransitionPolicy().plan(context, analysis, interpretation)

    evaluation = ActivityPlanValidator(
        lambda capability, plugin_id: capability != "games.quiz",
        lambda: context.activity_definitions,
    ).validate(plan)

    assert evaluation.accepted is False
    assert plan.current_activity_stopped is False
    assert plan.current_activity_type == "word_game"
