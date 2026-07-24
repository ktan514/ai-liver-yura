from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .emotion_state import EmotionState


class PerformanceDirectiveType(str, Enum):
    """外部から要求された演技。内部感情そのものではない。"""

    NONE = "none"
    ACT_HAPPY = "act_happy"
    ACT_SAD = "act_sad"
    ACT_ANGRY = "act_angry"
    ACT_SCARED = "act_scared"
    ACT_SURPRISED = "act_surprised"


@dataclass(frozen=True, slots=True)
class PerformanceDirective:
    directive_type: PerformanceDirectiveType = PerformanceDirectiveType.NONE
    intensity: float = 0.0
    source: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError("演技強度は0.0以上1.0以下で指定してください。")
        if self.directive_type == PerformanceDirectiveType.NONE and self.intensity != 0.0:
            raise ValueError("演技指示なしの場合、演技強度は0.0にしてください。")


@dataclass(frozen=True, slots=True)
class EmotionExpression:
    """内部感情から導出した表現用パラメータ。内部状態は変更しない。"""

    primary: str
    secondary: str | None
    valence: float
    arousal: float
    expressivity: float
    tension: float

    def __post_init__(self) -> None:
        if not -1.0 <= self.valence <= 1.0:
            raise ValueError("valenceは-1.0以上1.0以下で指定してください。")
        for name in ("arousal", "expressivity", "tension"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name}は0.0以上1.0以下で指定してください。")


class EmotionExpressionDeriver:
    """複数感情を保持したまま、出力層向けの混合表現を導出する。"""

    def derive(self, state: EmotionState) -> EmotionExpression:
        ranked = sorted(
            (
                (name, value)
                for name, value in state.reactive.as_dict().items()
                if name != "emotional_pressure"
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        primary_name, primary_value = ranked[0]
        secondary_name, secondary_value = ranked[1]
        secondary = secondary_name if secondary_value >= 0.2 else None
        pressure = state.reactive.emotional_pressure
        expressivity = self._clamp(
            (primary_value * 0.65)
            + (secondary_value * 0.20)
            + (state.arousal * 0.15),
            0.0,
            1.0,
        )
        tension = self._clamp(
            max(
                pressure,
                state.reactive.anger,
                state.reactive.fear,
                state.reactive.discomfort,
            ),
            0.0,
            1.0,
        )
        return EmotionExpression(
            primary=primary_name if primary_value >= 0.15 else "neutral",
            secondary=secondary,
            valence=state.valence,
            arousal=state.arousal,
            expressivity=expressivity,
            tension=tension,
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
