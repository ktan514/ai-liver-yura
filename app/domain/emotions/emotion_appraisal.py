from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmotionAppraisal:
    """感情状態へ適用する、原因付きの評価結果。"""

    arousal_delta: float = 0.0
    valence_delta: float = 0.0
    talkativeness_delta: float = 0.0
    reason: str = "no_change"
    source_event_id: str | None = None

    @property
    def has_change(self) -> bool:
        return any(
            value != 0.0
            for value in (
                self.arousal_delta,
                self.valence_delta,
                self.talkativeness_delta,
            )
        )
