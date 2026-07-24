from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.domain.activities import Activity, ActivityType, OngoingActivity
from app.domain.events import AgentEvent, AgentEventType
from app.domain.trace_context import TraceContext
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.utils.llm_trace import build_llm_trace_context
from app.utils.trace import TraceLogger


class _ResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return "相関情報を維持した応答"


class _ActionExecutor:
    async def execute(self, action_plan: object) -> None:
        return None


def test_event_creates_trace_and_activity_turn_correlation() -> None:
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"}
    )

    assert event.trace_context.trace_id
    assert event.trace_context.source_event_id == event.event_id
    assert event.trace_context.activity_turn_id


@pytest.mark.asyncio
async def test_user_turn_keeps_trace_from_activity_through_output() -> None:
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"}
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="応答する",
        source_event_id=event.event_id,
        context={
            "event_payload": event.payload,
            "trace_context": event.trace_context,
        },
    )

    group = await ActionPlanner(_ResponseGenerator()).plan(activity)
    output = await ActionScheduler(_ActionExecutor()).execute(group)
    turn = group.activity_turn_result

    assert turn is not None
    assert turn.trace_id == event.trace_context.trace_id
    assert turn.activity_turn_id == event.trace_context.activity_turn_id
    assert turn.character_result is not None
    assert turn.character_result.trace_id == event.trace_context.trace_id
    assert output.trace_id == event.trace_context.trace_id
    assert output.activity_turn_id == event.trace_context.activity_turn_id
    assert {result.trace_id for result in output.action_results} == {
        event.trace_context.trace_id
    }


def test_ongoing_activity_keeps_session_id_but_creates_trace_per_turn() -> None:
    ongoing = OngoingActivity(
        activity_type="shiritori",
        goal="しりとりを続ける",
        expected_input="次の単語",
        end_condition="終了",
    )
    traces = [TraceContext.new(source_event_id=f"event-{index}") for index in range(3)]
    for index, trace in enumerate(traces):
        ongoing = ongoing.begin_turn(
            f"word-{index}",
            trace.source_event_id,
            trace_context=trace,
        )

    assert len({turn.trace_context.trace_id for turn in ongoing.turns}) == 3
    assert {turn.trace_context.ongoing_activity_id for turn in ongoing.turns} == {
        ongoing.ongoing_activity_id
    }
    assert len({turn.turn_id for turn in ongoing.turns}) == 3


def test_child_trace_keeps_parent_relationship() -> None:
    original = TraceContext.new(source_event_id="event-original")
    resolution = original.child(source_event_id="event-resolution")

    assert resolution.trace_id != original.trace_id
    assert resolution.parent_trace_id == original.trace_id


def test_llm_trace_has_formal_role_and_request_correlation() -> None:
    trace = TraceContext.new(source_event_id="event-1").derive(
        activity_turn_id="turn-1"
    )
    activity = Activity(
        activity_type=ActivityType.BEHAVIOR_PLANNING,
        goal="意味解析",
        source_event_id="event-1",
        context={
            "llm_role": "situation_evaluator",
            "trace_context": trace,
            "llm_attempt": 2,
        },
    )

    context = build_llm_trace_context(activity)

    assert context.llm_role == "situation_evaluator"
    assert context.trace_context.trace_id == trace.trace_id
    assert context.trace_context.activity_turn_id == "turn-1"
    assert context.request_id
    assert context.attempt == 2


@pytest.mark.asyncio
async def test_bound_loggers_do_not_mix_parallel_trace_ids(tmp_path: Path) -> None:
    log_path = tmp_path / "trace.jsonl"
    TraceLogger.configure(
        level="DEBUG",
        trace_file_path=log_path,
        output_format="jsonl",
    )

    async def write(trace_id: str) -> None:
        logger = TraceLogger().bind(TraceContext(trace_id=trace_id))
        await asyncio.to_thread(logger.debug, "parallel_trace", sequence=trace_id)

    try:
        await asyncio.gather(write("trace-a"), write("trace-b"))
        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
        ]
        pairs = {(record["trace_id"], record["sequence"]) for record in records}
        assert pairs == {("trace-a", "trace-a"), ("trace-b", "trace-b")}
    finally:
        TraceLogger.configure(
            level="INFO",
            trace_file_path="logs/runtime_trace.log",
        )
