from __future__ import annotations

import threading
from datetime import datetime, timezone
from queue import Queue

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.activity_turn_result import (
    ActivityOutputStatus,
    CharacterGenerationResult,
    CharacterGenerationStatus,
)
from app.domain.character_response import (
    CharacterResponse,
    ResponseClaim,
)
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.domain.short_term_memory import ShortTermMemory
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
    ActivityPlanningService,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_execution import prepare_autonomous_execution
from app.runtime.behavior_planner import BehaviorPlanner
from app.runtime.character_response_pipeline import ResponseContextBuilder, ResponseValidator
from app.runtime.planned_activity_queue import PlannedActivity, PlannedActivityQueue


class ForbiddenLegacyGenerator:
    def __init__(self) -> None:
        self.call_count = 0

    async def generate_response(self, activity: Activity) -> str:
        self.call_count += 1
        raise AssertionError("legacy generator must not generate autonomous speech")


class CharacterPipelineStub:
    def __init__(self, speech: str, on_generate: object | None = None) -> None:
        self.speech = speech
        self.activities: list[Activity] = []
        self._on_generate = on_generate

    async def generate_with_result(
        self, activity: Activity
    ) -> tuple[CharacterResponse, CharacterGenerationResult]:
        self.activities.append(activity)
        if callable(self._on_generate):
            self._on_generate()
        return (
            CharacterResponse(
                speech=self.speech,
                expression="smile",
                claims=(ResponseClaim.CONVERSATION_ONLY,),
            ),
            CharacterGenerationResult(
                status=CharacterGenerationStatus.VALIDATED,
                activity_turn_id=activity.activity_id,
                source_event_id=activity.source_event_id,
                adopted_text=self.speech,
            ),
        )


class SuccessfulExecutor:
    async def execute(self, action_plan: ActionPlan) -> None:
        return None


class FailingSpeakExecutor:
    async def execute(self, action_plan: ActionPlan) -> None:
        if action_plan.action_type == ActionType.SPEAK:
            raise RuntimeError("speech output failed")


class SpeechActionPlanner:
    async def plan(self, activity: Activity) -> ActionPlanGroup:
        return ActionPlanGroup(
            action_plans=[
                ActionPlan(
                    action_type=ActionType.SPEAK,
                    text="実際に出力する自律発話",
                    source_activity_id=activity.activity_id,
                )
            ],
            source_activity_id=activity.activity_id,
        )


class AlwaysAcceptValidatorModel:
    def __init__(self) -> None:
        self.call_count = 0

    async def validate_character_response(self, activity: Activity) -> str:
        self.call_count += 1
        return '{"accepted":true,"reason":"valid","extracted_claims":[]}'


class PlanningLifeStub:
    def __init__(self, event: AgentEvent) -> None:
        self.event = event
        self.agent_state = AgentState(
            current_drive=DriveState(
                curiosity=0.9,
                engagement=0.7,
                boredom=0.4,
                energy=0.8,
            ),
            current_emotion=EmotionState(talkativeness=0.8),
            stream_status="live",
        )
        self.autonomous_topic = None

    def plan_next_event(self, now: datetime | None = None) -> AgentEvent:
        return self.event

    def handle_event(self, event: AgentEvent) -> None:
        return None

    def sync_from_activity_manager(self) -> None:
        return None


def _autonomous_activity(topic: str = "深海生物の発光") -> Activity:
    activity = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal=f"{topic}について短く話す",
        source_event_id="event-auto",
        context={
            "behavior_plan": {
                "activity_type": "autonomous_talk",
                "operation": "start",
                "goal": f"{topic}について短く話す",
                "topic": topic,
                "planning_reason": "curiosity_peak",
                "constraints": {"max_length": "short"},
            },
            "autonomous_situation_context": {
                "drive_state": {"curiosity": 0.9, "energy": 0.8},
                "emotion_state": {"talkativeness": 0.8},
                "recent_speech_summary": "前回はクラゲについて話した",
                "recent_topic_summary": "深海の環境",
                "stream_status": "live",
            },
        },
    )
    prepare_autonomous_execution(activity)
    return activity


def test_autonomous_planning_builds_situation_and_behavior_plan_without_speech() -> None:
    event = AgentEvent(
        event_type=AgentEventType.CURIOSITY_PEAK,
        payload={
            "reason": "curiosity_peak",
            "selected_topic": "深海生物の発光",
        },
    )
    manager = ActivityManager()
    life = PlanningLifeStub(event)
    memory = ShortTermMemory()
    memory.add_speech("さっきはクラゲについて話した")
    planner = BehaviorPlanner(response_generator=ForbiddenLegacyGenerator())
    service = ActivityPlanningService(
        agent_life_service=life,  # type: ignore[arg-type]
        activity_manager=manager,
        behavior_planner=planner,
        short_term_memory=memory,
    )

    planned = service.plan_once(now=datetime.now(timezone.utc))

    assert planned is not None
    payload = planned.activity.context["event_payload"]
    assert payload["behavior_plan"]["topic"] == "深海生物の発光"
    assert payload["behavior_plan"]["goal"] == "深海生物の発光について短く自律的に話す"
    assert payload["behavior_plan"]["planning_reason"] == "curiosity_peak"
    assert "speech" not in payload["behavior_plan"]
    situation = payload["autonomous_situation_context"]
    assert "さっきはクラゲ" in situation["recent_speech_summary"]
    assert situation["stream_status"] == "live"
    assert planned.planned_topic == "深海生物の発光"


@pytest.mark.asyncio
async def test_autonomous_activity_uses_character_validator_and_turn_results() -> None:
    activity = _autonomous_activity()
    legacy = ForbiddenLegacyGenerator()
    character = CharacterPipelineStub("深海生物が光る仕組みって不思議だよね")
    planner = ActionPlanner(
        response_generator=legacy,
        character_response_pipeline=character,  # type: ignore[arg-type]
    )

    group = await planner.plan(activity)
    output = await ActionScheduler(SuccessfulExecutor()).execute(group)
    result = group.activity_turn_result

    assert legacy.call_count == 0
    assert character.activities == [activity]
    assert result is not None
    assert result.execution_result is activity.context["activity_execution_result"]
    assert result.character_result is not None
    assert result.character_result.status == CharacterGenerationStatus.VALIDATED
    assert output.status == ActivityOutputStatus.COMPLETED
    assert result.with_output(output).final_status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "speech",
    [
        "検索結果を取得したよ",
        "配信を開始したよ",
        "ゲームを開始したよ",
    ],
)
async def test_autonomous_external_execution_claims_are_rejected(speech: str) -> None:
    activity = _autonomous_activity()
    context = ResponseContextBuilder().build(activity)
    response = CharacterResponse(speech=speech, claims=())

    result = await ResponseValidator().validate(activity, context, response)

    assert result.accepted is False


def test_autonomous_response_context_contains_planning_facts() -> None:
    activity = _autonomous_activity()

    context = ResponseContextBuilder().build(activity)

    assert context.user_input == ""
    assert context.topic == "深海生物の発光"
    assert context.planning_reason == "curiosity_peak"
    assert context.constraints == {"max_length": "short"}
    assert context.recent_speech_summary == "前回はクラゲについて話した"
    assert context.drive == {"curiosity": 0.9, "energy": 0.8}


@pytest.mark.asyncio
async def test_autonomous_topic_drift_is_rejected_deterministically() -> None:
    activity = _autonomous_activity("深海生物の発光")
    context = ResponseContextBuilder().build(activity)
    response = CharacterResponse(
        speech="今日は株式市場と投資信託の値動きを詳しく話すね",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )

    model = AlwaysAcceptValidatorModel()
    result = await ResponseValidator(model).validate(activity, context, response)

    assert result.accepted is False
    assert "autonomous_topic_drift" in result.claim_differences
    assert model.call_count == 0


@pytest.mark.asyncio
async def test_cancel_after_character_generation_does_not_create_actions() -> None:
    activity = _autonomous_activity()
    active = True

    def cancel() -> None:
        nonlocal active
        active = False

    pipeline = CharacterPipelineStub("まだ出力してはいけない文", on_generate=cancel)
    planner = ActionPlanner(
        response_generator=ForbiddenLegacyGenerator(),
        character_response_pipeline=pipeline,  # type: ignore[arg-type]
        activity_is_active=lambda _: active,
    )

    group = await planner.plan(activity)

    assert group.action_plans == []
    assert group.activity_turn_result is not None
    assert group.activity_turn_result.character_result is not None


class BlockingPlanningService:
    def __init__(self, planned: PlannedActivity) -> None:
        self.planned = planned
        self.started = threading.Event()
        self.release = threading.Event()
        self.canceled: list[PlannedActivity] = []

    def plan_once(self, now: datetime | None = None) -> PlannedActivity:
        self.started.set()
        self.release.wait(timeout=1.0)
        return self.planned

    def cancel_planned_activity(self, planned: PlannedActivity, *, reason: str) -> None:
        self.canceled.append(planned)


def test_user_input_cancels_autonomous_activity_while_planning() -> None:
    planned = PlannedActivity(activity=_autonomous_activity())
    service = BlockingPlanningService(planned)
    queue = PlannedActivityQueue()
    planner_thread = ActivityPlannerThread(
        request_queue=Queue(),
        planned_activity_queue=queue,
        planning_service=service,  # type: ignore[arg-type]
    )
    result: list[PlannedActivity | None] = []
    worker = threading.Thread(
        target=lambda: result.append(planner_thread.run_once(ActivityPlanningRequest()))
    )
    worker.start()
    assert service.started.wait(timeout=1.0)

    planner_thread.cancel_inflight_autonomous(source_event_id="user-event")
    service.release.set()
    worker.join(timeout=1.0)

    assert result == [None]
    assert queue.is_empty()
    assert service.canceled == [planned]


@pytest.mark.asyncio
@pytest.mark.parametrize("speech_succeeds", [True, False])
async def test_autonomous_topic_is_recorded_only_after_speak_success(
    speech_succeeds: bool,
) -> None:
    manager = ActivityManager()
    activity = manager.handle_event(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK, payload={"reason": "test"})
    )
    queue = PlannedActivityQueue()
    queue.put(PlannedActivity(activity=activity))
    agent_life = AgentLifeService(manager, initial_state=AgentState())
    executor = SuccessfulExecutor() if speech_succeeds else FailingSpeakExecutor()
    thread = ActivityExecutorThread(
        planned_activity_queue=queue,
        action_planner=SpeechActionPlanner(),  # type: ignore[arg-type]
        action_scheduler=ActionScheduler(executor),
        activity_manager=manager,
        agent_life_service=agent_life,
    )

    await thread.run_once()

    if speech_succeeds:
        assert agent_life.autonomous_topic is not None
        assert agent_life.autonomous_topic.original_text == "実際に出力する自律発話"
    else:
        assert agent_life.autonomous_topic is None
