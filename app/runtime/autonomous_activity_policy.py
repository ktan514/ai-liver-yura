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

    def awakening_settle_seconds(self, emotion: EmotionState) -> float:
        """覚醒直後に状況を受け取る時間を、現在の感情状態から決める。"""

        settle = 6.0 - emotion.arousal * 2.0 - emotion.talkativeness * 1.5
        if emotion.mood == MoodType.TIRED:
            settle += 2.0
        elif emotion.mood == MoodType.EXCITED:
            settle -= 1.0
        return min(8.0, max(2.0, settle))
