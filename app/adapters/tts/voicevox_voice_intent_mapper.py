from __future__ import annotations

from dataclasses import dataclass

from app.shared.contracts.expression import VoiceIntent


@dataclass(frozen=True, slots=True)
class VoiceVoxParameterLimits:
    speed_min: float = 0.5
    speed_max: float = 2.0
    pitch_min: float = -0.15
    pitch_max: float = 0.15
    intonation_min: float = 0.0
    intonation_max: float = 2.0
    volume_min: float = 0.0
    volume_max: float = 2.0


class VoiceVoxVoiceIntentMapper:
    """エンジン非依存VoiceIntentをVOICEVOX用数値へ安全に変換する。"""

    def __init__(self, limits: VoiceVoxParameterLimits | None = None) -> None:
        self._limits = limits or VoiceVoxParameterLimits()

    def map(
        self,
        *,
        base_speed: float,
        base_pitch: float,
        base_intonation: float,
        base_volume: float,
        intent: VoiceIntent,
    ) -> tuple[float, float, float, float]:
        speed = self._clamp(
            base_speed * intent.speed,
            self._limits.speed_min,
            self._limits.speed_max,
        )
        pitch = self._clamp(
            base_pitch + (intent.pitch * 0.15),
            self._limits.pitch_min,
            self._limits.pitch_max,
        )
        intonation = self._clamp(
            base_intonation
            * intent.intonation
            * (1.0 + (intent.emotional_leakage * 0.25)),
            self._limits.intonation_min,
            self._limits.intonation_max,
        )
        volume = self._clamp(
            base_volume * intent.volume,
            self._limits.volume_min,
            self._limits.volume_max,
        )
        return speed, pitch, intonation, volume

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
