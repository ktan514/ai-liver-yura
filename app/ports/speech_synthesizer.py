from __future__ import annotations

from typing import Protocol

from app.domain.emotions import EmotionState


class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str, emotion: EmotionState | None = None) -> bytes:
        """発話テキストをWAV音声データへ変換する。"""
