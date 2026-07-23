from __future__ import annotations

from dataclasses import dataclass

from app.domain.emotions import EmotionState, MoodType


@dataclass(frozen=True, slots=True)
class AutonomousActivityPolicy:
    """感情を表現へ変換せず、自律Activityの開始タイミングだけを判断する。

    対人会話や直前の自律発話の後には、相手が会話へ戻れる余白を確保する。
    沈黙は継続要求として扱わず、次の発話までの最小間隔を感情状態から決める。
    """

    low_talkativeness_threshold: float = 0.3
    default_handoff_seconds: float = 30.0
    excited_handoff_seconds: float = 20.0
    quiet_handoff_seconds: float = 45.0
    tired_handoff_seconds: float = 60.0

    def should_defer_talking(self, emotion: EmotionState) -> bool:
        return (
            emotion.talkativeness < self.low_talkativeness_threshold
            or emotion.mood in {MoodType.ANGRY, MoodType.SAD, MoodType.TIRED}
        )

    def minimum_talk_interval_seconds(self, emotion: EmotionState) -> float:
        """発話後に発話権を相手へ返すための最小待機時間を返す。"""

        if emotion.mood == MoodType.TIRED:
            return self.tired_handoff_seconds
        if emotion.mood in {MoodType.ANGRY, MoodType.SAD}:
            return self.quiet_handoff_seconds
        if emotion.mood == MoodType.EXCITED:
            return self.excited_handoff_seconds
        if emotion.talkativeness < self.low_talkativeness_threshold:
            return self.tired_handoff_seconds
        if emotion.talkativeness > 0.7:
            return self.default_handoff_seconds
        return self.quiet_handoff_seconds

    def awakening_settle_seconds(self, emotion: EmotionState) -> float:
        """覚醒直後に状況を受け取る時間を、現在の感情状態から決める。"""

        settle = 6.0 - emotion.arousal * 2.0 - emotion.talkativeness * 1.5
        if emotion.mood == MoodType.TIRED:
            settle += 2.0
        elif emotion.mood == MoodType.EXCITED:
            settle -= 1.0
        return min(8.0, max(2.0, settle))
