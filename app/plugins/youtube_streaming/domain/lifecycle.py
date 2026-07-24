from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.plugins.youtube_streaming.domain.health import utc_now
from app.plugins.youtube_streaming.domain.session import StreamSessionStatus


class StreamLifecycleClass(str, Enum):
    PRE_LIVE = "pre_live"
    LIVE_ACTIVE = "live_active"
    NORMAL_ENDING = "normal_ending"
    EMERGENCY_ENDING = "emergency_ending"
    TERMINAL = "terminal"
    FAILED = "failed"


class LifecycleOperation(str, Enum):
    START_OPENING = "start_opening"
    START_MAIN_SEGMENT = "start_main_segment"
    START_CLOSING = "start_closing"
    START_COMMENT_POLLING = "start_comment_polling"
    CONTINUE_COMMENT_POLLING = "continue_comment_polling"
    EVALUATE_COMMENT = "evaluate_comment"
    EMIT_COMMENT_CANDIDATE = "emit_comment_candidate"
    SELECT_COMMENT_RESPONSE_TARGET = "select_comment_response_target"
    START_COMMENT_RESPONSE = "start_comment_response"
    GENERATE_COMMENT_RESPONSE = "generate_comment_response"
    ENQUEUE_COMMENT_RESPONSE_ACTION = "enqueue_comment_response_action"
    START_COMMENT_RESPONSE_SPEECH = "start_comment_response_speech"
    START_AUTONOMOUS_TALK = "start_autonomous_talk"
    SELECT_TOPIC = "select_topic"
    START_LLM_GENERATION = "start_llm_generation"
    CREATE_ACTION_PLAN = "create_action_plan"
    ENQUEUE_ACTION = "enqueue_action"
    START_SPEECH = "start_speech"
    UPDATE_SUBTITLE = "update_subtitle"
    CHANGE_EXPRESSION = "change_expression"
    START_MOTION = "start_motion"
    START_NORMAL_END = "start_normal_end"
    START_EMERGENCY_STOP = "start_emergency_stop"


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    allowed: bool
    reason_code: str | None
    session_status: str
    external_state_required: bool
    manual_intervention_required: bool
    evaluated_at: datetime = field(default_factory=utc_now)


def classify_lifecycle(status: StreamSessionStatus) -> StreamLifecycleClass:
    if status == StreamSessionStatus.LIVE:
        return StreamLifecycleClass.LIVE_ACTIVE
    if status in {
        StreamSessionStatus.CLOSING_REQUESTED,
        StreamSessionStatus.CLOSING,
        StreamSessionStatus.STOPPING,
    }:
        return StreamLifecycleClass.NORMAL_ENDING
    if status in {
        StreamSessionStatus.EMERGENCY_STOP_REQUESTED,
        StreamSessionStatus.EMERGENCY_STOPPING,
    }:
        return StreamLifecycleClass.EMERGENCY_ENDING
    if status in {
        StreamSessionStatus.COMPLETED,
        StreamSessionStatus.EMERGENCY_STOPPED,
        StreamSessionStatus.ABORTED,
    }:
        return StreamLifecycleClass.TERMINAL
    if status in {StreamSessionStatus.FAILED, StreamSessionStatus.STOP_FAILED}:
        return StreamLifecycleClass.FAILED
    return StreamLifecycleClass.PRE_LIVE
