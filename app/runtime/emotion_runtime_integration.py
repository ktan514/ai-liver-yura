from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from types import MethodType
from typing import Any

from app.core.plugins.user_request import interpret_user_request
from app.domain.activities import Activity
from app.domain.character_response import ResponseContext, VoiceIntent
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_state import AgentState
from app.runtime.character_response_pipeline import CharacterLlmService
from app.runtime.emotion_appraisal_service import EmotionAppraisalService
from app.runtime.emotion_context_builder import EmotionContextBuilder


class EmotionAwareResponseContextBuilder:
    """既存Builderの結果へ最新の内部感情・原因・履歴を注入する。"""

    def __init__(
        self,
        delegate: Any,
        state_provider: Callable[[], AgentState],
    ) -> None:
        self._delegate = delegate
        self._state_provider = state_provider
        self._emotion_context_builder = EmotionContextBuilder()

    def build(self, activity: Activity) -> ResponseContext:
        context = self._delegate.build(activity)
        state = self._state_provider()
        emotion_context = self._emotion_context_builder.build(
            state.current_emotion,
            state.memory.emotion_history,
        )
        return replace(context, emotion=asdict(emotion_context))


def attach_emotion_runtime(
    coordinator: Any,
    appraisal_service: EmotionAppraisalService,
) -> Any:
    """RuntimeCoordinatorへ感情評価とCharacter文脈接続を後付けする。"""

    original_publish_events = coordinator.publish_events

    async def publish_events_with_emotion(
        self: Any,
        events: list[AgentEvent],
    ) -> None:
        enriched_events: list[AgentEvent] = []
        for event in events:
            state = self.agent_state
            relationship = state.relationship_memory.current
            relationship_context = (
                relationship.as_context() if relationship is not None else {}
            )
            request_kind = None
            if event.event_type == AgentEventType.USER_TEXT:
                text = event.payload.get("text")
                if isinstance(text, str):
                    request_kind = interpret_user_request(text).kind.value
            enriched_events.append(
                await appraisal_service.enrich(
                    event,
                    relationship=relationship_context,
                    situation=state.current_situation.as_context(),
                    recent_context=_recent_context(state),
                    request_kind=request_kind,
                )
            )
        await original_publish_events(enriched_events)

    coordinator.publish_events = MethodType(publish_events_with_emotion, coordinator)
    _attach_emotion_context_builder(coordinator)
    _attach_voice_intent_parser()
    return coordinator


def _attach_emotion_context_builder(coordinator: Any) -> None:
    action_planner = getattr(coordinator, "_action_planner", None)
    pipeline = getattr(action_planner, "_character_response_pipeline", None)
    context_builder = getattr(pipeline, "_context_builder", None)
    if context_builder is None:
        return
    pipeline._context_builder = EmotionAwareResponseContextBuilder(
        context_builder,
        lambda: coordinator.agent_state,
    )


def _attach_voice_intent_parser() -> None:
    CharacterLlmService._parse_voice_intent = staticmethod(_parse_voice_intent)


def _parse_voice_intent(value: object) -> VoiceIntent | None:
    if value is None:
        return VoiceIntent()
    if not isinstance(value, dict):
        return None
    style = value.get("style")
    if not isinstance(style, str) or not style.strip():
        return None
    try:
        return VoiceIntent(
            style=style.strip(),
            speed=_number(value, "speed", 1.0),
            pitch=_number(value, "pitch", 0.0),
            intonation=_number(value, "intonation", 1.0),
            volume=_number(value, "volume", 1.0),
            breathiness=_number(value, "breathiness", 0.0),
            emotional_leakage=_number(value, "emotional_leakage", 0.0),
        )
    except ValueError:
        return None


def _number(value: dict[str, object], key: str, default: float) -> float:
    item = value.get(key, default)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise ValueError(f"{key}は数値で指定してください。")
    return float(item)


def _recent_context(state: AgentState) -> str:
    history = state.memory.emotion_history[-3:]
    if not history:
        return ""
    return "\n".join(
        item.cause_summary or item.reason
        for item in history
        if item.cause_summary or item.reason
    )
