from __future__ import annotations

import json

import pytest

from app.config.app_config import load_app_config
from app.domain.activities import Activity, ActivityType
from app.domain.activity_turn_result import CharacterGenerationStatus
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorDecision,
    BehaviorPlanningContext,
)
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
    ResponseClaim,
)
from app.runtime.activity_registry import ActivityRegistry
from app.runtime.behavior_planner import BehaviorPlanner
from app.runtime.character_response_pipeline import (
    CharacterLlmService,
    CharacterResponsePipeline,
    ResponseContextBuilder,
    ResponseValidator,
)
from app.runtime.situation_evaluator import SituationEvaluator


class StubRoleModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.activities: list[Activity] = []

    async def evaluate(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.responses.pop(0)

    async def generate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        value = self.responses.pop(0)
        if value == "RAISE":
            raise RuntimeError("character unavailable")
        return value

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.responses.pop(0)


class StubResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return "{}"


def _semantic(activity_type: str, operation: str = "start") -> str:
    return json.dumps(
        {
            "decision": "start_activity",
            "activity_type": activity_type,
            "operation": operation,
            "goal": f"{activity_type}を実行する",
            "constraints": {"query": "深海"},
            "speech_act": "request",
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "knowledge_question": False,
            "confidence": 0.96,
            "reason": "semantic_match",
        },
        ensure_ascii=False,
    )


def _definitions() -> tuple[ActivityDefinition, ...]:
    return (
        ActivityDefinition(
            activity_type="search",
            display_name="検索",
            required_capability="tools.search",
            provider_plugin_id="search_plugin",
            description="外部情報を検索する",
            supported_operations=(ActivityOperation.START,),
            semantic_descriptions=("情報を探して結果を返す",),
            constraints_schema={"query": "string"},
        ),
        ActivityDefinition(
            activity_type="stream_control",
            display_name="配信制御",
            required_capability="stream.control",
            provider_plugin_id="stream_plugin",
            description="配信状態を操作する",
            supported_operations=(ActivityOperation.START, ActivityOperation.STOP),
            semantic_descriptions=("配信を開始または停止する",),
            constraints_schema={"query": "string"},
        ),
    )


@pytest.mark.asyncio
async def test_situation_evaluator_is_generic_and_does_not_select_capability() -> None:
    model = StubRoleModel([_semantic("search")])
    context = BehaviorPlanningContext(
        user_text="深海の最新情報を探して",
        source_event_id="event-1",
        available_capabilities=frozenset(),
        activity_definitions=_definitions(),
    )

    analysis = await SituationEvaluator(model).evaluate(context)

    assert analysis.activity_candidate == "search"
    assert analysis.constraints == {"query": "深海"}
    assert not hasattr(analysis, "required_capability")
    assert not hasattr(analysis, "provider_plugin_id")
    prompt = model.activities[0].context["plugin_prompt_override"]
    assert "search" in prompt
    assert "stream_control" in prompt
    assert "Capabilityの利用可否" in prompt


@pytest.mark.asyncio
async def test_behavior_planner_adds_definition_owned_execution_details() -> None:
    context = BehaviorPlanningContext(
        user_text="深海の最新情報を探して",
        source_event_id="event-1",
        available_capabilities=frozenset({"tools.search"}),
        activity_definitions=_definitions(),
    )
    analysis = await SituationEvaluator(StubRoleModel([_semantic("search")])).evaluate(context)

    plan = await BehaviorPlanner(StubResponseGenerator()).plan(context, analysis)

    assert plan.decision == BehaviorDecision.START_ACTIVITY
    assert plan.required_capability == "tools.search"
    assert plan.provider_plugin_id == "search_plugin"


def test_activity_registry_rejects_duplicate_generic_definitions() -> None:
    definition = _definitions()[0]
    registry = ActivityRegistry((definition, definition))

    with pytest.raises(ValueError, match="重複"):
        registry.list_definitions()


def test_response_context_is_built_from_rejected_execution_fact() -> None:
    result = ActivityExecutionResult(
        activity_type="search",
        operation="start",
        status=ActivityExecutionStatus.REJECTED,
        capability="tools.search",
        provider="search_plugin",
        failure_reason="capability_unavailable",
        payload={"summary": "検索は開始されなかった"},
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="拒否結果を伝える",
        context={
            "event_payload": {
                "text": "検索して",
                "activity_execution_result": result,
            }
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.status == ActivityExecutionStatus.REJECTED
    assert ResponseClaim.EXECUTION_UNAVAILABLE in context.allowed_claims
    assert ResponseClaim.ACTIVITY_STARTED in context.forbidden_claims
    assert not hasattr(context, "capability")
    assert not hasattr(context, "provider")


@pytest.mark.asyncio
async def test_validator_rejects_fact_conflict_without_activity_specific_words() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="拒否を伝える",
        context={
            "event_payload": {
                "activity_execution_result": ActivityExecutionResult(
                    activity_type="stream_control",
                    operation="start",
                    status=ActivityExecutionStatus.REJECTED,
                )
            }
        },
    )
    context = ResponseContextBuilder().build(activity)
    response = CharacterLlmService.parse('{"speech":"始めたよ","claims":["activity_started"]}')
    assert response is not None

    validation = await ResponseValidator().validate(activity, context, response)

    assert validation.accepted is False
    assert validation.invalid_claims == (ResponseClaim.ACTIVITY_STARTED,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "claim"),
    [
        (ActivityExecutionStatus.FAILED, ResponseClaim.ACTIVITY_SUCCEEDED),
        (ActivityExecutionStatus.CANCELED, ResponseClaim.ACTIVITY_CONTINUES),
    ],
)
async def test_validator_rejects_status_conflicts_generically(
    status: ActivityExecutionStatus, claim: ResponseClaim
) -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="結果を伝える",
        context={
            "event_payload": {
                "activity_execution_result": ActivityExecutionResult(
                    activity_type="external_operation",
                    operation="start",
                    status=status,
                )
            }
        },
    )
    context = ResponseContextBuilder().build(activity)
    response = CharacterLlmService.parse(
        json.dumps({"speech": "完了したよ", "claims": [claim.value]})
    )
    assert response is not None

    validation = await ResponseValidator().validate(activity, context, response)

    assert validation.accepted is False
    assert claim in validation.invalid_claims


@pytest.mark.asyncio
async def test_invalid_character_response_is_regenerated_once_then_adopted() -> None:
    character = StubRoleModel(
        [
            '{"speech":"開始したよ","claims":["activity_started"]}',
            '{"speech":"今はできないんだ","claims":["execution_unavailable"]}',
        ]
    )
    pipeline = CharacterResponsePipeline(
        ResponseContextBuilder(), CharacterLlmService(character), ResponseValidator()
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="拒否を伝える",
        context={"event_payload": {"execution_request_unmatched": True}},
    )

    response, generation_result = await pipeline.generate_with_result(activity)

    assert response.speech == "今はできないんだ"
    assert generation_result.status == CharacterGenerationStatus.VALIDATED
    assert generation_result.attempts == 2
    assert len(character.activities) == 2
    assert "前回応答の修正理由" in character.activities[1].context["plugin_prompt_override"]


@pytest.mark.asyncio
async def test_character_failure_uses_safe_fact_compatible_fallback() -> None:
    pipeline = CharacterResponsePipeline(
        ResponseContextBuilder(),
        CharacterLlmService(StubRoleModel(["RAISE"])),
        ResponseValidator(),
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="拒否を伝える",
        context={"event_payload": {"execution_request_unmatched": True}},
    )

    response, generation_result = await pipeline.generate_with_result(activity)

    assert response.claims == (ResponseClaim.EXECUTION_UNAVAILABLE,)
    assert "できない" in response.speech
    assert generation_result.status == CharacterGenerationStatus.FALLBACK_USED
    assert generation_result.error is not None


@pytest.mark.asyncio
async def test_validator_failure_uses_safe_response_after_single_regeneration() -> None:
    character = StubRoleModel(
        [
            '{"speech":"今はできない","claims":["execution_unavailable"]}',
            '{"speech":"まだできない","claims":["execution_unavailable"]}',
        ]
    )
    validator_model = StubRoleModel(["not-json", "not-json"])
    pipeline = CharacterResponsePipeline(
        ResponseContextBuilder(),
        CharacterLlmService(character),
        ResponseValidator(validator_model),
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="拒否を伝える",
        context={"event_payload": {"execution_request_unmatched": True}},
    )

    response = await pipeline.generate(activity)

    assert len(character.activities) == 2
    assert response.speech == "今はそれを一緒にできないんだ。別のお話をしよう。"


def test_llm_roles_are_explicit_and_separately_configured() -> None:
    roles = load_app_config().llm_roles

    assert roles.situation_evaluator.temperature < roles.character.temperature
    assert roles.response_validator.temperature == 0.0
    assert roles.situation_evaluator.model
    assert roles.character.model
    assert roles.response_validator.model
