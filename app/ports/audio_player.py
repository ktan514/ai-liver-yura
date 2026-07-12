from __future__ import annotations

from typing import Protocol


class AudioPlayer(Protocol):
    async def play(self, audio_data: bytes) -> None:
        """WAV音声データを再生し、完了まで待機する。"""
