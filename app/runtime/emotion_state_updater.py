from __future__ import annotations

from app.domain.emotions import EmotionAppraisal, EmotionState, MoodType


class EmotionStateUpdater:
    """評価結果と時間経過からEmotionStateを範囲内で更新する。"""

    def apply(self, state: EmotionState, appraisal: EmotionAppraisal) -> EmotionState:
        return EmotionState(
            mood=state.mood,
            arousal=self._clamp(state.arousal + appraisal.arousal_delta, 0.0, 1.0),
            valence=self._clamp(state.valence + appraisal.valence_delta, -1.0, 1.0),
            talkativeness=self._clamp(
                state.talkativeness + appraisal.talkativeness_delta, 0.0, 1.0
            ),
        )

    def decay(self, state: EmotionState, *, elapsed_seconds: float) -> EmotionState:
        if elapsed_seconds <= 0.0:
            return state
        factor = min(1.0, elapsed_seconds / 1800.0)
        arousal = self._toward(state.arousal, 0.5, factor)
        valence = self._toward(state.valence, 0.0, factor)
        talkativeness = self._toward(state.talkativeness, 0.5, factor)
        settled = (
            abs(arousal - 0.5) < 0.01
            and abs(valence) < 0.01
            and abs(talkativeness - 0.5) < 0.01
        )
        return EmotionState(
            mood=MoodType.NEUTRAL if settled else state.mood,
            arousal=arousal,
            valence=valence,
            talkativeness=talkativeness,
        )

    @staticmethod
    def _toward(value: float, baseline: float, factor: float) -> float:
        return value + ((baseline - value) * factor)

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
