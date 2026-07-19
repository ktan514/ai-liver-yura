from __future__ import annotations

import pytest

from app.domain.actions import ActionResource, ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.activity_turn_result import (
    CharacterGenerationResult,
    CharacterGenerationStatus,
)
from app.domain.character_response import (
    CharacterResponse,
    ReactionPlan,
    ReactionSegment,
    VoiceIntent,
)
from app.runtime.action_planner import ActionPlanner


class FakeResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return f"generated: {activity.goal}"


class FailingResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        raise RuntimeError("provider unavailable")


class ForbiddenAutonomousResponseGenerator:
    def __init__(self) -> None:
        self.call_count = 0

    async def generate_response(self, activity: Activity) -> str:
        self.call_count += 1
        raise AssertionError("自律本文を旧ResponseGeneratorで生成してはいけません。")


class FakeCharacterResponsePipeline:
    def __init__(self) -> None:
        self.activities: list[Activity] = []

    async def generate_with_result(
        self, activity: Activity
    ) -> tuple[CharacterResponse, CharacterGenerationResult]:
        self.activities.append(activity)
        return (
            CharacterResponse(
                speech="Characterが生成した自律発話",
                expression="happy",
                voice_intent=VoiceIntent(style="bright"),
            ),
            CharacterGenerationResult(
                status=CharacterGenerationStatus.VALIDATED,
                activity_turn_id=activity.activity_id,
                source_event_id=activity.source_event_id,
                adopted_text="Characterが生成した自律発話",
            ),
        )


class SegmentedCharacterResponsePipeline(FakeCharacterResponsePipeline):
    async def generate_with_result(
        self, activity: Activity
    ) -> tuple[CharacterResponse, CharacterGenerationResult]:
        response = CharacterResponse(
            speech="驚いたでも安心した",
            reaction_plan=ReactionPlan(
                (
                    ReactionSegment(
                        "驚いた",
                        expression="surprised",
                        gesture="lean_back",
                        voice_intent=VoiceIntent("startled"),
                        pause_after_seconds=0.2,
                    ),
                    ReactionSegment(
                        "でも安心した",
                        expression="soft_smile",
                        voice_intent=VoiceIntent("warm"),
                    ),
                )
            ),
        )
        return response, CharacterGenerationResult(
            status=CharacterGenerationStatus.VALIDATED,
            activity_turn_id=activity.activity_id,
            adopted_text=response.speech,
        )


@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_conversation() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザー入力に応答する",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert {plan.output_unit_id for plan in action_plan_group.action_plans} == {
        action_plan_group.group_id
    }
    assert action_plan_group.output_priority == 100
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert action_plan_group.action_plans[0].text == "generated: ユーザー入力に応答する"
    assert action_plan_group.action_plans[0].required_resources == {
        ActionResource.MOUTH
    }
    assert action_plan_group.action_plans[0].metadata["voice_intent"] == VoiceIntent()
    assert action_plan_group.action_plans[1].text == "generated: ユーザー入力に応答する"
    assert action_plan_group.action_plans[1].required_resources == {
        ActionResource.SUBTITLE
    }
    assert action_plan_group.action_plans[2].text == "smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


@pytest.mark.asyncio
async def test_action_planner_expands_reaction_segments_without_engine_parameters() -> (
    None
):
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="感情の変化を表現する",
    )
    planner = ActionPlanner(
        response_generator=FakeResponseGenerator(),
        character_response_pipeline=SegmentedCharacterResponsePipeline(),
    )

    group = await planner.plan(activity)
    speaks = [
        plan for plan in group.action_plans if plan.action_type == ActionType.SPEAK
    ]

    assert [plan.text for plan in speaks] == ["驚いた", "でも安心した"]
    assert speaks[0].metadata["voice_intent"] == VoiceIntent("startled")
    assert speaks[0].metadata["pause_after_seconds"] == 0.2
    assert [plan.metadata["reaction_segment_index"] for plan in speaks] == [0, 1]


@pytest.mark.asyncio
async def test_action_planner_uses_safe_fallback_only_after_generation_failure() -> (
    None
):
    fallback = "今はそれを一緒にできないんだ。別のお話をしよう。"
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="実行できない要求へ自然に応答する",
        context={"event_payload": {"safe_conversation_fallback": fallback}},
    )
    planner = ActionPlanner(response_generator=FailingResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.action_plans[0].text == fallback


# Additional tests for startup, stream opening, and stream closing greetings
@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_startup_reaction() -> None:
    activity = Activity(
        activity_type=ActivityType.STARTUP_REACTION,
        goal="起動直後の状況に反応する",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert action_plan_group.output_priority == 50
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert (
        action_plan_group.action_plans[0].text == "generated: 起動直後の状況に反応する"
    )
    assert action_plan_group.action_plans[0].required_resources == {
        ActionResource.MOUTH
    }
    assert (
        action_plan_group.action_plans[1].text == "generated: 起動直後の状況に反応する"
    )
    assert action_plan_group.action_plans[1].required_resources == {
        ActionResource.SUBTITLE
    }
    assert action_plan_group.action_plans[2].text == "smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_stream_opening_greeting() -> (
    None
):
    activity = Activity(
        activity_type=ActivityType.STREAM_OPENING_GREETING,
        goal="配信開始時のあいさつをする",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert (
        action_plan_group.action_plans[0].text
        == "generated: 配信開始時のあいさつをする"
    )
    assert action_plan_group.action_plans[0].required_resources == {
        ActionResource.MOUTH
    }
    assert (
        action_plan_group.action_plans[1].text
        == "generated: 配信開始時のあいさつをする"
    )
    assert action_plan_group.action_plans[1].required_resources == {
        ActionResource.SUBTITLE
    }
    assert action_plan_group.action_plans[2].text == "smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


@pytest.mark.asyncio
async def test_action_planner_uses_response_generator_for_stream_closing_greeting() -> (
    None
):
    activity = Activity(
        activity_type=ActivityType.STREAM_CLOSING_GREETING,
        goal="配信終了前のあいさつをする",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert (
        action_plan_group.action_plans[0].text
        == "generated: 配信終了前のあいさつをする"
    )
    assert action_plan_group.action_plans[0].required_resources == {
        ActionResource.MOUTH
    }
    assert (
        action_plan_group.action_plans[1].text
        == "generated: 配信終了前のあいさつをする"
    )
    assert action_plan_group.action_plans[1].required_resources == {
        ActionResource.SUBTITLE
    }
    assert action_plan_group.action_plans[2].text == "smile"
    assert action_plan_group.action_plans[2].required_resources == {ActionResource.FACE}


@pytest.mark.asyncio
async def test_action_planner_uses_character_pipeline_for_autonomous_talk() -> None:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="自律的に話題を出して話す",
    )
    response_generator = ForbiddenAutonomousResponseGenerator()
    character_pipeline = FakeCharacterResponsePipeline()
    planner = ActionPlanner(
        response_generator=response_generator,
        character_response_pipeline=character_pipeline,  # type: ignore[arg-type]
    )

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert action_plan_group.output_priority == 10
    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert action_plan_group.action_plans[0].text == "Characterが生成した自律発話"
    assert action_plan_group.action_plans[0].required_resources == {
        ActionResource.MOUTH
    }
    assert action_plan_group.action_plans[0].metadata["voice_intent"] == VoiceIntent(
        style="bright"
    )
    assert action_plan_group.action_plans[1].text == "Characterが生成した自律発話"
    assert action_plan_group.action_plans[1].required_resources == {
        ActionResource.SUBTITLE
    }
    assert action_plan_group.action_plans[2].text == "happy"
    assert response_generator.call_count == 0
    assert character_pipeline.activities == [activity]


@pytest.mark.asyncio
async def test_action_planner_uses_existing_output_path_for_plugin_activity() -> None:
    activity = Activity(
        activity_type=ActivityType.PLUGIN_ACTIVITY,
        goal="Plugin状態を表現する",
        context={"plugin_session_id": "session-1", "plugin_id": "fake"},
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert [plan.action_type for plan in action_plan_group.action_plans] == [
        ActionType.SPEAK,
        ActionType.UPDATE_SUBTITLE,
        ActionType.CHANGE_EXPRESSION,
    ]
    assert action_plan_group.action_plans[0].text == "generated: Plugin状態を表現する"
    assert action_plan_group.output_priority == 100


@pytest.mark.asyncio
async def test_action_planner_returns_observe_plan_for_other_activity() -> None:
    activity = Activity(
        activity_type=ActivityType.IDLE_OBSERVATION,
        goal="状態を観察する",
    )
    planner = ActionPlanner(response_generator=FakeResponseGenerator())

    action_plan_group = await planner.plan(activity)

    assert action_plan_group.source_activity_id == activity.activity_id
    assert len(action_plan_group.action_plans) == 1
    assert action_plan_group.action_plans[0].action_type == ActionType.OBSERVE
    assert action_plan_group.action_plans[0].required_resources == {ActionResource.EYES}
