from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MoodType(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    TIRED = "tired"
    EXCITED = "excited"


@dataclass(frozen=True, slots=True)
class ReactiveEmotionState:
    """出来事に反応して変化する短期感情を表す。"""

    joy: float = 0.0
    amusement: float = 0.0
    anger: float = 0.0
    sadness: float = 0.0
    fear: float = 0.0
    surprise: float = 0.0
    discomfort: float = 0.0
    emotional_pressure: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "joy",
            "amusement",
            "anger",
            "sadness",
            "fear",
            "surprise",
            "discomfort",
            "emotional_pressure",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} は 0.0 以上 1.0 以下で指定してください。")

    def as_dict(self) -> dict[str, float]:
        return {
            "joy": self.joy,
            "amusement": self.amusement,
            "anger": self.anger,
            "sadness": self.sadness,
            "fear": self.fear,
            "surprise": self.surprise,
            "discomfort": self.discomfort,
            "emotional_pressure": self.emotional_pressure,
        }

    def dominant(self) -> tuple[str, float]:
        values = self.as_dict()
        values.pop("emotional_pressure")
        return max(values.items(), key=lambda item: item[1])


@dataclass(frozen=True, slots=True)
class EmotionState:
    """AIライバーの内部感情と、既存処理向けの要約値を表す。"""

    mood: MoodType = MoodType.NEUTRAL
    arousal: float = 0.5
    valence: float = 0.0
    talkativeness: float = 0.5
    reactive: ReactiveEmotionState = field(default_factory=ReactiveEmotionState)

    def __post_init__(self) -> None:
        self._validate_range("arousal", self.arousal, 0.0, 1.0)
        self._validate_range("valence", self.valence, -1.0, 1.0)
        self._validate_range("talkativeness", self.talkativeness, 0.0, 1.0)

    @staticmethod
    def _validate_range(
        name: str, value: float, minimum: float, maximum: float
    ) -> None:
        if value < minimum or value > maximum:
            raise ValueError(
                f"{name} は {minimum} 以上 {maximum} 以下で指定してください。"
            )
