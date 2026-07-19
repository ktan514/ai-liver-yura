from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VoiceIntent:
    """音声エンジン非依存の、Characterが意図する話し方。"""

    style: str = "neutral"

    def __post_init__(self) -> None:
        if not self.style.strip():
            raise ValueError("voice intent styleは空にできません。")
