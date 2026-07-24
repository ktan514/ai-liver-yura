from __future__ import annotations

from typing import Protocol

from app.shared.contracts.expression import VoiceIntent


class SpeechSynthesizer(Protocol):
    async def synthesize(
        self, text: str, voice_intent: VoiceIntent | None = None
    ) -> bytes:
        """発話テキストを音声データへ変換する。"""


class AudioPlayer(Protocol):
    async def play(self, audio_data: bytes) -> None:
        """音声データを再生し、完了まで待機する。"""
