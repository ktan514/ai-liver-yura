from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.domain.activities import Activity, ActivityType
from app.domain.trace_context import TraceContext, trace_context_from


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
    llm_role: str
    model_key: str | None
    service: str | None
    trace_context: TraceContext
    request_id: str
    attempt: int = 1

    @property
    def log_fields(self) -> dict[str, object]:
        return {
            **self.trace_context.as_log_fields(),
            "llm_role": self.llm_role,
            "model_key": self.model_key,
            "service": self.service,
            "request_id": self.request_id,
            "attempt": self.attempt,
        }


def build_llm_trace_context(activity: Activity) -> LlmTraceContext:
    payload = activity.context.get("event_payload")
    event_payload = payload if isinstance(payload, dict) else {}
    purpose = _purpose(activity)
    trace_context = trace_context_from(activity.context) or TraceContext.new(
        source_event_id=activity.source_event_id
    )
    turn = activity.context.get("activity_turn")
    ongoing = activity.context.get("ongoing_activity")
    execution_result = activity.context.get("activity_execution_result")
    if execution_result is None:
        execution_result = event_payload.get("activity_execution_result")
    character_result = activity.context.get("character_generation_result")
    confirmation = event_payload.get("pending_confirmation")
    confirmation_payload = confirmation if isinstance(confirmation, dict) else {}
    trace_context = trace_context.derive(
        source_event_id=activity.source_event_id or trace_context.source_event_id,
        activity_turn_id=str(
            getattr(turn, "turn_id", None)
            or activity.context.get("activity_turn_id")
            or trace_context.activity_turn_id
            or activity.activity_id
        ),
        ongoing_activity_id=_optional_string(
            getattr(ongoing, "ongoing_activity_id", None)
            or activity.context.get("ongoing_activity_id")
        )
        or trace_context.ongoing_activity_id,
        plugin_session_id=_optional_string(
            activity.context.get("plugin_session_id")
            or activity.context.get("session_id")
        )
        or trace_context.plugin_session_id,
        confirmation_id=_optional_string(confirmation_payload.get("confirmation_id"))
        or trace_context.confirmation_id,
        activity_execution_result_id=_optional_string(
            getattr(execution_result, "result_id", None)
        )
        or trace_context.activity_execution_result_id,
        character_generation_result_id=_optional_string(
            getattr(character_result, "result_id", None)
        )
        or trace_context.character_generation_result_id,
    )
    return LlmTraceContext(
        purpose=purpose,
        activity_id=activity.activity_id,
        event_id=activity.source_event_id
        or _optional_string(activity.context.get("event_id")),
        session_id=_optional_string(
            activity.context.get("plugin_session_id")
            or activity.context.get("session_id")
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
        llm_role=purpose,
        model_key=_optional_string(activity.context.get("model_key")),
        service=_optional_string(activity.context.get("llm_service")),
        trace_context=trace_context,
        request_id=str(uuid4()),
        attempt=_positive_int(activity.context.get("llm_attempt")),
    )


def _purpose(activity: Activity) -> str:
    role = activity.context.get("llm_role")
    if isinstance(role, str) and role in {
        "situation_evaluator",
        "character",
        "response_validator",
        "claim_extractor",
        "autonomous_situation_evaluator",
        "confirmation_resolver",
    }:
        return role
    if activity.activity_type == ActivityType.BEHAVIOR_PLANNING:
        return "behavior_planning"
    if activity.activity_type == ActivityType.PLUGIN_ACTIVITY:
        return "plugin_response_generation"
    if activity.activity_type == ActivityType.AUTONOMOUS_TALK:
        return "autonomous_talk"
    return "conversation_generation"


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _positive_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else 1
    )
