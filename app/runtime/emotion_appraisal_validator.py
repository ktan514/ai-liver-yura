from __future__ import annotations

from dataclasses import replace

from app.domain.emotions import EmotionAppraisal, EmotionCause


class EmotionAppraisalValidationError(ValueError):
    pass


class EmotionAppraisalValidator:
    """LLM由来の評価をCoreへ入れる前に正規化・検証する。"""

    _DELTA_LIMIT = 1.0
    _MAX_TEXT_LENGTH = 240

    def validate(self, appraisal: EmotionAppraisal) -> EmotionAppraisal:
        values = {
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
        }
        for name, value in values.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise EmotionAppraisalValidationError(f"{name} が数値ではありません。")
            if not -self._DELTA_LIMIT <= float(value) <= self._DELTA_LIMIT:
                raise EmotionAppraisalValidationError(
                    f"{name} が許容範囲を超えています。"
                )
        cause = appraisal.cause
        normalized_cause = None
        if cause is not None:
            normalized_cause = EmotionCause(
                category=self._sanitize(cause.category, default="unspecified"),
                summary=self._sanitize(cause.summary, default=""),
                target=self._sanitize_optional(cause.target),
                source_event_id=cause.source_event_id,
            )
        return replace(
            appraisal,
            reason=self._sanitize(appraisal.reason, default="structured_appraisal"),
            cause=normalized_cause,
            confidence=max(0.0, min(1.0, float(appraisal.confidence))),
        )

    @classmethod
    def _sanitize(cls, value: str, *, default: str) -> str:
        if not isinstance(value, str):
            return default
        normalized = " ".join(value.replace("\x00", "").split()).strip()
        return normalized[: cls._MAX_TEXT_LENGTH] or default

    @classmethod
    def _sanitize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = cls._sanitize(value, default="")
        return normalized or None
