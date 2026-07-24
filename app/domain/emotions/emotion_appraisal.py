from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmotionCause:
    """感情変化の原因をCharacter LLMへ説明可能な形で保持する。"""

    category: str = "no_change"
    summary: str = ""
    target: str | None = None
    source_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class EmotionAppraisal:
    """感情状態へ適用する、原因付きの評価結果。"""

    joy_delta: float = 0.0
    amusement_delta: float = 0.0
    anger_delta: float = 0.0
    sadness_delta: float = 0.0
    fear_delta: float = 0.0
    surprise_delta: float = 0.0
    discomfort_delta: float = 0.0
    pressure_delta: float = 0.0
    arousal_delta: float = 0.0
    valence_delta: float = 0.0
    talkativeness_delta: float = 0.0
    reason: str = "no_change"
    cause: EmotionCause | None = None
    confidence: float = 1.0
    source_event_id: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence は 0.0 以上 1.0 以下で指定してください。")

    @property
    def has_change(self) -> bool:
        return any(
            value != 0.0
            for value in (
                self.joy_delta,
                self.amusement_delta,
                self.anger_delta,
                self.sadness_delta,
                self.fear_delta,
                self.surprise_delta,
                self.discomfort_delta,
                self.pressure_delta,
                self.arousal_delta,
                self.valence_delta,
                self.talkativeness_delta,
            )
        )

    def reactive_deltas(self) -> dict[str, float]:
        return {
            "joy": self.joy_delta,
            "amusement": self.amusement_delta,
            "anger": self.anger_delta,
            "sadness": self.sadness_delta,
            "fear": self.fear_delta,
            "surprise": self.surprise_delta,
            "discomfort": self.discomfort_delta,
            "emotional_pressure": self.pressure_delta,
        }
