from __future__ import annotations

from dataclasses import dataclass

from app.domain.emotions import EmotionState, MoodType


@dataclass(frozen=True, slots=True)
class AutonomousActivityPolicy:
    """感情を表現へ変換せず、自律Activityの開始タイミングだけを判断する。"""

    low_talkativeness_threshold: float = 0.3

    def should_defer_talking(self, emotion: EmotionState) -> bool:
        return (
            emotion.talkativeness < self.low_talkativeness_threshold
            or emotion.mood in {MoodType.ANGRY, MoodType.SAD, MoodType.TIRED}
        )

    def minimum_talk_interval_seconds(self, emotion: EmotionState) -> float:
        if emotion.mood == MoodType.ANGRY:
            return 5.0
        if emotion.mood == MoodType.TIRED:
            return 4.0
        if emotion.mood == MoodType.EXCITED:
            return 0.5
        if emotion.talkativeness < self.low_talkativeness_threshold:
            return 3.0
        if emotion.talkativeness > 0.7:
            return 0.8
        return 1.5
