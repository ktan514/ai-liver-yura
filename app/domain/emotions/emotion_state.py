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

    def should_reduce_speech(self) -> bool:
        return (
            self.mood in (MoodType.ANGRY, MoodType.SAD, MoodType.TIRED) or self.talkativeness < 0.3
        )

    def should_increase_reaction(self) -> bool:
        return self.mood in (MoodType.HAPPY, MoodType.EXCITED) or self.arousal > 0.7

    def speech_pause_seconds(self) -> float:
        if self.mood == MoodType.ANGRY:
            return 5.0

        if self.mood == MoodType.TIRED:
            return 4.0

        if self.mood == MoodType.EXCITED:
            return 0.5

        if self.talkativeness < 0.3:
            return 3.0

        if self.talkativeness > 0.7:
            return 0.8

        return 1.5

    def _validate_range(self, name: str, value: float, minimum: float, maximum: float) -> None:
        if value < minimum or value > maximum:
            raise ValueError(f"{name} は {minimum} 以上 {maximum} 以下で指定してください。")
