from __future__ import annotations

from collections.abc import Mapping

from app.domain.emotions import EmotionAppraisal, EmotionCause
from app.domain.events import AgentEvent, AgentEventType


class EmotionAppraiser:
    """Eventの確定事実と構造化済み意味評価を感情変化へ変換する。"""

    STRUCTURED_APPRAISAL_KEY = "emotion_appraisal"

    def appraise(self, event: AgentEvent) -> EmotionAppraisal:
        structured = event.payload.get(self.STRUCTURED_APPRAISAL_KEY)
        if isinstance(structured, Mapping):
            return self._from_mapping(structured, event)

        values = {
            AgentEventType.USER_TEXT: {
                "arousal_delta": 0.02,
                "talkativeness_delta": 0.03,
                "reason": "user_attention_received",
                "cause_summary": "ユーザーから注意を向けられた",
            },
            AgentEventType.USER_SPEECH: {
                "arousal_delta": 0.03,
                "talkativeness_delta": 0.03,
                "reason": "user_attention_received",
                "cause_summary": "ユーザーから声をかけられた",
            },
            AgentEventType.YOUTUBE_COMMENT: {
                "arousal_delta": 0.02,
                "talkativeness_delta": 0.02,
                "reason": "viewer_attention_received",
                "cause_summary": "視聴者からコメントを受け取った",
            },
            AgentEventType.ACTION_FAILED: {
                "anger_delta": 0.05,
                "sadness_delta": 0.04,
                "discomfort_delta": 0.10,
                "pressure_delta": 0.04,
                "arousal_delta": 0.08,
                "valence_delta": -0.08,
                "talkativeness_delta": -0.02,
                "reason": "action_failed",
                "cause_summary": "実行しようとした行動が失敗した",
            },
            AgentEventType.STREAM_STARTED: {
                "joy_delta": 0.05,
                "surprise_delta": 0.03,
                "arousal_delta": 0.05,
                "valence_delta": 0.03,
                "talkativeness_delta": 0.02,
                "reason": "stream_started",
                "cause_summary": "配信が開始された",
            },
            AgentEventType.STREAM_ENDED: {
                "sadness_delta": 0.03,
                "arousal_delta": -0.04,
                "talkativeness_delta": -0.02,
                "reason": "stream_ended",
                "cause_summary": "配信が終了した",
            },
        }.get(event.event_type)
        if values is None:
            return EmotionAppraisal(source_event_id=event.event_id)
        return self._from_mapping(values, event)

    def _from_mapping(
        self, values: Mapping[str, object], event: AgentEvent
    ) -> EmotionAppraisal:
        reason = self._text(values.get("reason"), "structured_appraisal")
        cause_value = values.get("cause")
        cause_mapping = cause_value if isinstance(cause_value, Mapping) else values
        cause = EmotionCause(
            category=self._text(cause_mapping.get("category"), reason),
            summary=self._text(cause_mapping.get("summary"), "")
            or self._text(cause_mapping.get("cause_summary"), ""),
            target=self._optional_text(
                cause_mapping.get("target") or cause_mapping.get("target_id")
            ),
            source_event_id=event.event_id,
        )
        return EmotionAppraisal(
            joy_delta=self._number(values.get("joy_delta")),
            amusement_delta=self._number(values.get("amusement_delta")),
            anger_delta=self._number(values.get("anger_delta")),
            sadness_delta=self._number(values.get("sadness_delta")),
            fear_delta=self._number(values.get("fear_delta")),
            surprise_delta=self._number(values.get("surprise_delta")),
            discomfort_delta=self._number(values.get("discomfort_delta")),
            pressure_delta=self._number(values.get("pressure_delta")),
            arousal_delta=self._number(values.get("arousal_delta")),
            valence_delta=self._number(values.get("valence_delta")),
            talkativeness_delta=self._number(values.get("talkativeness_delta")),
            reason=reason,
            cause=cause,
            confidence=self._bounded_number(values.get("confidence"), default=1.0),
            source_event_id=event.event_id,
        )

    @staticmethod
    def _number(value: object, default: float = 0.0) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return default

    @classmethod
    def _bounded_number(cls, value: object, *, default: float) -> float:
        return max(0.0, min(1.0, cls._number(value, default)))

    @staticmethod
    def _text(value: object, default: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    @classmethod
    def _optional_text(cls, value: object) -> str | None:
        text = cls._text(value, "")
        return text or None
