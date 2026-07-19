from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MoodType(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    TIRED = "tired"
    EXCITED = "excited"


@dataclass(frozen=True, slots=True)
class EmotionState:
    """AIライバーの感情・気分状態を表すドメインモデル。"""

    mood: MoodType = MoodType.NEUTRAL
    arousal: float = 0.5
    valence: float = 0.0
    talkativeness: float = 0.5

    def __post_init__(self) -> None:
        self._validate_range("arousal", self.arousal, 0.0, 1.0)
        self._validate_range("valence", self.valence, -1.0, 1.0)
        self._validate_range("talkativeness", self.talkativeness, 0.0, 1.0)

    def _validate_range(
        self, name: str, value: float, minimum: float, maximum: float
    ) -> None:
        if value < minimum or value > maximum:
            raise ValueError(
                f"{name} は {minimum} 以上 {maximum} 以下で指定してください。"
            )
