from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VoiceIntent:
    """音声エンジン非依存の、Characterが意図する話し方。"""

    style: str = "neutral"
    speed: float = 1.0
    pitch: float = 0.0
    intonation: float = 1.0
    volume: float = 1.0
    breathiness: float = 0.0
    emotional_leakage: float = 0.0

    def __post_init__(self) -> None:
        if not self.style.strip():
            raise ValueError("voice intent styleは空にできません。")
        self._validate_range("speed", self.speed, 0.5, 2.0)
        self._validate_range("pitch", self.pitch, -1.0, 1.0)
        self._validate_range("intonation", self.intonation, 0.0, 2.0)
        self._validate_range("volume", self.volume, 0.0, 2.0)
        self._validate_range("breathiness", self.breathiness, 0.0, 1.0)
        self._validate_range(
            "emotional_leakage",
            self.emotional_leakage,
            0.0,
            1.0,
        )

    @staticmethod
    def _validate_range(
        name: str,
        value: float,
        minimum: float,
        maximum: float,
    ) -> None:
        if not minimum <= value <= maximum:
            raise ValueError(
                f"{name} は {minimum} 以上 {maximum} 以下で指定してください。"
            )
