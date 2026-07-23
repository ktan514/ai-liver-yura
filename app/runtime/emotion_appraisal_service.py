from __future__ import annotations

from dataclasses import asdict, replace

from app.domain.events import AgentEvent, AgentEventType
from app.ports.emotion_appraisal_model import (
    EmotionAppraisalModel,
    EmotionStimulusContext,
)


class EmotionAppraisalService:
    """自然文の意味評価を実行し、構造化結果をEventへ付与する。"""

    _TEXT_EVENTS = {
        AgentEventType.USER_TEXT,
        AgentEventType.USER_SPEECH,
        AgentEventType.YOUTUBE_COMMENT,
    }
    _PERFORMANCE_REQUEST_KINDS = {
        "emotion_performance",
        "acting_request",
        "style_instruction",
    }

    def __init__(self, model: EmotionAppraisalModel) -> None:
        self._model = model

    async def enrich(
        self,
        event: AgentEvent,
        *,
        relationship: dict[str, object] | None = None,
        situation: dict[str, object] | None = None,
        recent_context: str = "",
        request_kind: str | None = None,
    ) -> AgentEvent:
        if event.event_type not in self._TEXT_EVENTS:
            return event
        if self._is_performance_request(event, request_kind=request_kind):
            return replace(
                event,
                payload={
                    **event.payload,
                    "emotion_appraisal_skipped": "performance_request",
                },
            )
        text = self._event_text(event)
        if not text:
            return event
        context = EmotionStimulusContext(
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            text=text,
            speaker_role=event.authority.role,
            directed_to_yura=self._directed_to_yura(event),
            relationship=dict(relationship or {}),
            recent_context=recent_context,
            situation=dict(situation or {}),
        )
        try:
            appraisal = await self._model.appraise(context)
        except Exception as error:
            return replace(
                event,
                payload={
                    **event.payload,
                    "emotion_appraisal_failed": {
                        "error_type": type(error).__name__,
                        "source_event_id": event.event_id,
                    },
                },
            )
        cause = asdict(appraisal.cause) if appraisal.cause is not None else None
        structured = {
            "joy_delta": appraisal.joy_delta,
            "amusement_delta": appraisal.amusement_delta,
            "anger_delta": appraisal.anger_delta,
            "sadness_delta": appraisal.sadness_delta,
            "fear_delta": appraisal.fear_delta,
            "surprise_delta": appraisal.surprise_delta,
            "discomfort_delta": appraisal.discomfort_delta,
            "pressure_delta": appraisal.pressure_delta,
            "arousal_delta": appraisal.arousal_delta,
            "valence_delta": appraisal.valence_delta,
            "talkativeness_delta": appraisal.talkativeness_delta,
            "reason": appraisal.reason,
            "cause": cause,
            "confidence": appraisal.confidence,
        }
        return replace(
            event,
            payload={
                **event.payload,
                "emotion_appraisal": structured,
            },
        )

    @classmethod
    def _is_performance_request(
        cls, event: AgentEvent, *, request_kind: str | None
    ) -> bool:
        if request_kind in cls._PERFORMANCE_REQUEST_KINDS:
            return True
        value = event.payload.get("emotion_mode")
        return isinstance(value, str) and value in {"performance", "acting"}

    @staticmethod
    def _event_text(event: AgentEvent) -> str:
        value = event.payload.get("text") or event.payload.get("comment")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _directed_to_yura(event: AgentEvent) -> bool:
        value = event.payload.get("directed_to_yura")
        if isinstance(value, bool):
            return value
        return event.event_type in {
            AgentEventType.USER_TEXT,
            AgentEventType.USER_SPEECH,
        }
