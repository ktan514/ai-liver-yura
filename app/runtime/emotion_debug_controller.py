from __future__ import annotations

from dataclasses import replace

from app.domain.emotions import EmotionState, MoodType, ReactiveEmotionState
from app.runtime.agent_state import AgentState
from app.runtime.emotion_state_updater import EmotionStateUpdater


class EmotionDebugController:
    """管理・診断経路からのみ使用する感情状態注入サービス。"""

    _FIELDS = {
        "joy",
        "amusement",
        "anger",
        "sadness",
        "fear",
        "surprise",
        "discomfort",
        "emotional_pressure",
    }

    def __init__(self, updater: EmotionStateUpdater | None = None) -> None:
        self._updater = updater or EmotionStateUpdater()

    def set_values(
        self,
        state: AgentState,
        values: dict[str, float],
        *,
        authority_role: str,
    ) -> AgentState:
        self._require_admin(authority_role)
        unknown = set(values) - self._FIELDS
        if unknown:
            raise ValueError(f"未対応の感情項目です: {', '.join(sorted(unknown))}")
        current = state.current_emotion.reactive.as_dict()
        for name, value in values.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{name} は数値で指定してください。")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} は0.0以上1.0以下で指定してください。")
            current[name] = float(value)
        reactive = ReactiveEmotionState(**current)
        emotion = replace(
            state.current_emotion,
            reactive=reactive,
            mood=self._updater.derive_mood(reactive),
        )
        return state.with_emotion(emotion)

    def reset(self, state: AgentState, *, authority_role: str) -> AgentState:
        self._require_admin(authority_role)
        return state.with_emotion(EmotionState())

    @staticmethod
    def snapshot(state: AgentState, *, authority_role: str) -> dict[str, object]:
        EmotionDebugController._require_admin(authority_role)
        emotion = state.current_emotion
        return {
            "mood": emotion.mood.value,
            "arousal": emotion.arousal,
            "valence": emotion.valence,
            "talkativeness": emotion.talkativeness,
            "reactive": emotion.reactive.as_dict(),
        }

    @staticmethod
    def _require_admin(authority_role: str) -> None:
        if authority_role not in {"system", "owner", "admin"}:
            raise PermissionError("感情状態の操作には管理者権限が必要です。")
