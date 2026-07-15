from app.domain.actions import ActionPlan, ActionPlanGroup, ActionResource, ActionType
from app.runtime.activity_result_builder import build_activity_result


def test_build_activity_result_preserves_speech_and_other_action_details() -> None:
    group = ActionPlanGroup(
        action_plans=[
            ActionPlan(action_type=ActionType.SPEAK, text="こんにちは"),
            ActionPlan(action_type=ActionType.CHANGE_EXPRESSION, text="smile"),
        ]
    )

    result = build_activity_result(group)

    assert result.result_type == "speech_output"
    assert result.summary == "こんにちは"
    assert result.data["output_unit_id"] == group.group_id
    assert [action["action_type"] for action in result.data["actions"]] == [
        "speak",
        "change_expression",
    ]


def test_build_activity_result_supports_non_speech_activity() -> None:
    group = ActionPlanGroup(
        action_plans=[
            ActionPlan(
                action_type=ActionType.OBSERVE,
                required_resources={ActionResource.EYES},
            )
        ]
    )

    result = build_activity_result(group)

    assert result.result_type == "action_output"
    assert result.summary == "observe"
    assert result.data["actions"][0]["action_type"] == "observe"
