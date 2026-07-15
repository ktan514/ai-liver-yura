from __future__ import annotations

from dataclasses import dataclass

from app.domain.activities import Activity, ActivityType


@dataclass(frozen=True, slots=True)
class LlmTraceContext:
    purpose: str
    activity_id: str
    event_id: str | None
    session_id: str | None
    user_input: object
    available_capabilities: object
    planner_state: object
    constraints: object


def build_llm_trace_context(activity: Activity) -> LlmTraceContext:
    payload = activity.context.get("event_payload")
    event_payload = payload if isinstance(payload, dict) else {}
    purpose = _purpose(activity)
    return LlmTraceContext(
        purpose=purpose,
        activity_id=activity.activity_id,
        event_id=activity.source_event_id or _optional_string(activity.context.get("event_id")),
        session_id=_optional_string(
            activity.context.get("game_session_id") or activity.context.get("session_id")
        ),
        user_input=(
            event_payload.get("text")
            or event_payload.get("comment")
            or activity.context.get("user_input")
        ),
        available_capabilities=(
            event_payload.get("available_plugin_capabilities")
            or activity.context.get("available_capabilities")
        ),
        planner_state=activity.context.get("planner_state"),
        constraints=(
            event_payload.get("behavior_fallback_plan")
            or event_payload.get("behavior_plan")
            or activity.context.get("constraints")
        ),
    )


def _purpose(activity: Activity) -> str:
    role = activity.context.get("llm_role")
    if isinstance(role, str) and role in {
        "situation_evaluator",
        "character",
        "response_validator",
    }:
        return role
    if activity.activity_type == ActivityType.BEHAVIOR_PLANNING:
        return "behavior_planning"
    if activity.activity_type == ActivityType.GAME_INPUT_CLASSIFICATION:
        return "game_intent_classification"
    if activity.activity_type == ActivityType.GAME_WITH_USER:
        return "game_response_generation"
    if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
        return "autonomous_talk"
    return "conversation_generation"


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
