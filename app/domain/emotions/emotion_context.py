from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EmotionContext:
    """Character LLMへ渡す、表現判断用の感情文脈。"""

    current: Mapping[str, object]
    dominant_emotions: tuple[Mapping[str, object], ...] = ()
    mixed_emotions: tuple[Mapping[str, object], ...] = ()
    delta: Mapping[str, float] = field(default_factory=dict)
    causes: tuple[Mapping[str, object], ...] = ()
    duration_seconds: float | None = None
    emotional_pressure: float = 0.0
    expression_tendency: Mapping[str, object] = field(default_factory=dict)
    recent_history: tuple[Mapping[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "current": dict(self.current),
            "dominant_emotions": [dict(item) for item in self.dominant_emotions],
            "mixed_emotions": [dict(item) for item in self.mixed_emotions],
            "delta": dict(self.delta),
            "causes": [dict(item) for item in self.causes],
            "duration_seconds": self.duration_seconds,
            "emotional_pressure": self.emotional_pressure,
            "expression_tendency": dict(self.expression_tendency),
            "recent_history": [dict(item) for item in self.recent_history],
        }
