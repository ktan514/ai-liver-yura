from __future__ import annotations

import json

import pytest

from app.adapters.prompt import CharacterPromptBuilder, ResponseValidatorPromptBuilder
from app.domain.activities import Activity, ActivityType, OngoingActivity
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
    CharacterResponse,
    Claim,
    ClaimType,
    ResponseClaim,
    ResponseContext,
)
from app.runtime.character_response_pipeline import (
    CharacterLlmService,
    CharacterResponsePipeline,
    ResponseContextBuilder,
    ResponseValidator,
)
from app.runtime.response_claim_validator import IndependentClaimExtractor

CHARACTER_PROMPT = CharacterPromptBuilder()
VALIDATION_PROMPT = ResponseValidatorPromptBuilder()


class StubRoleModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.activities: list[Activity] = []

    async def generate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.responses.pop(0)

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.responses.pop(0)


class CountingClaimExtractor(IndependentClaimExtractor):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.call_count = 0
        self._fail = fail

    def extract(self, context: ResponseContext, speech: str) -> tuple[Claim, ...]:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("extractor unavailable")
        return super().extract(context, speech)


def _activity(
    status: ActivityExecutionStatus,
    *,
    activity_type: str = "external_operation",
    operation: str = "start",
    ongoing: bool = False,
) -> Activity:
    result = ActivityExecutionResult(
        activity_type=activity_type,
        operation=operation,
        status=status,
        payload={"summary": "実行結果", "ongoing": ongoing},
    )
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="実行事実に沿って応答する",
        context={"event_payload": {"activity_execution_result": result}},
    )


def _response(speech: str, claims: tuple[ResponseClaim, ...] = ()) -> CharacterResponse:
    return CharacterResponse(speech=speech, claims=claims)


@pytest.mark.asyncio
async def test_low_initiative_greeting_does_not_expand_into_question() -> None:
    context = ResponseContext(
        user_input="こんにちは",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="挨拶に応答する",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="社会的な接触に一往復分応答する",
        speech_act="greeting",
        conversation_phase="greeting",
        initiative_level=0.15,
    )

    result = await ResponseValidator().validate(
        _activity(ActivityExecutionStatus.WAITING_INPUT),
        context,
        CharacterResponse(speech="こんにちは。今日は何を話しますか？"),
    )

    assert result.accepted is False
    assert result.reason == "response_exceeds_planned_initiative"


def test_response_context_contains_safe_structured_ongoing_activity_summary() -> None:
    ongoing = OngoingActivity(
        activity_type="game_with_user",
        goal="深海生物縛りのしりとりを続ける",
        expected_input="みから始まる言葉",
        end_condition="勝敗または停止",
        context={
            "plugin_id": "games",
            "capability": "games.shiritori",
            "plugin_session_id": "session-1",
            "game_type": "shiritori",
            "plugin_state_version": 2,
            "constraints": {"theme": "深海生物"},
            "game_state": {"used_words": ["内部状態は渡さない"]},
        },
    ).begin_turn(
        "しりとりしよう",
        "event-1",
        operation="start",
        constraints_snapshot={"theme": "深海生物"},
    )
    result = ActivityExecutionResult(
        activity_type="game_with_user",
        operation="start",
        status=ActivityExecutionStatus.WAITING_INPUT,
        payload={"summary": "最初の単語を出した"},
        constraints={"theme": "深海生物"},
    )
    activity = Activity(
        activity_type=ActivityType.PLUGIN_ACTIVITY,
        goal="ゲームの応答を表現する",
        context={
            "ongoing_activity": ongoing,
            "activity_execution_result": result,
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.ongoing_activity is not None
    assert context.ongoing_activity.ongoing_activity_id == ongoing.ongoing_activity_id
    assert context.ongoing_activity.turn_count == 1
    assert context.ongoing_activity.constraints == {"theme": "深海生物"}
    assert (
        context.ongoing_activity.plugin_context_summary["plugin_session_id"]
        == "session-1"
    )
    assert "game_state" not in context.ongoing_activity.plugin_context_summary
    assert ResponseClaim.ACTIVITY_STARTED in context.allowed_claims


def test_response_context_exposes_confirmation_target_and_forbids_execution_claims() -> (
    None
):
    result = ActivityExecutionResult(
        activity_type="confirmation",
        operation="start",
        status=ActivityExecutionStatus.WAITING_INPUT,
        payload={"summary": "開始意図を確認する"},
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="候補を確認する",
        context={
            "event_payload": {
                "activity_execution_result": result,
                "pending_confirmation": {
                    "confirmation_id": "confirmation-1",
                    "confirmation_type": "confirm_start_activity",
                    "candidate_activity_type": "shiritori",
                    "candidate_operation": "start",
                    "question": "しりとりを始める意図で合っているか確認する",
                },
            }
        },
    )

    context = ResponseContextBuilder().build(activity)

    assert context.confirmation_id == "confirmation-1"
    assert context.confirmation_candidate_activity_type == "shiritori"
    assert context.confirmation_question is not None
    assert context.allowed_claims == (ResponseClaim.CONVERSATION_ONLY,)
    assert ResponseClaim.ACTIVITY_STARTED in context.forbidden_claims


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("activity", "response", "claim_type"),
    [
        (
            _activity(ActivityExecutionStatus.WAITING_INPUT, activity_type="search"),
            _response("検索を完了したよ"),
            ClaimType.ACTIVITY_COMPLETED,
        ),
        (
            _activity(ActivityExecutionStatus.REJECTED, activity_type="stream_control"),
            _response("配信を開始したよ", (ResponseClaim.CONVERSATION_ONLY,)),
            ClaimType.ACTIVITY_STARTED,
        ),
        (
            _activity(ActivityExecutionStatus.CANCELED, activity_type="game"),
            _response("まだゲームを続けているよ"),
            ClaimType.ACTIVITY_RUNNING,
        ),
    ],
)
async def test_speech_claim_is_rejected_even_when_self_report_is_omitted_or_faked(
    activity: Activity,
    response: CharacterResponse,
    claim_type: ClaimType,
) -> None:
    context = ResponseContextBuilder().build(activity)

    result = await ResponseValidator().validate(activity, context, response)

    assert result.accepted is False
    assert claim_type in {claim.claim_type for claim in result.extracted_claims}


@pytest.mark.asyncio
async def test_preserved_ongoing_activity_cannot_be_claimed_as_completed() -> None:
    result = ActivityExecutionResult(
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.SUCCEEDED,
        payload={"summary": "進行中Activityについて会話した"},
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="進行中Activityについて会話する",
        context={
            "event_payload": {
                "activity_execution_result": result,
                "ongoing_transition": {
                    "ongoing_input_decision": "conversation_about_current",
                    "current_activity_status": "waiting",
                    "current_activity_preserved": True,
                    "current_activity_stopped": False,
                    "transition_result": "succeeded",
                },
            }
        },
    )
    context = ResponseContextBuilder().build(activity)

    validation = await ResponseValidator().validate(
        activity,
        context,
        _response("進行中の活動は終了したよ", (ResponseClaim.ACTIVITY_COMPLETED,)),
    )

    assert context.ongoing_input_decision == "conversation_about_current"
    assert context.current_activity_preserved is True
    assert validation.accepted is False
    assert "preserved_activity_claimed_stopped" in validation.claim_differences


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_reason"),
    [
        (
            _response("外部処理は成功したよ", (ResponseClaim.ACTIVITY_FAILED,)),
            "speech_positive_self_report_negative",
        ),
        (
            _response("まだ処理を実行中だよ", (ResponseClaim.ACTIVITY_COMPLETED,)),
            "speech_running_self_report_completed",
        ),
        (
            _response("結果を取得したよ"),
            "speech_execution_claim_missing_from_self_report",
        ),
        (
            _response("今日はいい天気だね", (ResponseClaim.ACTIVITY_SUCCEEDED,)),
            "self_reported_execution_claim_missing_from_speech",
        ),
    ],
)
async def test_self_reported_claims_and_speech_must_be_consistent(
    response: CharacterResponse,
    expected_reason: str,
) -> None:
    activity = _activity(ActivityExecutionStatus.SUCCEEDED, ongoing=True)
    context = ResponseContextBuilder().build(activity)

    result = await ResponseValidator().validate(activity, context, response)

    assert result.accepted is False
    assert (
        expected_reason in result.claim_differences or result.reason == expected_reason
    )


@pytest.mark.asyncio
async def test_structured_self_reported_claim_metadata_must_match_execution_fact() -> (
    None
):
    parsed = CharacterLlmService.parse(
        json.dumps(
            {
                "speech": "検索を完了したよ",
                "claims": [
                    {
                        "claim_type": "activity_completed",
                        "activity_type": "stream_control",
                        "operation": "stop",
                        "status": "failed",
                        "target": "検索",
                        "confidence": 0.99,
                        "evidence": "検索を完了したよ",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    assert parsed is not None
    activity = _activity(ActivityExecutionStatus.SUCCEEDED, activity_type="search")
    context = ResponseContextBuilder().build(activity)

    result = await ResponseValidator().validate(activity, context, parsed)

    assert result.accepted is False
    assert "self_reported_activity_type_mismatch" in result.claim_differences
    assert "self_reported_operation_mismatch" in result.claim_differences
    assert "self_reported_status_mismatch" in result.claim_differences


@pytest.mark.asyncio
async def test_validator_llm_cannot_override_deterministic_rejection() -> None:
    model = StubRoleModel(['{"accepted":true,"reason":"valid"}'])
    activity = _activity(
        ActivityExecutionStatus.REJECTED, activity_type="stream_control"
    )
    context = ResponseContextBuilder().build(activity)

    result = await ResponseValidator(model, VALIDATION_PROMPT).validate(
        activity,
        context,
        _response("配信を開始したよ", (ResponseClaim.ACTIVITY_STARTED,)),
    )

    assert result.accepted is False
    assert model.activities == []


@pytest.mark.asyncio
async def test_validator_llm_extracted_claim_is_deterministically_revalidated() -> None:
    model = StubRoleModel(
        [
            json.dumps(
                {
                    "accepted": True,
                    "reason": "valid",
                    "extracted_claims": [
                        {
                            "claim_type": "external_result_obtained",
                            "activity_type": "search",
                            "operation": "start",
                            "status": "succeeded",
                            "target": "情報",
                            "confidence": 0.95,
                            "evidence": "探していた情報が手元に届いた",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ]
    )
    activity = _activity(ActivityExecutionStatus.REJECTED, activity_type="search")
    context = ResponseContextBuilder().build(activity)

    result = await ResponseValidator(model, VALIDATION_PROMPT).validate(
        activity,
        context,
        _response("探していた情報が手元に届いたよ"),
    )

    assert result.accepted is False
    assert result.reason.startswith("claim_not_supported_by_rejected")


@pytest.mark.asyncio
async def test_deterministically_valid_response_reaches_validator_llm() -> None:
    model = StubRoleModel(['{"accepted":true,"reason":"facts_consistent"}'])
    activity = _activity(
        ActivityExecutionStatus.WAITING_INPUT, activity_type="conversation"
    )
    context = ResponseContextBuilder().build(activity)

    result = await ResponseValidator(model, VALIDATION_PROMPT).validate(
        activity,
        context,
        _response("検索の仕組みについて説明するね", (ResponseClaim.CONVERSATION_ONLY,)),
    )

    assert result.accepted is True
    assert len(model.activities) == 1
    prompt = model.activities[0].context["plugin_prompt_override"]
    assert "Speechから独立抽出済みのClaims" in prompt


@pytest.mark.asyncio
async def test_regeneration_runs_claim_extractor_again_and_adopts_corrected_response() -> (
    None
):
    character = StubRoleModel(
        [
            '{"speech":"配信を開始したよ","claims":[]}',
            '{"speech":"今は開始できないんだ","claims":["execution_unavailable"]}',
        ]
    )
    extractor = CountingClaimExtractor()
    pipeline = CharacterResponsePipeline(
        ResponseContextBuilder(),
        CharacterLlmService(character, CHARACTER_PROMPT),
        ResponseValidator(claim_extractor=extractor),
    )

    response = await pipeline.generate(
        _activity(ActivityExecutionStatus.REJECTED, activity_type="stream_control")
    )

    assert response.speech == "今は開始できないんだ"
    assert extractor.call_count == 2
    assert len(character.activities) == 2
    correction = character.activities[1].context["plugin_prompt_override"]
    assert "invalid_speech_claims" in correction
    assert "未実行処理を実行済みと表現しない" in correction


@pytest.mark.asyncio
async def test_second_invalid_response_is_replaced_with_safe_fallback() -> None:
    character = StubRoleModel(
        [
            '{"speech":"配信を開始したよ","claims":[]}',
            '{"speech":"やっぱり開始したよ","claims":[]}',
        ]
    )
    pipeline = CharacterResponsePipeline(
        ResponseContextBuilder(),
        CharacterLlmService(character, CHARACTER_PROMPT),
        ResponseValidator(),
    )

    response = await pipeline.generate(
        _activity(ActivityExecutionStatus.REJECTED, activity_type="stream_control")
    )

    assert len(character.activities) == 2
    assert response.claims == (ResponseClaim.EXECUTION_UNAVAILABLE,)
    assert "できない" in response.speech


@pytest.mark.asyncio
async def test_claim_extractor_failure_uses_safe_fallback_after_one_regeneration() -> (
    None
):
    character = StubRoleModel(
        [
            json.dumps({"speech": "普通に話すね", "claims": ["conversation_only"]}),
            json.dumps({"speech": "もう一度話すね", "claims": ["conversation_only"]}),
        ]
    )
    extractor = CountingClaimExtractor(fail=True)
    pipeline = CharacterResponsePipeline(
        ResponseContextBuilder(),
        CharacterLlmService(character, CHARACTER_PROMPT),
        ResponseValidator(claim_extractor=extractor),
    )

    response = await pipeline.generate(
        _activity(ActivityExecutionStatus.REJECTED, activity_type="search")
    )

    assert extractor.call_count == 2
    assert response.claims == (ResponseClaim.EXECUTION_UNAVAILABLE,)


@pytest.mark.asyncio
async def test_ordinary_conversation_does_not_require_external_success_result() -> None:
    activity = _activity(
        ActivityExecutionStatus.WAITING_INPUT, activity_type="conversation"
    )
    context = ResponseContextBuilder().build(activity)

    result = await ResponseValidator().validate(
        activity,
        context,
        _response(
            "しりとりは、最後の文字をつなぐ言葉遊びだよ",
            (ResponseClaim.CONVERSATION_ONLY,),
        ),
    )

    assert result.accepted is True
