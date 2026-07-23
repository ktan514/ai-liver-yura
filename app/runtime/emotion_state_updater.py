from __future__ import annotations

from app.domain.emotions import EmotionAppraisal, EmotionState, MoodType
from app.domain.emotions.emotion_state import ReactiveEmotionState


class EmotionStateUpdater:
    """評価結果と時間経過からEmotionStateを範囲内で更新する。"""

    _DECAY_SECONDS = {
        "joy": 1200.0,
        "amusement": 600.0,
        "anger": 1800.0,
        "sadness": 3600.0,
        "fear": 1200.0,
        "surprise": 300.0,
        "discomfort": 1500.0,
        "emotional_pressure": 2700.0,
    }

    def apply(self, state: EmotionState, appraisal: EmotionAppraisal) -> EmotionState:
        reactive_values = state.reactive.as_dict()
        for name, delta in appraisal.reactive_deltas().items():
            reactive_values[name] = self._clamp(
                reactive_values[name] + delta,
                0.0,
                1.0,
            )
        reactive = ReactiveEmotionState(**reactive_values)
        arousal = self._clamp(
            state.arousal + appraisal.arousal_delta,
            0.0,
            1.0,
        )
        valence = self._clamp(
            state.valence + appraisal.valence_delta,
            -1.0,
            1.0,
        )
        talkativeness = self._clamp(
            state.talkativeness + appraisal.talkativeness_delta,
            0.0,
            1.0,
        )
        return EmotionState(
            mood=self.derive_mood(
                reactive,
                fallback=state.mood,
                arousal=arousal,
                valence=valence,
            ),
            arousal=arousal,
            valence=valence,
            talkativeness=talkativeness,
            reactive=reactive,
        )

    def decay(self, state: EmotionState, *, elapsed_seconds: float) -> EmotionState:
        if elapsed_seconds <= 0.0:
            return state
        factor = min(1.0, elapsed_seconds / 1800.0)
        arousal = self._toward(state.arousal, 0.5, factor)
        valence = self._toward(state.valence, 0.0, factor)
        talkativeness = self._toward(state.talkativeness, 0.5, factor)
        reactive_values = {
            name: self._decay_value(
                value,
                elapsed_seconds=elapsed_seconds,
                decay_seconds=self._DECAY_SECONDS[name],
            )
            for name, value in state.reactive.as_dict().items()
        }
        reactive = ReactiveEmotionState(**reactive_values)
        settled = (
            abs(arousal - 0.5) < 0.01
            and abs(valence) < 0.01
            and abs(talkativeness - 0.5) < 0.01
            and max(reactive.as_dict().values()) < 0.01
        )
        return EmotionState(
            mood=(
                MoodType.NEUTRAL
                if settled
                else self.derive_mood(
                    reactive,
                    fallback=state.mood,
                    arousal=arousal,
                    valence=valence,
                )
            ),
            arousal=arousal,
            valence=valence,
            talkativeness=talkativeness,
            reactive=reactive,
        )

    @staticmethod
    def derive_mood(
        reactive: ReactiveEmotionState,
        *,
        fallback: MoodType = MoodType.NEUTRAL,
        arousal: float = 0.5,
        valence: float = 0.0,
    ) -> MoodType:
        """個別感情から互換用の代表moodを導出する。"""

        name, intensity = reactive.dominant()
        if intensity < 0.2:
            if arousal >= 0.8 and valence > 0.15:
                return MoodType.EXCITED
            return fallback
        if name in {"joy", "amusement"}:
            return MoodType.EXCITED if arousal >= 0.8 else MoodType.HAPPY
        if name in {"anger", "discomfort"}:
            return MoodType.ANGRY
        if name == "sadness":
            return MoodType.SAD
        if name == "fear":
            return MoodType.SAD if arousal < 0.45 else MoodType.EXCITED
        if name == "surprise":
            return MoodType.EXCITED
        return fallback

    @staticmethod
    def _decay_value(
        value: float,
        *,
        elapsed_seconds: float,
        decay_seconds: float,
    ) -> float:
        factor = min(1.0, elapsed_seconds / decay_seconds)
        return max(0.0, value * (1.0 - factor))

    @staticmethod
    def _toward(value: float, baseline: float, factor: float) -> float:
        return value + ((baseline - value) * factor)

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
