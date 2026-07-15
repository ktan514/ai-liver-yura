from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.activities import Activity
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
    OngoingActivityPlanningContext,
    SpeechAct,
)
from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner
from app.utils.trace import TraceLogger


class StubResponseGenerator:
    def __init__(self, response: str = "{}") -> None:
        self.response = response
        self.activities: list[Activity] = []

    async def generate_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.response


def _context(
    text: str,
    *,
    available: frozenset[str] = frozenset(),
    definitions: tuple[ActivityDefinition, ...] = (),
) -> BehaviorPlanningContext:
    return BehaviorPlanningContext(
        user_text=text,
        source_event_id="event-1",
        available_capabilities=available,
        activity_definitions=definitions,
    )


def _shiritori_definition() -> ActivityDefinition:
    return ActivityDefinition(
        activity_type="shiritori",
        display_name="しりとり",
        required_capability="games.shiritori",
        provider_plugin_id="games",
        start_markers=("しりとりしよう",),
        description="ユーザーと交互に単語の末尾をつなげる継続ゲーム",
        supported_operations=(
            ActivityOperation.START,
            ActivityOperation.CONTINUE,
            ActivityOperation.STOP,
        ),
        semantic_descriptions=("言葉を交互につなぐ遊び",),
    )


def _semantic_json(
    *,
    decision: str = "start_activity",
    activity_type: str = "shiritori",
    operation: str | None = "start",
    goal: str = "しりとりを開始する",
    constraints: dict[str, object] | None = None,
    speech_act: str = "proposal",
    negated: bool = False,
    hypothetical: bool = False,
    past_reference: bool = False,
    knowledge_question: bool = False,
    confidence: float = 0.95,
    reason: str = "semantic_match",
) -> str:
    return json.dumps(
        {
            "decision": decision,
            "activity_type": activity_type,
            "operation": operation,
            "goal": goal,
            "constraints": constraints or {},
            "speech_act": speech_act,
            "negated": negated,
            "hypothetical": hypothetical,
            "past_reference": past_reference,
            "knowledge_question": knowledge_question,
            "confidence": confidence,
            "reason": reason,
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_normal_chat_selects_conversation_activity() -> None:
    planner = BehaviorPlanner(StubResponseGenerator())

    plan = await planner.plan(_context("今日はいい天気だね"))

    assert plan.decision == BehaviorDecision.CONVERSATION
    assert plan.activity_type == "conversation"
    assert plan.required_capability is None


@pytest.mark.asyncio
async def test_shiritori_request_selects_structured_activity_plan() -> None:
    planner = BehaviorPlanner(StubResponseGenerator())

    plan = await planner.plan(_context("しりとりしよう", definitions=(_shiritori_definition(),)))

    assert plan.decision == BehaviorDecision.START_ACTIVITY
    assert plan.activity_type == "shiritori"
    assert plan.required_capability == "games.shiritori"
    assert plan.provider_plugin_id == "games"


def test_capability_validator_returns_normal_rejection_result() -> None:
    plan = ActivityPlan(
        decision=BehaviorDecision.START_ACTIVITY,
        activity_type="shiritori",
        goal="しりとりを開始する",
        required_capability="games.shiritori",
        provider_plugin_id="games",
        operation=ActivityOperation.START,
    )
    validator = ActivityPlanValidator(lambda capability, plugin_id: False)

    evaluation = validator.validate(plan)

    assert evaluation.accepted is False
    assert evaluation.fallback_required is True
    assert evaluation.result.result_type == "activity_plan_rejected"
    assert evaluation.result.succeeded is False


def test_validator_never_executes_start_plan_without_capability() -> None:
    plan = ActivityPlan(
        decision=BehaviorDecision.START_ACTIVITY,
        activity_type="invented",
        goal="未知のActivityを開始する",
        operation=ActivityOperation.START,
    )

    evaluation = ActivityPlanValidator(lambda capability, plugin_id: True).validate(plan)

    assert evaluation.accepted is False
    assert evaluation.result.data["reason"] == "required_capability_missing"


def test_unknown_llm_activity_is_rejected_by_schema_matching() -> None:
    planner = BehaviorPlanner(StubResponseGenerator())
    plan = planner.parse_llm_plan(
        _semantic_json(activity_type="invented", reason="llm_selected"),
        definitions=(_shiritori_definition(),),
    )

    assert plan is None


@pytest.mark.asyncio
async def test_active_activity_selects_continuation() -> None:
    definition = _shiritori_definition()
    context = BehaviorPlanningContext(
        user_text="ごりら",
        source_event_id="event-2",
        available_capabilities=frozenset({"games.shiritori"}),
        activity_definitions=(definition,),
        active_activity_definition=definition,
        ongoing_activity_type="shiritori",
    )

    plan = await BehaviorPlanner(
        StubResponseGenerator(
            _semantic_json(
                decision="continue_activity",
                operation="continue",
                goal="しりとりを継続する",
            )
        )
    ).plan(context)

    assert plan.decision == BehaviorDecision.CONTINUE_ACTIVITY
    assert plan.activity_type == "shiritori"


@pytest.mark.asyncio
async def test_active_activity_accepts_plugin_owned_stop_matcher() -> None:
    definition = ActivityDefinition(
        activity_type="generic_activity",
        display_name="汎用Activity",
        required_capability="plugin.generic",
        provider_plugin_id="plugin",
        stop_markers=("活動をやめよう",),
        supported_operations=(ActivityOperation.CONTINUE, ActivityOperation.STOP),
    )
    context = BehaviorPlanningContext(
        user_text="活動をやめよう",
        source_event_id="event-stop",
        available_capabilities=frozenset({"plugin.generic"}),
        active_activity_definition=definition,
    )

    plan = await BehaviorPlanner(StubResponseGenerator()).plan(context)

    assert plan.decision == BehaviorDecision.CONTINUE_ACTIVITY
    assert plan.operation == ActivityOperation.STOP
    assert plan.required_capability == "plugin.generic"


@pytest.mark.asyncio
async def test_situation_evaluator_receives_safe_ongoing_activity_context() -> None:
    definition = _shiritori_definition()
    generator = StubResponseGenerator(
        _semantic_json(
            decision="continue_activity",
            operation="continue",
            goal="次の単語を処理する",
        )
    )
    context = BehaviorPlanningContext(
        user_text="みみず",
        source_event_id="event-ongoing",
        available_capabilities=frozenset({"games.shiritori"}),
        activity_definitions=(definition,),
        active_activity_definition=definition,
        ongoing_activity_type="shiritori",
        ongoing_activity=OngoingActivityPlanningContext(
            ongoing_activity_id="ongoing-1",
            activity_type="shiritori",
            status="waiting",
            goal="海の生き物縛りでしりとりを続ける",
            constraints={"theme": "海の生き物"},
            expected_input="みから始まる単語",
            turn_count=2,
            current_operation="continue",
            plugin_state_summary={"game_session_id": "session-1"},
            recent_turns=({"sequence": 2, "operation": "continue"},),
        ),
    )

    plan = await BehaviorPlanner(generator).plan(context)

    assert plan.decision == BehaviorDecision.CONTINUE_ACTIVITY
    assert len(generator.activities) == 1
    prompt = str(generator.activities[0].context["plugin_prompt_override"])
    assert "ongoing-1" in prompt
    assert "みから始まる単語" in prompt
    assert "session-1" in prompt
    assert "recent_turns" in prompt


@pytest.mark.asyncio
async def test_behavior_llm_returns_only_structured_activity_plan() -> None:
    response = _semantic_json(
        activity_type="first",
        goal="活動を開始する",
        constraints={"theme": "海"},
        confidence=0.9,
        reason="selected",
    )
    generator = StubResponseGenerator(response)
    planner = BehaviorPlanner(generator)
    first = ActivityDefinition("first", "第一候補", "plugin.first", "plugin", ("何かしよう",))
    second = ActivityDefinition("second", "第二候補", "plugin.second", "plugin", ("何かしよう",))

    plan = await planner.plan(
        _context(
            "何かしよう",
            available=frozenset({"plugin.first", "plugin.second"}),
            definitions=(first, second),
        )
    )

    assert plan.planner_type == "llm"
    assert plan.activity_type == "first"
    assert plan.operation == ActivityOperation.START
    assert plan.constraints == {"theme": "海"}
    assert plan.required_capability == "plugin.first"
    assert len(generator.activities) == 1
    prompt = generator.activities[0].context["plugin_prompt_override"]
    assert "発話本文は生成せず意味構造JSONだけ" in prompt
    assert "認識可能なActivity定義" in prompt


@pytest.mark.asyncio
async def test_behavior_planner_logs_raw_and_parsed_result_to_debug(tmp_path: Path) -> None:
    response = _semantic_json(
        activity_type="first",
        goal="活動を開始する",
        confidence=0.9,
        reason="selected",
    )
    first = ActivityDefinition("first", "第一候補", "plugin.first", "plugin", ("何かしよう",))
    second = ActivityDefinition("second", "第二候補", "plugin.second", "plugin", ("何かしよう",))
    debug_file = tmp_path / "runtime_debug.log"
    TraceLogger.configure(
        level="INFO",
        trace_file_path=tmp_path / "runtime_trace.log",
        output_format="jsonl",
        debug_file_enabled=True,
        debug_file_path=debug_file,
        log_llm_responses=True,
    )
    try:
        await BehaviorPlanner(StubResponseGenerator(response)).plan(
            _context(
                "何かしよう",
                available=frozenset({"plugin.first", "plugin.second"}),
                definitions=(first, second),
            )
        )

        records = [json.loads(line) for line in debug_file.read_text(encoding="utf-8").splitlines()]
        record = next(item for item in records if item["label"] == "llm_response")
        assert record["purpose"] == "behavior_planning"
        assert record["raw_response"] == response
        assert record["parsed_response"]["activity_type"] == "first"
        assert record["stage"] == "parsed"
        assert any(item["label"] == "behavior_planner:llm_candidates" for item in records)
        assert any(item["label"] == "behavior_planner:final_activity_plan" for item in records)
    finally:
        TraceLogger.configure(
            level="INFO",
            trace_file_path=tmp_path / "restored.log",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "constraints"),
    [
        ("しりとりしませんか？", {}),
        ("しりとりしようよ", {}),
        ("一緒にしりとりしない？", {}),
        ("深海生物縛りでしりとりしませんか？", {"theme": "深海生物"}),
        ("動物だけでしりとりをやろう", {"theme": "動物"}),
        ("食べ物縛りのしりとりに付き合って", {"theme": "食べ物"}),
        ("しりとりでもしようか", {}),
        ("語尾をつないで遊ぼう", {}),
        ("最後の文字から言葉を返すやつをやろう", {}),
    ],
)
async def test_semantic_start_expressions_select_shiritori_activity(
    text: str, constraints: dict[str, object]
) -> None:
    generator = StubResponseGenerator(
        _semantic_json(
            goal="条件に沿ってしりとりを行う",
            constraints=constraints,
        )
    )

    plan = await BehaviorPlanner(generator).plan(
        _context(text, definitions=(_shiritori_definition(),))
    )

    assert plan.decision == BehaviorDecision.START_ACTIVITY
    assert plan.activity_type == "shiritori"
    assert plan.operation == ActivityOperation.START
    assert plan.constraints == constraints
    assert plan.speech_act == SpeechAct.PROPOSAL
    assert plan.required_capability == "games.shiritori"
    assert len(generator.activities) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "operation", "knowledge", "negated", "past", "hypothetical"),
    [
        ("しりとりって何？", ActivityOperation.EXPLAIN, True, False, False, False),
        (
            "しりとりのルールを教えて",
            ActivityOperation.EXPLAIN,
            True,
            False,
            False,
            False,
        ),
        (
            "深海生物縛りのしりとりは難しい？",
            ActivityOperation.DISCUSS,
            True,
            False,
            False,
            False,
        ),
        ("昨日しりとりをした", None, False, False, True, False),
        ("しりとりはしたくない", None, False, True, False, False),
        (
            "しりとりをするとしたら何から始める？",
            ActivityOperation.DISCUSS,
            False,
            False,
            False,
            True,
        ),
    ],
)
async def test_non_execution_references_remain_conversation(
    text: str,
    operation: ActivityOperation | None,
    knowledge: bool,
    negated: bool,
    past: bool,
    hypothetical: bool,
) -> None:
    generator = StubResponseGenerator("invalid")

    plan = await BehaviorPlanner(generator).plan(
        _context(text, definitions=(_shiritori_definition(),))
    )

    assert plan.decision == BehaviorDecision.CONVERSATION
    assert plan.activity_type == "conversation"
    assert plan.operation == operation
    assert plan.knowledge_question is knowledge
    assert plan.negated is negated
    assert plan.past_reference is past
    assert plan.hypothetical is hypothetical
    assert generator.activities == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "しりとりしませんか？",
        "しりとりしようよ",
        "一緒にしりとりしない？",
        "深海生物縛りでしりとりしませんか？",
        "動物だけでしりとりをやろう",
        "食べ物縛りのしりとりに付き合って",
        "しりとりでもしようか",
        "語尾をつないで遊ぼう",
        "最後の文字から言葉を返すやつをやろう",
    ],
)
async def test_all_semantic_start_expressions_are_rejected_when_capability_is_off(
    text: str,
) -> None:
    planner = BehaviorPlanner(StubResponseGenerator(_semantic_json()))
    plan = await planner.plan(_context(text, definitions=(_shiritori_definition(),)))
    validator = ActivityPlanValidator(
        lambda capability, plugin_id: False,
        lambda: (_shiritori_definition(),),
    )

    evaluation = validator.validate(plan)

    assert evaluation.accepted is False
    assert evaluation.result.data["reason"] == "capability_unavailable"
    fallback = planner.fallback_after_rejection(evaluation)
    assert fallback.decision == BehaviorDecision.CONVERSATION
    assert fallback.required_capability is None


@pytest.mark.asyncio
async def test_invalid_json_falls_back_without_starting_activity() -> None:
    plan = await BehaviorPlanner(StubResponseGenerator("not-json")).plan(
        _context("深海生物縛りでしりとりしませんか？", definitions=(_shiritori_definition(),))
    )

    assert plan.decision == BehaviorDecision.CONVERSATION
    assert plan.required_capability is None
    assert plan.reason == "execution_request_without_matching_activity"


@pytest.mark.asyncio
async def test_low_confidence_semantic_result_requires_confirmation() -> None:
    plan = await BehaviorPlanner(StubResponseGenerator(_semantic_json(confidence=0.5))).plan(
        _context("言葉で何か遊ばない？", definitions=(_shiritori_definition(),))
    )

    assert plan.decision == BehaviorDecision.ASK_CONFIRMATION
    assert plan.activity_type == "shiritori"
    assert plan.required_capability == "games.shiritori"
    assert plan.operation == ActivityOperation.START
    assert plan.reason == "semantic_confidence_below_threshold"
